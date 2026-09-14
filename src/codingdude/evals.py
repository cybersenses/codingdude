"""R7-thin: session-replay eval harness (docs/specs/R7-thin-replay-evals.md).

Recording is an export over already-persisted session messages; replay feeds
those recorded model responses back through the engine via the scripted-model
infrastructure. Assertions are named predicates (``CHECKS``) over the replayed
outcome and trace events.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from .config import Config, load_config
from .db import Database
from .messages import decode_messages


def export_scenario(db: Database, session_id: str, name: str, checks: list[str] | None = None) -> dict:
    """Recorded scenario: first user prompt + every model response, in order."""
    from pydantic_ai.messages import ModelRequest

    prompt = None
    responses: list[dict] = []
    for message in decode_messages(db.load_messages(session_id)):
        if isinstance(message, ModelRequest):
            if prompt is None:
                for part in message.parts:
                    if getattr(part, 'part_kind', '') == 'user-prompt':
                        prompt = str(getattr(part, 'content', ''))
                        break
        else:
            responses.append(_serialize_response(message))
    if prompt is None:
        raise ValueError(f'session {session_id!r} has no recorded user prompt')
    return {'name': name, 'prompt': prompt, 'responses': responses, 'checks': checks or [],
            'notes': db.list_session_notes(session_id)}


def _serialize_response(message: ModelResponse) -> dict:
    tool_calls = []
    for part in message.parts:
        if isinstance(part, ToolCallPart):
            args = part.args
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append({'tool_name': part.tool_name, 'args': args})
    text = None
    for part in message.parts:
        if isinstance(part, TextPart):
            text = part.content
    return {'text': text, 'tool_calls': tool_calls}


def write_scenario(scenario: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scenario, indent=2) + '\n', encoding='utf-8')


def load_scenario(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


@dataclass
class Failure:
    scenario: str
    check: str
    message: str

    def __str__(self) -> str:
        return f'{self.scenario}: check {self.check!r} failed — {self.message}'


@dataclass
class _ScriptedModelSpec:
    responses: list[dict]
    issued: int = field(default=0, repr=False)


def _replay_model(spec: _ScriptedModelSpec):
    """Scripted responder: hand back recorded responses in order; when the
    recording is exhausted, stop the loop with a plain completion."""

    def fn(messages, info):
        index = spec.issued
        spec.issued += 1
        if index >= len(spec.responses):
            return ModelResponse(parts=[TextPart(content='done')])
        recorded = spec.responses[index]
        parts = [
            ToolCallPart(tool_name=call['tool_name'], args=call['args'])
            for call in recorded['tool_calls']
        ]
        if recorded['text'] is not None or not parts:
            parts.append(TextPart(content=recorded['text'] or ''))
        return ModelResponse(parts=parts)

    return fn


async def replay(
    scenario: dict,
    workdir: Path,
    home: Path,
    config: Config | None = None,
) -> dict:
    """Run the engine once against the recorded prompt with a scripted model
    built from the recorded responses. Returns outcome + trace events."""
    import sys

    from codingdude.engine import Engine

    tests_dir = Path(__file__).resolve().parents[2] / 'tests'
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from helpers import scripted  # type: ignore[import-not-found]  # test helper

    from .approvals import ApprovalPolicy

    spec = _ScriptedModelSpec(responses=scenario['responses'])
    engine = Engine(config=config or load_config(), db=Database.connect(home))
    # Supply on_event so the engine runs its streaming path — that's what
    # emits TOOL_CALL_START/END events into the trace (headless runs skip it).
    outcome = await engine.run(
        prompt=scenario['prompt'],
        workdir=workdir,
        model=scripted(_replay_model(spec)),
        approvals=ApprovalPolicy(),
        emit=lambda event: None,
    )
    return {
        'scenario': scenario['name'],
        'outcome': outcome,
        'trace': _read_trace(home, outcome.session_id),
    }


def _read_trace(home: Path, session_id: str) -> list[dict]:
    trace_file = home / 'traces' / f'{session_id}.jsonl'
    if not trace_file.exists():
        return []
    events = []
    for line in trace_file.read_text(encoding='utf-8').splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _check_user_prompt_first(result: dict) -> str | None:
    events = result['trace']
    if not events or events[0].get('type') != 'USER_PROMPT':
        return f"first trace event was {events[0].get('type') if events else 'nothing'}"
    return None


def _check_tool_call_executed(result: dict) -> str | None:
    if not any(e.get('type') == 'TOOL_CALL_START' for e in result['trace']):
        return 'no TOOL_CALL_START in trace'
    return None


def _check_plan_gated_headless(result: dict) -> str | None:
    outcome = result['outcome']
    if outcome.status != 'gate_aborted':
        return f"headless plan should abort at the gate (ADR-0003), got status {outcome.status!r}"
    if outcome.gate is None or 'plan' not in outcome.gate.command:
        return 'gate request does not mention the plan'
    return None


def _check_directive_echo(result: dict) -> str | None:
    if 'ZEBRA-RULE' not in result['outcome'].output:
        return 'output does not contain ZEBRA-RULE (verification-following skill skipped)'
    return None


CHECKS = {
    'user_prompt_first': _check_user_prompt_first,
    'tool_call_executed': _check_tool_call_executed,
    'plan_gated_headless': _check_plan_gated_headless,
    'directive_echo': _check_directive_echo,
}


async def run_scenarios(
    directory: Path,
    workdir: Path,
    home: Path,
    config: Config | None = None,
) -> list[Failure]:
    """Replay every scenario file and apply its declared checks.

    Returns readable Failure records; an empty list means the suite passed.
    """
    failures: list[Failure] = []
    for path in sorted(directory.glob('*.json')):
        scenario = load_scenario(path)
        result = await replay(scenario, workdir, home, config=config)
        for check in scenario['checks']:
            predicate = CHECKS.get(check)
            if predicate is None:
                failures.append(Failure(
                    scenario['name'], check,
                    f'unknown check {check!r} (known: {", ".join(sorted(CHECKS))})',
                ))
                continue
            message = predicate(result)
            if message:
                failures.append(Failure(scenario['name'], check, message))
    return failures

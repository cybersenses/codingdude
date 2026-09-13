"""R7-thin: replay eval harness (docs/specs/R7-thin-replay-evals.md)."""

import json
from pathlib import Path

from helpers import say, scripted
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from codingdude.config import load_config
from codingdude.db import Database
from codingdude.engine import Engine
from codingdude.evals import (
    export_scenario,
    load_scenario,
    replay,
    run_scenarios,
    write_scenario,
)


async def test_export_records_prompt_and_responses(engine, db, workdir):
    outcome = await engine.run(
        prompt='Change the greeting to hello',
        workdir=workdir,
        model=scripted(say('hello there')),
    )
    scenario = export_scenario(db, outcome.session_id, name='greet')
    assert scenario['name'] == 'greet'
    assert scenario['prompt'] == 'Change the greeting to hello'
    assert scenario['responses'] == [{'text': 'hello there', 'tool_calls': []}]
    assert scenario['checks'] == []


async def test_export_captures_tool_calls(engine, db, workdir):
    def edit(messages, info):
        calls = [
            p
            for m in messages
            for p in m.parts
            if getattr(p, 'part_kind', '') == 'tool-call'
        ]
        if not calls:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name='edit_file',
                        args={'path': 'src/app.py', 'old_text': '"hi"', 'new_text': '"hello"'},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content='done')])

    outcome = await engine.run(prompt='edit app.py', workdir=workdir, model=scripted(edit))
    scenario = export_scenario(db, outcome.session_id, name='edit')
    assert scenario['responses'][0]['tool_calls'] == [
        {
            'tool_name': 'edit_file',
            'args': {'path': 'src/app.py', 'old_text': '"hi"', 'new_text': '"hello"'},
        }
    ]


async def test_scenario_round_trips_through_json(engine, db, workdir, tmp_path):
    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('hello'))
    )
    scenario = export_scenario(db, outcome.session_id, name='rt', checks=['user_prompt_first'])
    path = tmp_path / 'rt.json'
    write_scenario(scenario, path)
    loaded = load_scenario(path)
    assert loaded == json.loads(path.read_text())
    assert loaded['checks'] == ['user_prompt_first']


async def test_replay_applies_recorded_tool_call(home, db, workdir, tmp_path):

    def edit(messages, info):
        calls = [
            p
            for m in messages
            for p in m.parts
            if getattr(p, 'part_kind', '') == 'tool-call'
        ]
        if not calls:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name='edit_file',
                        args={'path': 'src/app.py', 'old_text': '"hi"', 'new_text': '"hello"'},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content='done')])

    outcome = await engine_run_edit(home, workdir, edit)
    scenario = export_scenario(db, outcome.session_id, name='edit-replay')

    result = await replay(scenario, workdir, home)
    assert '"hello"' in (workdir / 'src' / 'app.py').read_text()
    assert result['trace'][0]['type'] == 'USER_PROMPT'


async def engine_run_edit(home, workdir, edit):
    db = Database.connect(home)
    engine = Engine(config=load_config(), db=db)
    return await engine.run(prompt='edit app.py', workdir=workdir, model=scripted(edit))


async def test_unknown_check_name_is_readable(home, workdir, tmp_path):

    scenario = {
        'name': 'mystery', 'prompt': 'hi',
        'responses': [{'text': 'hello', 'tool_calls': []}],
        'checks': ['no_such_check'],
    }
    path = tmp_path / 'mystery.json'
    write_scenario(scenario, path)

    failures = await run_scenarios(tmp_path, workdir, home)
    assert len(failures) == 1
    assert 'no_such_check' in failures[0].message
    assert 'user_prompt_first' in failures[0].message  # names the known set


async def test_failing_check_reports_readable_failure(home, workdir, tmp_path):

    scenario = {
        'name': 'skips-verification', 'prompt': 'say hi',
        'responses': [{'text': 'no-directive', 'tool_calls': []}],
        'checks': ['directive_echo'],
    }
    write_scenario(scenario, tmp_path / 'broken-skill.json')

    failures = await run_scenarios(tmp_path, workdir, home)
    assert len(failures) == 1
    assert failures[0].scenario == 'skips-verification'
    assert 'ZEBRA-RULE' in failures[0].message


async def test_passing_scenarios_yield_no_failures(home, workdir, tmp_path):

    write_scenario({
        'name': 'edit-surgical', 'prompt': 'edit app.py',
        'responses': [
            {'text': None, 'tool_calls': [
                {'tool_name': 'edit_file',
                 'args': {'path': 'src/app.py', 'old_text': '"hi"', 'new_text': '"hello"'}}
            ]},
            {'text': 'done', 'tool_calls': []},
        ],
        'checks': ['user_prompt_first', 'tool_call_executed'],
    }, tmp_path / 'edit-surgical.json')

    failures = await run_scenarios(tmp_path, workdir, home)
    assert failures == []


async def test_committed_scenario_suite(home, workdir):
    """The tracer acceptance: green scenarios pass; broken-skill fails readably."""

    scenarios = Path(__file__).parent / 'scenarios'
    failures = await run_scenarios(scenarios, workdir, home)
    names = {f.scenario for f in failures}
    assert names == {'broken-skill'}
    assert 'ZEBRA-RULE' in failures[0].message

"""CodingDude command-line entry point: --version and the headless `run` command."""

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic_ai.models import Model, infer_model

from . import __version__
from .config import config_home, load_config
from .db import Database
from .engine import Engine
from .exceptions import BudgetExceeded


def run_headless(
    engine: Engine,
    workdir: Path,
    prompt: str,
    model: Model | str | None = None,
    session_id: str | None = None,
    approvals=None,
    fix_loop: bool = False,
) -> int:
    """One-shot Headless Run (ADR-0003). Returns a process exit code:
    0 success, 1 failure, 2 gate-aborted, 3 budget-exceeded."""
    try:
        coro = engine.run(
            prompt=prompt,
            workdir=workdir,
            session_id=session_id,
            model=model,
            approvals=approvals,
            fix_loop=fix_loop,
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            outcome = asyncio.run(coro)
        else:
            # Already inside an event loop (tests, embedded use): run isolated.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                outcome = pool.submit(asyncio.run, coro).result()
    except BudgetExceeded as exc:
        print(f'budget stop: {exc}', file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — a failed run is an exit code, not a traceback
        print(f'error: {exc}', file=sys.stderr)
        return 1
    if outcome.status == 'gate_aborted':
        assert outcome.gate is not None
        print(
            f'aborted: this run needs your approval to run:\n'
            f'  {outcome.gate.command}\n'
            f'Re-run with the action approved, or pass --yolo.',
            file=sys.stderr,
        )
        return 2
    print(outcome.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='codingdude')
    parser.add_argument('--version', action='version', version=f'codingdude {__version__}')
    sub = parser.add_subparsers(dest='command')
    run = sub.add_parser('run', help='headless one-shot run (no web UI)')
    run.add_argument('prompt', help='the task for the agent')
    run.add_argument('--workdir', type=Path, default=Path.cwd())
    run.add_argument('--model', default=None, help='model override, e.g. openai:gpt-5-mini')
    run.add_argument('--yolo', action='store_true', help='run without approval gates (ADR-0003)')
    run.add_argument('--budget', type=float, default=None, help='session spend cap in USD (hard stop)')
    run.add_argument('--fix-loop', action='store_true', help='run tests after the task and feed failures back until green (max 3 rounds)')
    serve_cmd = sub.add_parser('serve', help='start the web server + UI')
    serve_cmd.add_argument('--port', type=int, default=8765)

    args = parser.parse_args(argv)
    if args.command == 'serve':
        from .server import serve

        serve(port=args.port)
        return 0
    if args.command != 'run':
        parser.print_help()
        return 0

    config = load_config()
    engine = Engine(
        config=config,
        db=Database.connect(config_home()),
        budget_cap_usd=args.budget,
    )
    if args.fix_loop:
        args.fix_loop = True
    from .approvals import ApprovalPolicy

    return run_headless(
        engine,
        args.workdir.resolve(),
        args.prompt,
        model=infer_model(args.model) if args.model else None,
        approvals=ApprovalPolicy(yolo=args.yolo),
        fix_loop=args.fix_loop,
    )


if __name__ == '__main__':
    sys.exit(main())

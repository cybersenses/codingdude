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


def run_headless(
    engine: Engine,
    workdir: Path,
    prompt: str,
    model: Model | str | None = None,
    session_id: str | None = None,
) -> int:
    """One-shot Headless Run (ADR-0003). Returns a process exit code."""
    try:
        outcome = asyncio.run(
            engine.run(prompt=prompt, workdir=workdir, session_id=session_id, model=model)
        )
    except Exception as exc:  # noqa: BLE001 — a failed run is an exit code, not a traceback
        print(f'error: {exc}', file=sys.stderr)
        return 1
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

    args = parser.parse_args(argv)
    if args.command != 'run':
        parser.print_help()
        return 0

    config = load_config()
    engine = Engine(config=config, db=Database.connect(config_home()))
    return run_headless(
        engine,
        args.workdir.resolve(),
        args.prompt,
        model=infer_model(args.model) if args.model else None,
    )


if __name__ == '__main__':
    sys.exit(main())

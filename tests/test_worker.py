"""Worker: CLI → engine.run argument wiring.

Seam: `worker.engine_run_kwargs` is the single place the worker maps its parsed
arguments onto `Engine.run`. Testing it here catches the class of bug where a
flag is parsed but never forwarded (self-review H2: `--fix-loop`).
"""

import argparse
from pathlib import Path


def _args(**over) -> argparse.Namespace:
    base = dict(
        prompt='do a thing',
        workdir=str(Path.cwd()),
        session='sess1',
        fix_loop=False,
        image=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_engine_run_kwargs_forwards_fix_loop():
    from codingdude import worker

    kwargs = worker.engine_run_kwargs(_args(fix_loop=True), model='m')
    assert kwargs['fix_loop'] is True
    assert kwargs['prompt'] == 'do a thing'
    assert kwargs['session_id'] == 'sess1'
    assert kwargs['model'] == 'm'
    assert kwargs['image_path'] is None


def test_engine_run_kwargs_defaults_fix_loop_off_and_resolves_workdir(tmp_path):
    from codingdude import worker

    kwargs = worker.engine_run_kwargs(_args(workdir=str(tmp_path)), model=None)
    assert kwargs['fix_loop'] is False
    assert kwargs['workdir'] == tmp_path.resolve()


def test_engine_run_kwargs_resolves_image_path(tmp_path):
    from codingdude import worker

    img = tmp_path / 'shot.png'
    img.write_bytes(b'x')
    kwargs = worker.engine_run_kwargs(_args(image=str(img)), model=None)
    assert kwargs['image_path'] == img.resolve()

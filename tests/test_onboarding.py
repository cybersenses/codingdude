# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Project onboarding: first-run discovery of a project's conventions.

Gap being closed: an agent taking over a project from another tool had no
enforced step to discover *where work is tracked* (GitHub Issues, ROADMAP.md,
docs) or the project's gates, so default behaviors won and work went unlogged.
"""
from __future__ import annotations

from pathlib import Path

from codingdude.directives import build_directive_layers
from codingdude.memory import MemoryStore
from codingdude.onboarding import MARKER, mark_onboarded, onboarding_needed


def test_fresh_workdir_needs_onboarding(db, tmp_path):
    assert onboarding_needed(MemoryStore(db), tmp_path) is True


def test_onboarding_done_once_convention_memory_exists(db, tmp_path):
    store = MemoryStore(db)
    mark_onboarded(store, tmp_path, 'tracker: GitHub Issues (gh); tests: pytest -q')
    assert onboarding_needed(store, tmp_path) is False


def test_other_workdir_does_not_satisfy_onboarding(db, tmp_path):
    store = MemoryStore(db)
    mark_onboarded(store, tmp_path / 'other', 'tracker: ROADMAP.md')
    assert onboarding_needed(store, tmp_path) is True


def test_mark_onboarded_forces_marker_prefix(db, tmp_path):
    store = MemoryStore(db)
    mark_onboarded(store, tmp_path, 'tests: ruff+mypy')
    assert any(MARKER in r['content'] for r in store.all_entries())


def test_instructions_inject_onboarding_block_when_fresh(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from codingdude.onboarding import onboarding_block
    from codingdude.run_pipeline import PromptAssembler

    assembler = PromptAssembler()
    services = _services_stub(db, tmp_path)
    text = assembler.instructions(
        services, tmp_path, 'do the thing', _empty_registry(),
        MemoryStore(db), embedder=None,
    )
    assert 'Project onboarding' in text
    assert onboarding_block() in text


def test_instructions_skip_onboarding_when_recorded(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = MemoryStore(db)
    mark_onboarded(store, tmp_path, 'tracker: GitHub Issues')
    from codingdude.run_pipeline import PromptAssembler

    assembler = PromptAssembler()
    text = assembler.instructions(
        _services_stub(db, tmp_path), tmp_path, 'do the thing',
        _empty_registry(), store, embedder=None,
    )
    assert 'Project onboarding' not in text


def test_builtin_ticket_directive_always_present(db, tmp_path):
    """The standing 'tracked item before non-trivial work' rule ships built-in,
    even with no DIRECTIVES.md or AGENT.md on disk."""
    text = build_directive_layers(Path.home() / '_no_such_dir_', tmp_path)
    assert 'tracked item' in text
    assert 'non-trivial work' in text


# --- stubs ---------------------------------------------------------------

class _Config:
    models = type('M', (), {'request_limit': 50, 'max_tokens': None})()


def _services_stub(db, workdir):
    from codingdude.run_pipeline import RunServices

    return RunServices(
        _Config(), db, workdir, extraction_model=lambda: None,
    )


def _empty_registry():
    class _R:
        def index(self):
            return []

        def matching(self, prompt):
            return []
    return _R()

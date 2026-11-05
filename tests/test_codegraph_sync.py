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
"""R75: an existing codegraph index must be *updated*, not re-inited.

`codegraph init` no-ops on an existing index (prints "Already initialized",
never rebuilds), so the #203 stale self-heal and the R14 mid-run refresh
both ran forever without changing anything — the graph stayed stale and
every session re-printed the banner. New contract:
  index missing  -> init
  index stale    -> sync, falling back to `index` (full rebuild) on failure
"""

import os
import time
import types

from codingdude.codegraph_boot import boot_codegraph, refresh_codegraph_index


def _stale_fixture(tmp_path):
    """A present index older than a source file (index_is_stale == True)."""
    (tmp_path / '.codegraph').mkdir()
    idx = tmp_path / '.codegraph' / 'index.bin'
    idx.write_bytes(b'x')
    (tmp_path / 'app.py').write_text('x = 1', encoding='utf-8')
    now = time.time()
    os.utime(idx, (now - 100, now - 100))
    os.utime(tmp_path / 'app.py', (now, now))


def _capturing_runner(results=None):
    """Runner that records argv; per-call returncodes via [('sync', rc)...]."""
    calls = []
    results = results or []

    def runner(cmd, cwd, timeout=None):
        sub = cmd[3] if len(cmd) > 3 else ''
        calls.append((sub, list(cmd)))
        rc = next((r for name, r in results if name == sub), 0)
        return types.SimpleNamespace(returncode=rc, stdout=f'{sub} out')

    runner.calls = calls
    return runner


# --- boot: stale index updates via sync --------------------------------------

def test_boot_syncs_stale_index_instead_of_init(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner()
    status = boot_codegraph(tmp_path, runner=runner, cli_path='/fake')
    assert status['status'] == 'ok'
    assert status['reason'] == 'index was stale; synced'
    subs = [sub for sub, _ in runner.calls]
    assert subs == ['sync']


def test_boot_stale_sync_failure_falls_back_to_rebuild(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner(results=[('sync', 1)])
    status = boot_codegraph(tmp_path, runner=runner, cli_path='/fake')
    assert status['status'] == 'ok'
    assert status['reason'] == 'index was stale; rebuilt'
    subs = [sub for sub, _ in runner.calls]
    assert subs == ['sync', 'index']


def test_boot_stale_both_fail_reports_failure(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner(results=[('sync', 1), ('index', 1)])
    status = boot_codegraph(tmp_path, runner=runner, cli_path='/fake')
    assert status['status'] == 'failed'
    assert 'stale index refresh failed' in status['reason']


def test_boot_missing_index_still_inits(tmp_path):
    runner = _capturing_runner()
    status = boot_codegraph(tmp_path, runner=runner, cli_path='/fake')
    assert status == {'status': 'ok', 'reason': None}
    assert [sub for sub, _ in runner.calls] == ['init']


# --- refresh: existing index syncs, missing index inits ----------------------

def test_refresh_syncs_existing_index(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner()
    out = refresh_codegraph_index(tmp_path, runner=runner, cli_path='/fake')
    assert out == 'sync out'
    assert [sub for sub, _ in runner.calls] == ['sync']


def test_refresh_sync_failure_falls_back_to_rebuild(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner(results=[('sync', 1)])
    out = refresh_codegraph_index(tmp_path, runner=runner, cli_path='/fake')
    assert out == 'index out'
    assert [sub for sub, _ in runner.calls] == ['sync', 'index']


def test_refresh_both_fail_is_none(tmp_path):
    _stale_fixture(tmp_path)
    runner = _capturing_runner(results=[('sync', 1), ('index', 1)])
    assert refresh_codegraph_index(tmp_path, runner=runner, cli_path='/fake') is None


def test_refresh_missing_index_inits(tmp_path):
    runner = _capturing_runner()
    out = refresh_codegraph_index(tmp_path, runner=runner, cli_path='/fake')
    assert out == 'init out'
    assert [sub for sub, _ in runner.calls] == ['init']

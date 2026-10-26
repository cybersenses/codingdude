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
"""Workdir walker seams (#255): the tree/files/renders scans must skip side
venvs (.venv-verify & friends), not just .venv — a side venv holds a full
site-packages tree and made /sessions/{id}/tree take ~38s / 2 MB on
G:\\pydantic."""

import httpx
from test_server import auth, create_session, server  # noqa: F401 - pytest fixture


def _paths(node, acc=None):
    acc = [] if acc is None else acc
    acc.append(node['path'])
    for child in node.get('children', []):
        _paths(child, acc)
    return acc


def test_tree_skips_side_venvs(server, tmp_path):  # noqa: F811 - fixture param shadows import
    """`.venv*` (any suffix), not just the exact name `.venv`: a workdir with
    a .venv-verify side venv must not leak it into the explorer tree."""
    app, base = server
    workdir = tmp_path / 'walker-proj'
    (workdir / 'src').mkdir(parents=True)
    (workdir / 'src' / 'main.py').write_text('x = 1\n', encoding='utf-8')
    (workdir / '.venv' / 'lib').mkdir(parents=True)
    (workdir / '.venv-verify' / 'lib' / 'site-packages').mkdir(parents=True)
    (workdir / '.venv-verify' / 'lib' / 'site-packages' / 'pkg.py').write_text(
        'y = 2\n', encoding='utf-8'
    )
    session_id = create_session(base, workdir)

    tree = httpx.get(
        f'{base}/sessions/{session_id}/tree', headers=auth(), timeout=10
    ).json()
    paths = _paths(tree)
    assert 'src/main.py' in paths
    assert not any(p.startswith('.venv') for p in paths), (
        f'side venv leaked into tree: {[p for p in paths if p.startswith(".venv")]}'
    )


def test_files_listing_skips_side_venvs(server, tmp_path):  # noqa: F811 - fixture param shadows import
    app, base = server
    workdir = tmp_path / 'walker-files'
    workdir.mkdir(parents=True)
    (workdir / 'notes.txt').write_text('hi\n', encoding='utf-8')
    (workdir / '.venv-verify' / 'lib').mkdir(parents=True)
    (workdir / '.venv-verify' / 'lib' / 'site-packages.py').write_text(
        'z = 3\n', encoding='utf-8'
    )
    session_id = create_session(base, workdir)
    # create_session's workdir.mkdir runs before we add files, so the
    # listing sees them; endpoint caps at 500 entries which we are under.
    files = httpx.get(
        f'{base}/sessions/{session_id}/files', headers=auth(), timeout=10
    ).json()
    assert 'notes.txt' in ' '.join(files)
    assert not any('.venv-verify' in f for f in files)


def test_renders_scan_skips_side_venvs(server, tmp_path):  # noqa: F811 - fixture param shadows import
    app, base = server
    workdir = tmp_path / 'walker-renders'
    workdir.mkdir()
    (workdir / 'shot.png').write_bytes(b'\x89PNG fake')
    (workdir / '.venv-verify' / 'assets').mkdir(parents=True)
    (workdir / '.venv-verify' / 'assets' / 'leak.png').write_bytes(b'\x89PNG leak')
    session_id = create_session(base, workdir)
    data = httpx.get(
        f'{base}/sessions/{session_id}/renders', headers=auth(), timeout=10
    ).json()
    paths = [r['path'] for r in data['renders']]
    assert 'shot.png' in paths
    assert not any('.venv-verify' in p for p in paths)

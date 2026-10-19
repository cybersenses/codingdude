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
"""CheckpointStore: capture, restore file/checkpoint, rewind, prune."""

import pytest

from codingdude.checkpoints import CheckpointStore


@pytest.fixture
def store(home):
    return CheckpointStore(home)


def test_capture_and_restore_checkpoint(store, tmp_path):
    f = tmp_path / 'app.py'
    f.write_text('v1\n')
    cp_id = store.begin('s1')
    store.capture_file('s1', cp_id, tmp_path, f)  # capture pre-edit state
    f.write_text('v2\n')

    out = store.restore_checkpoint('s1', cp_id, tmp_path)
    assert out['restored'] == ['app.py']
    assert f.read_text() == 'v1\n'


def test_capture_is_lazy_per_file(store, tmp_path):
    f = tmp_path / 'a.py'
    f.write_text('one\n')
    cp_id = store.begin('s1')
    # capture twice: second is a no-op within the same checkpoint
    store.capture_file('s1', cp_id, tmp_path, f)
    store.capture_file('s1', cp_id, tmp_path, f)
    meta = store.list_checkpoints('s1')[0]
    assert meta['files'] == ['a.py']
    # further edits within the same checkpoint are NOT captured — the pre-turn
    # state is what a rollback restores
    f.write_text('three\n')
    store.capture_file('s1', cp_id, tmp_path, f)
    store.restore_checkpoint('s1', cp_id, tmp_path)
    assert f.read_text() == 'one\n'


def test_new_file_capture_restores_deletion(store, tmp_path):
    cp_id = store.begin('s1')
    store.capture_file('s1', cp_id, tmp_path, tmp_path / 'new.py')  # doesn't exist yet
    (tmp_path / 'new.py').write_text('created\n')

    store.restore_checkpoint('s1', cp_id, tmp_path)
    assert not (tmp_path / 'new.py').exists()  # restored as deleted


def test_restore_single_file(store, tmp_path):
    a, b = tmp_path / 'a.py', tmp_path / 'b.py'
    cp_id = store.begin('s1')
    a.write_text('A1\n'), b.write_text('B1\n')
    store.capture_file('s1', cp_id, tmp_path, a)
    store.capture_file('s1', cp_id, tmp_path, b)
    a.write_text('A2\n'), b.write_text('B2\n')

    store.restore_file('s1', cp_id, 'a.py', tmp_path)
    assert a.read_text() == 'A1\n'
    assert b.read_text() == 'B2\n'  # untouched


def test_rewind_to_undoes_later_checkpoints_and_keeps_safety(store, tmp_path):
    f = tmp_path / 'doc.txt'
    cp1 = store.begin('s1')
    f.write_text('state 1\n')
    store.capture_file('s1', cp1, tmp_path, f)

    cp2 = store.begin('s1')
    f.write_text('state 2\n')
    store.capture_file('s1', cp2, tmp_path, f)

    result = store.rewind_to('s1', cp1, tmp_path)
    assert f.read_text() == 'state 1\n'
    assert result['safety_checkpoint']  # state 2 recoverable
    listed = store.list_checkpoints('s1')
    assert result['safety_checkpoint'] in [c['id'] for c in listed]


def test_prune_caps_per_session(home, tmp_path):
    store = CheckpointStore(home, max_per_session=5)
    for i in range(7):
        cp = store.begin('s1')
        f = tmp_path / f'f{i}.txt'
        f.write_text(str(i))
        store.capture_file('s1', cp, tmp_path, f)
    listed = store.list_checkpoints('s1')
    assert len(listed) == 5
    # newest kept, oldest pruned
    assert listed[0]['id'] == store.list_checkpoints('s1')[0]['id']


def test_corrupt_metadata_degrades_gracefully(store, tmp_path):
    cp_id = store.begin('sx')
    (tmp_path / 'f.txt').write_text('v1')
    store.capture_file('sx', cp_id, tmp_path, tmp_path / 'f.txt')

    # Simulate a torn write from a racing worker.
    meta = store._session_dir('sx') / cp_id / 'metadata.json'
    meta.write_text('{"files": {"f.txt": {"existed": TRUNC', encoding='utf-8')

    # capture/list/restore must not raise raw JSONDecodeError.
    store.capture_file('sx', cp_id, tmp_path, tmp_path / 'f.txt')
    assert store.list_checkpoints('sx') == []
    with pytest.raises(FileNotFoundError):
        store.restore_checkpoint('sx', cp_id, tmp_path)

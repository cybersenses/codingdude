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
"""R85: wireframe packs — DSL v1, strict validation at the emit chokepoint."""

import json
import re
from pathlib import Path

import pytest

from codingdude.artifacts import ArtifactStore, build_artifacts_toolset
from codingdude.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.connect(tmp_path / 'home')


@pytest.fixture
def session(db: Database) -> str:
    return db.create_session(Path.cwd(), title='wireframes')


@pytest.fixture
def store(db: Database, session: str) -> ArtifactStore:
    return ArtifactStore(db, session)


def _minimal_pack() -> dict:
    return {
        'version': 1,
        'screens': [{
            'id': 'settings', 'title': 'Settings', 'template': 'nav main',
            'regions': [
                {'name': 'nav', 'widget': 'nav', 'label': 'Sections'},
                {'name': 'main', 'widget': 'form', 'label': 'Provider settings'},
            ],
        }],
        'flows': [],
    }


def test_emit_wireframe_round_trip(store):
    artifact_id = store.emit_wireframe(_minimal_pack(), 'Config redesign')
    listed = store.list()
    assert listed[0]['kind'] == 'wireframe'
    assert listed[0]['title'] == 'Config redesign'
    assert listed[0]['payload']['version'] == 1
    assert store.feedback(artifact_id) is None  # pending until the user edits


def test_wireframe_rejects_unknown_screen_reference(store):
    pack = _minimal_pack()
    pack['flows'] = [{'from': 'settings', 'to': 'nowhere', 'trigger': 'Save'}]
    with pytest.raises(ValueError, match='nowhere'):
        store.emit_wireframe(pack, 'bad flow')


def test_wireframe_batches_all_violations_into_one_error(store):
    pack = {
        'version': 2,
        'screens': [
            {'id': 'settings', 'title': 'Settings', 'template': 'nav main',
             'regions': [{'name': 'nav'}, {'name': 'phantom'}]},
            {'id': 'settings', 'title': 7, 'template': '  ',
             'regions': [{'name': 'ghost'}]},
        ],
        'flows': [{'from': 'a', 'to': 'b'}],
    }
    with pytest.raises(ValueError) as exc:
        store.emit_wireframe(pack, 'broken')
    message = str(exc.value)
    for expected in (
        'version', 'duplicated', 'title must be a string', 'template',
        "'phantom'", "'ghost'", "'a'", "'b'",
    ):
        assert expected in message, f'missing {expected!r} in: {message}'


def test_wireframe_tolerates_unknown_widgets_and_extra_fields(store):
    pack = _minimal_pack()
    pack['extra'] = {'ignored': True}
    pack['screens'][0]['regions'][0]['widget'] = 'hologram'
    pack['screens'][0]['regions'][1]['mystery'] = 'whatever'
    store.emit_wireframe(pack, 'tolerant')
    assert store.list()[0]['payload']['screens'][0]['regions'][0]['widget'] == 'hologram'


def test_wireframe_allows_single_screen_without_flows(store):
    pack = _minimal_pack()
    del pack['flows']
    store.emit_wireframe(pack, 'one screen')
    assert store.list()[0]['payload'].get('flows') is None  # stored as-is


def test_wireframe_dot_filler_areas_need_no_region(store):
    pack = _minimal_pack()
    pack['screens'][0]['template'] = 'nav main\n. side'
    pack['screens'][0]['regions'].append({'name': 'side', 'widget': 'text'})
    store.emit_wireframe(pack, 'filler ok')


def test_wireframe_rejects_non_object_payload(store):
    with pytest.raises(ValueError, match='JSON object'):
        store.emit_wireframe(['not', 'an', 'object'], 'junk')


async def test_toolset_emits_wireframe(db, session):
    toolset = build_artifacts_toolset(db, session)
    tools = toolset.tools

    out = tools['emit_wireframe'].function(_minimal_pack(), 'Config redesign')
    artifact_id = re.search(r'id=([A-Za-z0-9_-]+)', out).group(1)
    assert ArtifactStore(db, session).feedback(artifact_id) is None  # pending
    assert ArtifactStore(db, session).list()[0]['kind'] == 'wireframe'

    bad = _minimal_pack()
    bad['flows'] = [{'from': 'settings', 'to': 'void'}]
    with pytest.raises(ValueError, match='known screen id'):
        tools['emit_wireframe'].function(bad, 'bad')


def test_respond_accepts_inline_edits_on_a_wireframe(store):
    artifact_id = store.emit_wireframe(_minimal_pack(), 'Config redesign')
    edited = _minimal_pack()
    edited['screens'][0]['title'] = 'Settings (edited)'
    store.respond(artifact_id, {'content': json.dumps(edited)})
    feedback = store.feedback(artifact_id)
    assert feedback['content'].startswith('{')
    assert 'Settings (edited)' in feedback['content']


def test_wireframe_rejects_empty_or_malformed_screens(store):
    with pytest.raises(ValueError, match='screens must be a non-empty list'):
        store.emit_wireframe({'version': 1, 'screens': []}, 'no screens')
    pack = _minimal_pack()
    pack['screens'] = ['junk']
    with pytest.raises(ValueError, match=r'screens\[0\] must be an object'):
        store.emit_wireframe(pack, 'screen junk')
    pack = _minimal_pack()
    pack['screens'][0]['id'] = 7
    with pytest.raises(ValueError, match='id must be a non-empty string'):
        store.emit_wireframe(pack, 'id junk')


def test_wireframe_rejects_missing_or_malformed_regions(store):
    pack = _minimal_pack()
    del pack['screens'][0]['regions']
    with pytest.raises(ValueError, match='regions must be a non-empty list'):
        store.emit_wireframe(pack, 'no regions')
    pack = _minimal_pack()
    pack['screens'][0]['regions'] = ['junk']
    with pytest.raises(ValueError, match=r'regions\[0\] must be an object'):
        store.emit_wireframe(pack, 'region junk')


def test_wireframe_rejects_bad_region_names(store):
    pack = _minimal_pack()
    pack['screens'][0]['regions'].append({'name': 'nav'})  # duplicate
    with pytest.raises(ValueError, match="'nav' is duplicated"):
        store.emit_wireframe(pack, 'dup region')
    pack = _minimal_pack()
    pack['screens'][0]['regions'].append({'widget': 'nav'})  # no name at all
    with pytest.raises(ValueError, match='name must be a non-empty string'):
        store.emit_wireframe(pack, 'nameless region')


def test_wireframe_rejects_non_string_optional_fields(store):
    pack = _minimal_pack()
    pack['screens'][0]['regions'][0]['widget'] = 7
    pack['flows'] = [{'from': 'settings', 'to': 'settings', 'trigger': 3}]
    with pytest.raises(ValueError) as exc:
        store.emit_wireframe(pack, 'wrong types')
    message = str(exc.value)
    assert 'widget must be a string when present' in message
    assert 'trigger must be a string when present' in message


def test_wireframe_rejects_malformed_flows(store):
    pack = _minimal_pack()
    pack['flows'] = 'not a list'
    with pytest.raises(ValueError, match='flows must be a list when present'):
        store.emit_wireframe(pack, 'flows junk')
    pack = _minimal_pack()
    pack['flows'] = ['not an object']
    with pytest.raises(ValueError, match=r'flows\[0\] must be an object'):
        store.emit_wireframe(pack, 'flow junk')
    pack = _minimal_pack()
    pack['flows'] = [{'from': 1, 'to': 2}]
    with pytest.raises(ValueError, match='from must be a non-empty string'):
        store.emit_wireframe(pack, 'edge junk')


def test_wireframe_rejects_bool_version(store):
    pack = _minimal_pack()
    pack['version'] = True  # True == 1 in Python; a bool is not a version
    with pytest.raises(ValueError, match='version must be 1'):
        store.emit_wireframe(pack, 'bool version')


async def test_revision_loop_emit_edit_reemit(db, session):
    """#315 contract: the revision loop end to end — emit -> user inline edit
    -> agent reads it back -> whole-pack re-emission, newest-first."""
    tools = build_artifacts_toolset(db, session).tools
    out = tools['emit_wireframe'].function(_minimal_pack(), 'Config redesign')
    first_id = re.search(r'id=([A-Za-z0-9_-]+)', out).group(1)

    # The user edits the pack inline (respond's content branch)…
    edited = _minimal_pack()
    edited['screens'][0]['regions'][1]['label'] = 'Provider settings (user edit)'
    ArtifactStore(db, session).respond(first_id, {'content': json.dumps(edited)})

    # …the agent reads that edit back as a requirement…
    feedback = json.loads(tools['get_artifact_feedback'].function(first_id))
    assert 'Provider settings (user edit)' in feedback['content']

    # …and re-emits the WHOLE pack incorporating it.
    revised = json.loads(feedback['content'])
    revised['screens'][0]['regions'][0]['notes'] = 'kept; nav unchanged per user'
    out2 = tools['emit_wireframe'].function(revised, 'Config redesign — revised')
    second_id = re.search(r'id=([A-Za-z0-9_-]+)', out2).group(1)
    assert second_id != first_id

    listed = ArtifactStore(db, session).list()  # newest first
    assert listed[0]['id'] == second_id
    assert listed[0]['payload']['screens'][0]['regions'][1]['label'] == 'Provider settings (user edit)'
    assert listed[1]['id'] == first_id
    # The original keeps the user's edit on record; the new pack is pending.
    assert ArtifactStore(db, session).feedback(first_id) is not None
    assert ArtifactStore(db, session).feedback(second_id) is None

class TestWidgetVocabularyPinned:
    """#320: the widget vocabulary v1 is written in three places — the
    emit_wireframe tool docstring (the contract agents read), the frontend
    renderer's WIDGETS set, and the authoring SKILL. One canonical list; this
    pin keeps them from silently desyncing (the reviewer found nothing
    enforcing it). Currently green by design — it is a guard, not a fix."""

    CANONICAL = [
        'nav', 'header', 'form', 'table', 'list', 'text', 'chart',
        'actions', 'tabs', 'image', 'code', 'placeholder',
    ]

    def _repo_file(self, *parts: str) -> str:
        return (Path(__file__).resolve().parents[1] / Path(*parts)).read_text(encoding='utf-8')

    def test_docstring_lists_the_canonical_vocabulary(self):
        doc = self._repo_file('src', 'codingdude', 'artifacts.py')
        # The line wraps in source; capture up to the em-dash and split loose.
        m = re.search(r'Widget vocabulary v1: (.*?) — ', doc, re.S)
        assert m, 'emit_wireframe docstring lost its vocabulary line'
        assert [w for w in re.split(r'[\s,]+', m.group(1).strip()) if w] == self.CANONICAL

    def test_frontend_renderer_set_matches(self):
        src = self._repo_file('frontend', 'src', 'WireframeView.jsx')
        m = re.search(r'WIDGETS = new Set\(\[([^\]]+)\]\)', src)
        assert m, 'WireframeView.jsx lost its WIDGETS set'
        widgets = [w.strip().strip(chr(39) + chr(34)) for w in m.group(1).split(',')]
        assert widgets == self.CANONICAL

    def test_authoring_skill_matches(self):
        skill = self._repo_file('.codingdude-seed', 'skills', 'wireframes', 'SKILL.md')
        m = re.search(r'vocabulary: `([a-z, ]+)`', skill)
        assert m, 'SKILL.md lost its widget vocabulary line'
        assert [w.strip() for w in m.group(1).split(',')] == self.CANONICAL

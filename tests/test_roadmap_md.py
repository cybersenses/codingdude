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
"""ROADMAP.md is the canonical roadmap source; the Planning tab must serve it live."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codingdude.roadmap import parse_roadmap_md, upsert_roadmap_md

SAMPLE = """\
# CodingDude — Feature Roadmap

Status is one of `open`, `in-progress`, `done`.

## R1 — Rendered output surface
**Status:** done · **Area:** observability

Shipped: an `inspect_image` agent tool.

### Problem
It could not see images.

## R2 — Agent appears to hang after the user replies
**Status:** in-progress · **Area:** run lifecycle

Reattach with backoff.

## R99 — Something open
**Status:** open

Not started.
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'ROADMAP.md'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return path


def test_parse_roadmap_md_sections(tmp_path: Path) -> None:
    items = parse_roadmap_md(_write(tmp_path, SAMPLE))
    assert [i['id'] for i in items] == ['R1', 'R2', 'R99']
    assert items[0]['title'] == 'Rendered output surface'
    assert items[0]['status'] == 'done'
    assert 'inspect_image' in items[0]['body']
    assert '### Problem' in items[0]['body']
    assert items[1]['status'] == 'in_progress'  # normalized
    assert items[2]['status'] == 'open'


def test_parse_roadmap_md_status_bold_with_value(tmp_path: Path) -> None:
    """Tolerates `**Status: DONE** ...` (bold wraps the value, not just the label)."""
    text = (
        '## R12 — Thing\n'
        '**Status: DONE** (commit `abc1234`).\n\n'
        'Body.\n'
    )
    items = parse_roadmap_md(_write(tmp_path, text))
    assert items[0]['status'] == 'done'


def test_upsert_roadmap_md_replaces_bold_value_status(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE.replace(
        '**Status:** open', '**Status: OPEN** (some note)'))
    upsert_roadmap_md(path, 'R99', status='done')
    items = parse_roadmap_md(path)
    assert items[2]['status'] == 'done'


def test_parse_roadmap_md_crlf_blank_line(tmp_path: Path) -> None:
    """CRLF/LF mix must not hide the status line from the first paragraph."""
    text = '## R12 — Thing\r\n\r\n**Status:** done (commit `abc`).\r\n\r\nBody.\r\n'
    items = parse_roadmap_md(_write(tmp_path, text))
    assert items[0]['status'] == 'done'


def test_parse_roadmap_md_missing_status_defaults_open(tmp_path: Path) -> None:
    text = '## R7 — No status line\n\nBody only.\n'
    items = parse_roadmap_md(_write(tmp_path, text))
    assert items[0]['status'] == 'open'


def test_upsert_roadmap_md_status(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE)
    upsert_roadmap_md(path, 'R2', status='done')
    items = parse_roadmap_md(path)
    assert items[1]['status'] == 'done'
    # untouched sections byte-identical
    assert items[0]['status'] == 'done'
    assert 'Reattach with backoff.' in items[1]['body']
    # CRLF/other endings preserved for untouched text
    with open(path, encoding='utf-8', newline='') as f:
        raw = f.read()
    assert 'in-progress' not in raw.split('## R99')[0].split('## R2')[1]


def test_upsert_roadmap_md_append(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE)
    upsert_roadmap_md(path, None, title='Brand new item', body='Fresh idea.')
    items = parse_roadmap_md(path)
    assert items[-1]['id'] == 'R100'
    assert items[-1]['title'] == 'Brand new item'
    assert items[-1]['status'] == 'open'
    assert 'Fresh idea.' in items[-1]['body']


@pytest.fixture()
def client_with_roadmap(tmp_path, monkeypatch):
    from codingdude.server import create_app

    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    with open(tmp_path / 'ROADMAP.md', 'w', encoding='utf-8', newline='') as f:
        f.write(SAMPLE)
    app = create_app(home=tmp_path / 'home', token='test-token', allow_testclient=True)
    app.state.port = 8000

    with TestClient(app) as c:
        yield c, app.state.token, str(tmp_path / 'ROADMAP.md')


def test_planning_endpoint_serves_roadmap_file(client_with_roadmap, tmp_path) -> None:
    c, token, _ = client_with_roadmap
    h = {'Authorization': f'Bearer {token}'}
    resp = c.get(f'/planning?workdir={tmp_path}', headers=h)
    assert resp.status_code == 200
    road = resp.json()['roadmap']
    assert [i['id'] for i in road] == ['R1', 'R2', 'R99']


def test_roadmap_update_writes_back_to_file(client_with_roadmap, tmp_path) -> None:
    c, token, md = client_with_roadmap
    h = {'Authorization': f'Bearer {token}'}
    resp = c.put(f'/planning/roadmap/R99?workdir={tmp_path}', json={'status': 'done'}, headers=h)
    assert resp.status_code == 200
    items = parse_roadmap_md(Path(md))
    assert items[2]['status'] == 'done'


def test_roadmap_create_appends_to_file(client_with_roadmap, tmp_path) -> None:
    c, token, md = client_with_roadmap
    h = {'Authorization': f'Bearer {token}'}
    resp = c.post(f'/planning/roadmap?workdir={tmp_path}', json={'title': 'Next thing'}, headers=h)
    assert resp.status_code == 200
    items = parse_roadmap_md(Path(md))
    assert items[-1]['title'] == 'Next thing'
    assert items[-1]['status'] == 'open'


# ---- the shipped ROADMAP.md itself (R86 #348) -------------------------
#
# These guard the file the planning tools actually read, not a synthetic one.
# A heading the parser cannot see is worse than a duplicated one: it vanishes
# from list_planning, create_ticket and update_roadmap_item while still looking
# present in the file.

SHIPPED_ROADMAP = Path(__file__).resolve().parent.parent / 'ROADMAP.md'
#: A heading that claims to be a roadmap item.
_ITEM_HEADING = re.compile(r'^## R\d+')
#: The #348 defect, own id repeated: `## R83 — R83: Composer`, `## R31 — R31 Run-end`.
_OWN_ID_REPEATED = re.compile(r'^## (R\d+) \u2014 \1[: \u2014]')
#: The same defect with a *mismatched* id — a stale prefix copied from a
#: neighbouring heading: `## R24 — R22 — File-tools`. A same-id pattern misses
#: this, and the heading delimiter (`—` / `:`) is what distinguishes it from a
#: legitimate cross-reference such as `## R89 — R86 review findings …`, where the
#: second id is followed by prose and carries meaning.
_STALE_ID_PREFIX = re.compile(r'^## R\d+ \u2014 R\d+ ?[\u2014:]')


def _shipped_lines() -> list[str]:
    return SHIPPED_ROADMAP.read_text(encoding='utf-8').splitlines()


def test_every_item_heading_in_the_shipped_roadmap_parses() -> None:
    headings = [line for line in _shipped_lines() if _ITEM_HEADING.match(line)]
    assert len(parse_roadmap_md(SHIPPED_ROADMAP)) == len(headings)


def test_no_shipped_heading_repeats_an_id_prefix() -> None:
    doubled = [
        line for line in _shipped_lines()
        if _OWN_ID_REPEATED.match(line) or _STALE_ID_PREFIX.match(line)
    ]
    assert doubled == [], f'heading carries a second id prefix: {doubled}'


def test_a_cross_referencing_heading_is_not_mistaken_for_a_duplicate() -> None:
    """`R89 — R86 review findings …` keeps its reference: a bare space after a
    different id is prose, not a heading prefix."""
    assert _OWN_ID_REPEATED.match('## R89 \u2014 R86 review findings out of scope') is None
    assert _STALE_ID_PREFIX.match('## R89 \u2014 R86 review findings out of scope') is None
    # …while both real defect shapes are caught:
    assert _OWN_ID_REPEATED.match('## R83 \u2014 R83: Composer')
    assert _STALE_ID_PREFIX.match('## R24 \u2014 R22 \u2014 File-tools hardening')


def test_shipped_roadmap_ids_are_unique() -> None:
    ids = [item['id'] for item in parse_roadmap_md(SHIPPED_ROADMAP)]
    assert len(ids) == len(set(ids))


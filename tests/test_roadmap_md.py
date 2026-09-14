"""ROADMAP.md is the canonical roadmap source; the Planning tab must serve it live."""

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

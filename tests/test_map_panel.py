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
"""R103 #377: the server side of the Map panel — the page, its cache policy,
and an empty state that says where it looked.

The page is served as a file, not carried as an artifact payload: it is 2.6 MB
with ELK and the fonts inlined, and the artifacts endpoint is polled, so the
payload route would re-serialize it continuously. What is asserted here is the
contract the panel depends on — `built` or a reason, and bytes that must
revalidate (a rebuild has to reach the frame without a hard refresh).
"""

import asyncio
import time
from pathlib import Path

import pytest

from codingdude import floorplan


@pytest.fixture(autouse=True)
def _isolated_home(home):
    """Pin the config home for every test here (decision #107).

    The map now lives under the config home rather than in the project, so
    without this these tests would read and write the developer's real
    `~/.codingdude/maps` — silently, because the route only reports a path.
    """
    return home


@pytest.fixture(autouse=True)
def _floorplan_present(monkeypatch):
    """Both halves of availability, pinned (#379).

    `/map/state` now answers "can this be built at all", and that is `available()`
    — so the node probe is stubbed here rather than being asked of the machine,
    or the empty-state assertion changes shape on a host without node.
    """
    from codingdude.tools import Captured

    async def version(argv, **kwargs):
        return Captured(code=0, stdout='v22.0.0\n', stderr='')

    monkeypatch.setattr(floorplan, 'node_binary', lambda: 'node')
    monkeypatch.setattr(floorplan, 'run_captured', version)
    monkeypatch.setattr(floorplan, 'floorplan_home', lambda *a, **k: Path('C:/floorplan'))


def _app(tmp_path):
    from test_lane import _test_app

    client, headers = _test_app(tmp_path)
    # Every request in this module is authenticated; putting the bearer on the
    # client keeps the tests about the map routes rather than about headers.
    client.headers.update(headers)
    return client, headers


def _session(client, tmp_path):
    """A real session row pointing at a throwaway project dir."""
    proj = tmp_path / 'proj'
    proj.mkdir()
    response = client.post('/sessions', json={'workdir': str(proj)})
    assert response.status_code == 200, response.text
    return response.json()['session_id'], proj


def _map_home(tmp_path):
    """The config home `_test_app` injects, so map paths resolve where the app
    looks rather than where `CODEDUDE_HOME` happens to point.

    Keeping the two apart is the point: the routes must use the home they were
    given (`create_app(home=...)`), not re-resolve it from the environment.
    """
    return tmp_path / 'home'


def _build_page(proj, tmp_path, body='<!doctype html><html><body>map sentinel</body></html>'):
    page = floorplan.map_page(proj, _map_home(tmp_path))
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding='utf-8')
    return page


def test_state_reports_absent_with_a_reason_that_names_the_path(tmp_path):
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        state = client.get(f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['built'] is False
    # The reason names the path it actually looked in -- the config home's map
    # dir since decision #107, not the project root it used to name.
    assert str(floorplan.map_page(proj, _map_home(tmp_path))) in state['reason']
    assert state['bytes'] == 0


def test_state_reports_size_and_build_time_once_the_map_exists(tmp_path):
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        page = _build_page(proj, tmp_path)
        state = client.get(f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['built'] is True
    assert state['bytes'] == page.stat().st_size
    assert state['built_at']
    assert state['reason'] == ''
    # Decision #107: the page is reported where it actually is, and building it
    # left nothing behind in the project.
    assert state['path'] == str(page)
    assert not (proj / 'floorplan').exists()


def test_the_page_is_served_as_html_that_must_revalidate(tmp_path):
    """`no-cache`, not `no-store`: a rebuild lands on the next load without a
    hard refresh, and an unchanged page still costs a 304.

    The page is written under `_map_home()` while `CODEDUDE_HOME` points at the
    `home` fixture's different directory, so a 200 here also pins that the
    route uses the home `create_app` was given instead of re-resolving one.
    """
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        _build_page(proj, tmp_path)
        response = client.get(f'/sessions/{session_id}/map', headers=headers)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['cache-control'] == 'no-cache'
    assert 'map sentinel' in response.text


def test_the_page_404s_with_the_reason_when_nothing_is_built(tmp_path):
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        response = client.get(f'/sessions/{session_id}/map', headers=headers)
    assert response.status_code == 404
    assert str(floorplan.map_page(proj, _map_home(tmp_path))) in response.json()['detail']


@pytest.mark.parametrize('route', ['/sessions/not-a-session/map', '/sessions/not-a-session/map/state'])
def test_an_unknown_session_404s_on_both_routes(tmp_path, route):
    client, headers = _app(tmp_path)
    with client:
        response = client.get(route, headers=headers)
    assert response.status_code == 404
    assert response.json()['detail'] == 'no such session'


# --- #379: the trigger ------------------------------------------------------

def _fake_build(monkeypatch, tmp_path, *, ok=True, error='', warnings=()):
    """Stand in for the scan+build pair; the pair has its own tests.

    A success writes the page, because the point of these tests is the seam:
    the route settles, and `/map/state` answers from what actually landed.
    """
    calls = []

    async def fake(workdir, home=None, **kwargs):
        calls.append((workdir, home))
        page = None
        if ok:
            page = _build_page(Path(workdir), tmp_path)
        return floorplan.MapBuild(ok=ok, error=error, warnings=tuple(warnings),
                                 counts={'files': 621, 'edges': 848},
                                 page=page)

    monkeypatch.setattr(floorplan, 'build_map', fake)
    return calls


def test_the_build_route_settles_and_the_state_flips_to_built(tmp_path, monkeypatch):
    calls = _fake_build(monkeypatch, tmp_path)
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        response = client.post(f'/sessions/{session_id}/map/build', headers=headers)
        state = client.get(f'/sessions/{session_id}/map/state', headers=headers).json()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['ok'] is True
    assert body['counts']['files'] == 621
    # The settled state rides along, so the panel does not have to ask twice.
    assert body['state']['built'] is True
    assert state['built'] is True
    assert len(calls) == 1
    # Decision #107: the map dir, never the project.
    assert calls[0][0] == str(proj)


def test_the_build_route_returns_floorplans_own_words_on_failure(tmp_path, monkeypatch):
    """A settled 200 carries the reason. A non-2xx would make the panel render
    an exception string instead of the receipt that says what to fix."""
    _fake_build(monkeypatch, tmp_path, ok=False,
                error='floorplan build failed (exit 1): no node nodes',
                warnings=['node "gates" path "x.py" matches no included file'])
    client, headers = _app(tmp_path)
    with client:
        session_id, _ = _session(client, tmp_path)
        response = client.post(f'/sessions/{session_id}/map/build', headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is False
    assert 'no node nodes' in body['error']
    assert body['warnings'] == ['node "gates" path "x.py" matches no included file']
    assert body['state']['built'] is False


def test_a_second_build_while_one_is_running_is_a_conflict(tmp_path, monkeypatch):
    """Two builds write the same paths, so the second is refused rather than
    queued. The lock is the adapter's, not the route's, so the tool is covered
    by the same rule."""
    client, headers = _app(tmp_path)
    with client:
        session_id, proj = _session(client, tmp_path)
        with floorplan.build_lock(proj, _map_home(tmp_path)):
            response = client.post(f'/sessions/{session_id}/map/build', headers=headers)
    assert response.status_code == 409
    assert 'already running' in response.json()['detail']


def test_an_unknown_session_cannot_be_asked_to_build(tmp_path):
    client, headers = _app(tmp_path)
    with client:
        response = client.post('/sessions/not-a-session/map/build', headers=headers)
    assert response.status_code == 404
    assert response.json()['detail'] == 'no such session'


def test_state_says_why_it_cannot_build_instead_of_no_map_yet(tmp_path, monkeypatch):
    """The panel's empty state must not offer to build what cannot be built,
    and must not report a missing dependency as a missing map — the two need
    different actions from different people."""
    monkeypatch.setattr(floorplan, 'node_binary', lambda: None)
    client, headers = _app(tmp_path)
    with client:
        session_id, _ = _session(client, tmp_path)
        state = client.get(f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['built'] is False
    assert state['available'] is False
    assert state['detail'] == floorplan.NODE_MISSING
    assert floorplan.NODE_MISSING in state['reason']
    assert 'no map has been built' not in state['reason']


def test_state_reports_availability_so_the_panel_can_offer_the_button(tmp_path):
    client, headers = _app(tmp_path)
    with client:
        session_id, _ = _session(client, tmp_path)
        state = client.get(f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['available'] is True
    assert state['detail']
    # Nothing is reported as running when nothing is.
    assert state['running'] is False
    # No build has been attempted, so there is no receipt to render.
    assert state['build'] is None


def _slow_build(monkeypatch, tmp_path, *, ok, error='', warnings=(), delay=0.4):
    """A build that outlasts the route's settle budget, as a big tree would.

    It takes the real lock and writes the real receipt, because those are the
    two things the 202 path depends on: the poll reads the lock for `running`
    and the receipt for the outcome.
    """
    project = tmp_path / 'proj'

    async def fake(workdir, home=None, **kwargs):
        with floorplan.build_lock(workdir, home):
            outcome = floorplan.MapBuild(
                ok=False, error=error, warnings=tuple(warnings))
            await asyncio.sleep(delay)
            if ok:
                outcome = floorplan.MapBuild(
                    ok=True, counts={'files': 621}, page=_build_page(project, tmp_path))
            outcome.write(floorplan.map_dir(workdir, home) / floorplan.RECEIPT_NAME)
            return outcome

    monkeypatch.setattr(floorplan, 'build_map', fake)
    return project


def test_a_build_that_outlasts_the_budget_answers_202_and_the_panel_polls(
    tmp_path, monkeypatch,
):
    """The request must not be held open for a tree big enough to take minutes.
    The build carries on, and `/map/state` — the surface the panel already has —
    reports it finished."""
    monkeypatch.setattr('codingdude.server.MAP_SETTLE_BUDGET_S', 0.01)
    _slow_build(monkeypatch, tmp_path, ok=True)
    client, headers = _app(tmp_path)
    with client:
        session_id, _ = _session(client, tmp_path)
        response = client.post(f'/sessions/{session_id}/map/build', headers=headers)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body['started'] is True
        assert body['state']['running'] is True
        # The panel polls while the lock is held; the build finishes on its own.
        deadline = time.time() + 10
        state = body['state']
        while time.time() < deadline and not state['built']:
            time.sleep(0.1)
            state = client.get(
                f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['built'] is True
    assert state['running'] is False


def test_a_failure_that_finished_after_the_202_is_still_explained(
    tmp_path, monkeypatch,
):
    """Without the receipt on disk the poll could only say "not built" — the one
    thing the reader already knew. The reason has to survive the request."""
    monkeypatch.setattr('codingdude.server.MAP_SETTLE_BUDGET_S', 0.01)
    _slow_build(monkeypatch, tmp_path, ok=False,
                error='floorplan build failed (exit 1): no node nodes',
                warnings=['node "gates" path "src/x.py" matches no included file'])
    client, headers = _app(tmp_path)
    with client:
        session_id, _ = _session(client, tmp_path)
        response = client.post(f'/sessions/{session_id}/map/build', headers=headers)
        assert response.status_code == 202, response.text
        deadline = time.time() + 10
        state = response.json()['state']
        while time.time() < deadline and state['build'] is None:
            time.sleep(0.1)
            state = client.get(
                f'/sessions/{session_id}/map/state', headers=headers).json()
    assert state['built'] is False
    assert 'no node nodes' in state['build']['error']
    assert state['build']['warnings'] == [
        'node "gates" path "src/x.py" matches no included file']

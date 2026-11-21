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

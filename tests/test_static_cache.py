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
"""#363: the served bundle states its cache policy instead of leaving the
browser to guess.

The failure this pins: with no `Cache-Control`, `index.html` gets heuristic
caching. It is the only file that names the hashed assets, so a pinned copy
keeps requesting asset filenames that no longer exist after a rebuild — the
footer reads `ui <old sha>` while `/health` reports the new one, and nothing
short of clearing site data resolves it. Hashed assets and the entry point
therefore need opposite rules, and both are asserted here.
"""
import pytest

from codingdude import server


def _built_site(tmp_path, monkeypatch):
    """A throwaway dist holding the two kinds of file the policy separates.

    The mount is pointed at it through `_frontend_dist`, so the test never
    depends on a real `npm run build` having happened in this checkout.
    """
    from test_lane import _test_app

    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text(
        '<!doctype html><script src="/assets/app-abc123.js"></script>',
        encoding='utf-8',
    )
    (dist / 'assets' / 'app-abc123.js').write_text('console.log(1)', encoding='utf-8')
    monkeypatch.setattr(server, '_frontend_dist', lambda: dist)
    return _test_app(tmp_path)


def test_the_entry_point_must_revalidate(tmp_path, monkeypatch):
    c, h = _built_site(tmp_path, monkeypatch)
    with c:
        response = c.get('/', headers=h)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-cache'


def test_hashed_assets_are_immutable(tmp_path, monkeypatch):
    """A content-hashed name is a cache key: the bytes behind it never change,
    so re-asking is pure waste."""
    c, h = _built_site(tmp_path, monkeypatch)
    with c:
        response = c.get('/assets/app-abc123.js', headers=h)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'


def test_a_revalidated_entry_point_reports_304_with_the_policy_intact(tmp_path, monkeypatch):
    """`no-cache` must stay cheap: the second load is a 304, and the policy
    header has to survive onto it or the browser re-learns it every time."""
    c, h = _built_site(tmp_path, monkeypatch)
    with c:
        first = c.get('/', headers=h)
        etag = first.headers.get('etag')
        assert etag, 'the static response must be revalidatable'
        second = c.get('/', headers={**h, 'If-None-Match': etag})
    assert second.status_code == 304
    assert second.headers['Cache-Control'] == 'no-cache'


@pytest.mark.parametrize(('path', 'expected'), [
    # Starlette hands get_response an OS path (os.path.normpath), so the
    # separator normalisation is load-bearing on Windows, not decoration.
    ('assets/index-abc123.js', server._IMMUTABLE_ASSETS),
    ('assets\\index-abc123.js', server._IMMUTABLE_ASSETS),
    ('index.html', server._REVALIDATE),
    ('.', server._REVALIDATE),  # the root URL, normalised by Starlette
    ('assets', server._REVALIDATE),  # a directory, not a file under assets/
    ('favicon.svg', server._REVALIDATE),
])
def test_the_policy_separates_hashed_assets_from_everything_else(path, expected):
    assert server.cache_control_for(path) == expected


def test_the_mount_serves_through_the_caching_static_files(tmp_path, monkeypatch):
    """A pin on the wiring: reverting the mount to plain `StaticFiles` leaves
    every header above absent while the policy tests still pass."""
    c, _h = _built_site(tmp_path, monkeypatch)
    mounts = [route for route in c.app.routes if getattr(route, 'name', None) == 'ui']
    assert len(mounts) == 1
    assert isinstance(mounts[0].app, server._CachedStaticFiles)

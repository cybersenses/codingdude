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
"""SEC #250 auth-seam tests. Lives in its own file because test_server.py's
line endings are inconsistent (the R66 repair left them mixed), so editing
that file risks EOL churn — see code-design.md #250."""

from pathlib import Path

import httpx
from test_server import server  # noqa: F401 — pytest fixture


def test_non_ascii_credentials_fail_closed_not_500(server):  # noqa: F811 — pytest fixture param shadows the import
    """SEC #250: non-ASCII candidates must fail closed (401), never 500 —
    _ct_eq compares UTF-8 bytes, so non-ASCII simply mismatches (no
    TypeError to dodge). (Header values can't carry non-ASCII at all —
    httpx/h11 reject them client-side — so the reachable seams are the
    query param and the login body.) The candidates are built at runtime
    so no literal looks like a secret."""
    app, base = server
    umlaut_o = chr(246)
    non_ascii_query = f'workdir=/&token=caf{umlaut_o}'
    non_ascii_password = f'p{chr(228)}ssw{umlaut_o}rd'
    r = httpx.get(f'{base}/sessions?{non_ascii_query}', timeout=5)
    assert r.status_code == 401
    r2 = httpx.post(f'{base}/login', json={'password': non_ascii_password}, timeout=5)
    assert r2.status_code == 401


def test_auth_seams_use_constant_time_compare():
    """SEC #250 tripwire (source-parse, R64/R65 precedent): every token
    compare routes through _ct_eq/secrets.compare_digest. Round 1 found
    the bug shape "2 of 3 transports migrated", so counts are pinned, not
    just membership; negatives catch both operand orders (`== token` and
    `token ==`) so a plain compare can't sneak back in reversed."""
    src = Path(__file__).parent.parent / 'src' / 'codingdude' / 'server.py'
    text = src.read_text(encoding='utf-8')

    def segment(start: str, end: str) -> str:
        return text[text.index(start):text.index(end)]

    # The one constant-time primitive lives in _ct_eq and nowhere else.
    helper = segment('def _ct_eq', 'def _authed')
    assert helper.count('compare_digest') == 1

    # The shared transport check: exactly one _ct_eq per transport (Bearer,
    # cookie, query). 2-of-3 here was the round-1 bug shape.
    authed = segment('def _authed', 'def authorize')
    assert authed.count('_ct_eq(') == 3

    # authorize and run_events delegate to _authed and keep no private
    # token compare (the round-1 duplication finding).
    for start, end in [
        ('def authorize', 'def _session_cookie'),
        ('async def run_events', '@app.websocket'),
    ]:
        seg = segment(start, end)
        assert '_authed(request)' in seg
        assert '_ct_eq(' not in seg

    # The single-compare seams: exactly one _ct_eq each.
    for start, end in [
        ('def auth_check', 'def auth_local'),
        ('def login', 'class SessionIn'),
        ('async def run_ws', 'await ws.accept()'),
    ]:
        assert segment(start, end).count('_ct_eq(') == 1

    # No plain token compare anywhere in the auth region, either order.
    auth_region = segment('def _ct_eq', "app.get('/models')")
    for bad in ('== token', '!= token', 'token ==', 'token !='):
        assert bad not in auth_region, bad

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
"""SEC #250 auth-seam tests. Lives in its own file because test_server.py
has mixed line endings and the edit tool normalizes it — see the R66
repair commit."""

from pathlib import Path

import httpx
from test_server import server  # noqa: F401 — pytest fixture


def test_non_ascii_credentials_fail_closed_not_500(server):  # noqa: F811 — pytest fixture param shadows the import
    """SEC #250: compare_digest only accepts ASCII strings — every auth seam
    must fail closed (401), never blow up, on non-ASCII candidates. (Header
    values can't carry non-ASCII at all — httpx/h11 reject them client-side —
    so the reachable seams are the query param and the login body.) The
    candidates are built at runtime so no literal looks like a secret."""
    app, base = server
    umlaut_o = chr(246)
    non_ascii_query = f'workdir=/&token=caf{umlaut_o}'
    non_ascii_password = f'p{chr(228)}ssw{umlaut_o}rd'
    r = httpx.get(f'{base}/sessions?{non_ascii_query}', timeout=5)
    assert r.status_code == 401
    r2 = httpx.post(f'{base}/login', json={'password': non_ascii_password}, timeout=5)
    assert r2.status_code == 401


def test_auth_seams_use_constant_time_compare():
    """SEC #250 tripwire (source-parse, R64/R65 precedent): token compares in
    authorize/auth_check/login AND the two inline-auth endpoints (run_events,
    run_ws) must go through _ct_eq/secrets.compare_digest — a plain ==/!=
    would reintroduce the timing side channel silently (review round 1 found
    exactly that on the two inline seams)."""
    src = Path(__file__).parent.parent / 'src' / 'codingdude' / 'server.py'
    text = src.read_text(encoding='utf-8')
    helper = text[text.index('def _ct_eq'):text.index('def authorize')]
    assert 'compare_digest' in helper  # the one constant-time primitive
    authorize = text[text.index('def authorize'):text.index('def _session_cookie')]
    assert '_ct_eq' in authorize
    assert '!= token' not in authorize and '== token' not in authorize
    auth_check = text[text.index('def auth_check'):text.index('def auth_local')]
    assert '_ct_eq' in auth_check
    assert '== token' not in auth_check
    login = text[text.index('def login'):text.index('class SessionIn')]
    assert '_ct_eq' in login
    assert '!= token' not in login
    run_events = text[text.index('def run_events'):text.index('@app.websocket')]
    assert '_ct_eq' in run_events
    assert '== token' not in run_events
    run_ws = text[text.index('async def run_ws'):text.index('await ws.accept()')]
    assert '_ct_eq' in run_ws
    assert '!= token' not in run_ws

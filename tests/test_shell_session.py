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
"""R28 Phase 3: persistent interactive shell sessions.

A session is a long-lived shell process the agent can write stdin to and
read fresh output from across multiple tool calls. Output also streams to
trace as PROCESS_OUTPUT events so HITL sees session progress live.
"""
import sys
import time

from codingdude.processes import ProcessRegistry

ECHO_SCRIPT = (
    "import sys\nfor line in sys.stdin:\n"
    "    print('got:' + line.strip(), flush=True)\n"
)
ECHO_ARGV = [sys.executable, '-u', '-c', ECHO_SCRIPT]


def test_session_starts_and_polls_running():
    reg = ProcessRegistry()
    session = reg.start_session(ECHO_ARGV, cwd='.')
    try:
        record = reg.poll(session.pid)
        assert record is not None
        assert record['status'] == 'running'
        assert record['command'] == str(ECHO_ARGV)
    finally:
        session.terminate()


def test_session_via_shell_string_starts_and_polls():
    reg = ProcessRegistry()
    session = reg.start_session('cat', cwd='.')
    try:
        record = reg.poll(session.pid)
        assert record is not None
        assert record['status'] == 'running'
        assert record['command'] == 'cat'
    finally:
        session.terminate()


def test_write_then_read_returns_response():
    reg = ProcessRegistry()
    session = reg.start_session(ECHO_ARGV, cwd='.')
    try:
        session.write('hello\n')
        deadline = time.time() + 5
        out = ''
        while 'got:hello' not in out and time.time() < deadline:
            out += session.read_new()
            time.sleep(0.05)
        assert 'got:hello' in out
    finally:
        session.terminate()


def test_read_new_only_returns_output_since_last_read():
    reg = ProcessRegistry()
    session = reg.start_session(ECHO_ARGV, cwd='.')
    try:
        session.write('one\n')
        deadline = time.time() + 5
        while 'got:one' not in (out1 := session.read_new()) and time.time() < deadline:
            time.sleep(0.05)
        assert 'got:one' in out1
        session.write('two\n')
        out2 = ''
        deadline = time.time() + 5
        while 'got:two' not in out2 and time.time() < deadline:
            out2 += session.read_new()
            time.sleep(0.05)
        assert 'got:two' in out2
        assert 'got:one' not in out2  # already consumed
    finally:
        session.terminate()


def test_session_output_streams_as_process_output_events():
    events: list[dict] = []
    reg = ProcessRegistry(on_event=events.append)
    session = reg.start_session(ECHO_ARGV, cwd='.')
    try:
        session.write('stream\n')
        deadline = time.time() + 5
        while not any(
            e.get('type') == 'PROCESS_OUTPUT' and 'got:stream' in e.get('data', '')
            for e in events
        ) and time.time() < deadline:
            session.read_new()
            time.sleep(0.05)
        outputs = [e for e in events if e.get('type') == 'PROCESS_OUTPUT']
        assert any('got:stream' in e['data'] for e in outputs)
        assert all(e.get('pid') == session.pid for e in outputs)
    finally:
        session.terminate()


def test_terminate_marks_exited_in_registry():
    reg = ProcessRegistry()
    session = reg.start_session('cat', cwd='.')
    pid = session.pid
    session.terminate()
    deadline = time.time() + 5
    while reg.poll(pid)['status'] == 'running' and time.time() < deadline:
        time.sleep(0.05)
    assert reg.poll(pid)['status'] != 'running'


def test_write_to_non_session_pid_is_refused():
    reg = ProcessRegistry()
    session = reg.start_session('cat', cwd='.')
    try:
        assert 'not' in reg.write(999999, 'x').lower()
    finally:
        session.terminate()

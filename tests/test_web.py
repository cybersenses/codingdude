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
"""Engine seam: web search and fetch tools attached to the agent."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


class StubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<html><body><h1> Docs </h1><p>magic word: ZEBRA-QUARTZ</p></body></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def test_web_tools_registered_by_default(engine, workdir):
    def list_tools(messages, info):
        names = sorted(t.name for t in info.model_request_parameters.function_tools or [])
        return ModelResponse(parts=[TextPart(content='ALL:' + ','.join(names))])

    outcome = await engine.run(
        prompt='list tools', workdir=workdir, model=scripted(list_tools)
    )
    assert 'web_search' in outcome.output
    assert 'web_fetch' in outcome.output


async def test_web_fetch_quotes_page(engine, workdir):
    server = HTTPServer(('127.0.0.1', 0), StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]

        def fetch_then_answer(url: str):
            def fn(messages: list[ModelMessage], info):
                if not any(
                    isinstance(p, ToolCallPart) for m in messages for p in m.parts
                ):
                    return ModelResponse(
                        parts=[ToolCallPart(tool_name='web_fetch', args={'url': url})]
                    )
                returns = [
                    str(p.content)
                    for m in messages
                    for p in m.parts
                    if isinstance(p, ToolReturnPart)
                ]
                found = any('ZEBRA-QUARTZ' in r for r in returns)
                return ModelResponse(parts=[TextPart(content='quoted' if found else 'missing')])

            return scripted(fn)

        outcome = await engine.run(
            prompt='read the docs',
            workdir=workdir,
            model=fetch_then_answer(f'http://127.0.0.1:{port}/docs'),
        )
        assert outcome.output == 'quoted'
    finally:
        server.shutdown()

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
"""Living-artifact collaboration channel (R6).

The agent emits structured artifacts — choice cards and editable spec
blocks — the user interacts with in the session UI, and the answers flow
back into the conversation via `get_artifact_feedback`. Mermaid stays
render-only: fences are shown as code blocks, not executed.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, Iterator

from pydantic_ai.toolsets import FunctionToolset

from .db import utc_now_iso as _now


def _check_optional_strings(
    obj: dict, fields: tuple[str, ...], where: str, errors: list[str]
) -> None:
    """Optional fields must be strings when present; absent is fine (tolerant)."""
    for field in fields:
        if field in obj and not isinstance(obj[field], str):
            errors.append(f'{where}.{field} must be a string when present')


def _validate_wireframe_region(
    region: object, where: str, areas: set[str], names: set[str], errors: list[str]
) -> None:
    """A region must name a unique template area; widget/label/notes are strings
    when present. Unknown widget values pass (tolerant content, R85)."""
    if not isinstance(region, dict):
        errors.append(f'{where} must be an object')
        return
    name = region.get('name')
    if not isinstance(name, str) or not name:
        errors.append(f'{where}.name must be a non-empty string')
    elif name in names:
        errors.append(f'{where}.name {name!r} is duplicated')
    elif name not in areas:
        errors.append(f'{where}.name {name!r} is not an area in template')
    else:
        names.add(name)
    _check_optional_strings(region, ('widget', 'label', 'notes'), where, errors)


def _validate_wireframe_screen(
    screen: object, index: int, ids: set[str], errors: list[str]
) -> None:
    """One screen: unique id, string title, grid template, regions tied to areas."""
    where = f'screens[{index}]'
    if not isinstance(screen, dict):
        errors.append(f'{where} must be an object')
        return
    screen_id = screen.get('id')
    if not isinstance(screen_id, str) or not screen_id:
        errors.append(f'{where}.id must be a non-empty string')
    elif screen_id in ids:
        errors.append(f'{where}.id {screen_id!r} is duplicated')
    else:
        ids.add(screen_id)
    if not isinstance(screen.get('title'), str):
        errors.append(f'{where}.title must be a string')
    template = screen.get('template')
    if not isinstance(template, str) or not template.strip():
        errors.append(f'{where}.template must be a non-empty string')
        template = ''
    # grid-template-areas tokens; quoted rows and '.' filler cells are allowed.
    areas = set(template.replace('"', ' ').split()) - {'.'}
    regions = screen.get('regions')
    if not isinstance(regions, list) or not regions:
        errors.append(f'{where}.regions must be a non-empty list')
        return
    names: set[str] = set()
    for j, region in enumerate(regions):
        _validate_wireframe_region(region, f'{where}.regions[{j}]', areas, names, errors)


def _validate_wireframe_flow(
    flow: object, index: int, ids: set[str], errors: list[str]
) -> None:
    """A flow edge references known screen ids; trigger/label are optional strings."""
    where = f'flows[{index}]'
    if not isinstance(flow, dict):
        errors.append(f'{where} must be an object')
        return
    for field in ('from', 'to'):
        ref = flow.get(field)
        if not isinstance(ref, str) or not ref:
            errors.append(f'{where}.{field} must be a non-empty string')
        elif ref not in ids:
            errors.append(f'{where}.{field} {ref!r} is not a known screen id')
    _check_optional_strings(flow, ('trigger', 'label'), where, errors)


def _validate_wireframe(payload: dict) -> None:
    """R85 DSL v1: strict structure, tolerant content. Unknown widgets and extra
    fields pass through (the renderer degrades them to generic boxes); every
    structural violation is batched into ONE readable ValueError so the agent
    can self-correct in a single turn."""
    if not isinstance(payload, dict):
        raise ValueError('invalid wireframe payload: payload must be a JSON object')
    errors: list[str] = []
    version = payload.get('version')
    if isinstance(version, bool) or version != 1:  # True == 1 in Python; not a version
        errors.append('version must be 1')
    screens = payload.get('screens')
    if not isinstance(screens, list) or not screens:
        errors.append('screens must be a non-empty list')
        screens = []
    ids: set[str] = set()
    for i, screen in enumerate(screens):
        _validate_wireframe_screen(screen, i, ids, errors)
    flows = payload.get('flows', [])
    if not isinstance(flows, list):
        errors.append('flows must be a list when present')
    else:
        for i, flow in enumerate(flows):
            _validate_wireframe_flow(flow, i, ids, errors)
    if errors:
        raise ValueError('invalid wireframe payload: ' + '; '.join(errors))


# Per-kind payload validation at the _emit chokepoint, keyed by kind so future
# kinds slot in without touching _emit again.
_EMIT_VALIDATORS: dict[str, Callable[[dict], None]] = {
    'wireframe': _validate_wireframe,
}


class ArtifactStore:
    """SQLite-backed store of tool artifacts (request/response pairs) per session."""
    def __init__(self, db, session_id: str):
        self._db = db
        self._session_id = session_id

    def emit_choice_card(
        self, question: str, options: list[str], description: str = ''
    ) -> str:
        if not options:
            raise ValueError('a choice card needs at least one option')
        return self._emit('choice', question, {
            'question': question,
            'options': list(options),
            'description': description,
        })

    def emit_spec_block(self, name: str, markdown: str) -> str:
        return self._emit('spec', name, {'markdown': markdown})

    def emit_html(self, name: str, html: str) -> str:
        """Publish an HTML artifact the UI renders inline (sandboxed iframe)."""
        return self._emit('html', name, {'html': html})

    def emit_wireframe(self, payload: dict, title: str) -> str:
        """Publish a wireframe pack (screens + flows) rendered in the Artifacts tab."""
        return self._emit('wireframe', title, payload)

    def record_qa(self, questions: list, answers) -> str:
        """Auto-capture an answered ask_user round as decision history."""
        return self._emit(
            'qa',
            'Question answered',
            {'questions': questions, 'answers': answers},
            status='answered',
            response=answers,
        )

    def record_decision(self, title: str, body: str = '') -> str:
        """Auto-capture a recorded design decision as decision history."""
        return self._emit(
            'decision', title, {'title': title, 'body': body}, status='answered',
            response={'title': title, 'body': body},
        )


    def _emit(
        self,
        kind: str,
        title: str,
        payload: dict,
        status: str = 'pending',
        response: dict | None = None,
    ) -> str:
        validator = _EMIT_VALIDATORS.get(kind)
        if validator is not None:
            validator(payload)
        artifact_id = secrets.token_urlsafe(8)
        self._db._conn.execute(
            'INSERT INTO artifacts'
            ' (id, session_id, kind, title, payload_json, status, response_json, created_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                artifact_id, self._session_id, kind, title,
                json.dumps(payload), status,
                json.dumps(response) if response is not None else None, _now(),
            ),
        )
        self._db._conn.commit()
        return artifact_id

    def respond(self, artifact_id: str, response: dict) -> None:
        artifact = self._get(artifact_id)
        if artifact['status'] == 'dismissed':
            raise ValueError(
                f'artifact {artifact_id!r} was dismissed — its run is gone, so an'
                ' answer would reach nobody'
            )
        payload = json.loads(artifact['payload_json'])
        if artifact['kind'] == 'choice':
            pick = response.get('pick')
            if pick not in payload['options']:
                raise ValueError(
                    f'pick {pick!r} is not one of the options: {payload["options"]}'
                )
        else:  # spec
            if not isinstance(response.get('content'), str):
                raise ValueError('a spec block response needs {"content": "<markdown>"}')
        self._db._conn.execute(
            'UPDATE artifacts SET status = ?, response_json = ? WHERE id = ?',
            ('answered', json.dumps(response), artifact_id),
        )
        self._db._conn.commit()

    def dismiss(self, artifact_id: str) -> None:
        """Retire a card nobody can answer any more (R58).

        `dismissed` is a terminal state distinct from `answered`: no answer
        was recorded, so `feedback` still reports nothing to the agent's
        replacement — but the card stops rendering as pending forever.
        """
        artifact = self._get(artifact_id)
        if artifact['status'] != 'pending':
            raise ValueError(
                f'artifact {artifact_id!r} is {artifact["status"]}, not pending'
            )
        self._db._conn.execute(
            "UPDATE artifacts SET status = 'dismissed' WHERE id = ?", (artifact_id,)
        )
        self._db._conn.commit()

    def list(self) -> list[dict]:
        rows = self._db._conn.execute(
            'SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at DESC',
            (self._session_id,),
        ).fetchall()
        return [self._as_dict(r) for r in rows]

    def feedback(self, artifact_id: str) -> dict | None:
        artifact = self._get(artifact_id)
        if artifact['status'] != 'answered':
            return None
        return json.loads(artifact['response_json'])

    def watch(self, poll_seconds: float = 1.0) -> Iterator[dict]:
        """Tail the artifacts table (R6 SSE push): an initial snapshot event,
        then an 'emitted' or 'answered' delta per change. Sync generator —
        Starlette iterates it in a threadpool for the streaming endpoint."""
        seen: dict[str, str] = {}
        first = True
        while True:
            current = {a['id']: a['status'] for a in self.list()}
            if first:
                yield {'event': 'snapshot', 'artifacts': self.list()}
                first = False
            else:
                for artifact_id, status in current.items():
                    previous = seen.get(artifact_id)
                    if previous is None:
                        yield {'event': 'emitted', 'artifact': self._get_mapped(artifact_id)}
                    elif previous != status:
                        yield {'event': 'answered', 'artifact': self._get_mapped(artifact_id)}
            seen = current
            time.sleep(poll_seconds)

    def _get(self, artifact_id: str) -> dict:
        row = self._db._conn.execute(
            'SELECT * FROM artifacts WHERE id = ?', (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'no artifact with id {artifact_id!r}')
        return dict(row)

    def _get_mapped(self, artifact_id: str) -> dict:
        """_get() shaped like list() rows: payload deserialized, payload_json gone.

        SSE deltas feed the Artifacts panel verbatim — an unmapped raw row
        makes kind-specific rendering read a.payload.* of undefined and
        crashes the React tree.
        """
        return self._as_dict(self._get(artifact_id))

    @staticmethod
    def _as_dict(row) -> dict:
        artifact = dict(row)
        artifact['payload'] = json.loads(artifact.pop('payload_json'))
        response = artifact.pop('response_json')
        artifact['response'] = json.loads(response) if response else None
        return artifact


def build_artifacts_toolset(db, session_id: str) -> FunctionToolset:
    """Agent tools to emit artifacts and read back the user's answers."""
    store = ArtifactStore(db, session_id)

    def emit_choice_card(question: str, options: list[str], description: str = '') -> str:
        """Offer the user a pick-one decision as an interactive card in the UI."""
        artifact_id = store.emit_choice_card(question, options, description)
        return (
            f'choice card emitted (id={artifact_id}). The user answers in the UI; '
            'poll get_artifact_feedback to read the pick.'
        )

    def emit_spec_block(name: str, markdown: str) -> str:
        """Publish an editable spec block the user can revise inline in the UI."""
        artifact_id = store.emit_spec_block(name, markdown)
        return (
            f'spec block emitted (id={artifact_id}). Poll get_artifact_feedback '
            'to read the user\'s edits.'
        )

    def emit_html(name: str, html: str) -> str:
        """Publish an HTML page the user sees rendered inline in the Artifacts tab."""
        artifact_id = store.emit_html(name, html)
        return f'html artifact emitted (id={artifact_id}); it renders inline in the UI.'

    def emit_wireframe(payload: dict, title: str) -> str:
        """Publish a wireframe pack (screens + flows) stored for the Artifacts tab.

        payload shape (DSL v1):
        {"version": 1, "screens": [...], "flows": [...]}
        Each screen: {"id": str, "title": str, "template": "<grid-template-areas>",
          "regions": [{"name": str (a template area), "widget": str,
                       "label": str, "notes": str}]}.
        Widget vocabulary v1: nav, header, form, table, list, text, chart,
        actions, tabs, image, code, placeholder — unknown values are fine, they
        render as a generic labeled box.
        flows: [{"from": screen id, "to": screen id, "trigger": str, "label": str}].
        Structural violations (version != 1, duplicated ids, a region naming an
        area that is not in the template, unknown screen references) come back
        as ONE message listing every problem — fix all of them and re-emit the
        whole pack.
        """
        artifact_id = store.emit_wireframe(payload, title)
        return (
            f'wireframe pack emitted (id={artifact_id}); stored for the '
            'Artifacts tab renderer.'
        )

    def get_artifact_feedback(artifact_id: str) -> str:
        """Read the user's answer for an artifact (pick or edited content)."""
        feedback = store.feedback(artifact_id)
        if feedback is None:
            return 'pending — user has not answered yet'
        return json.dumps(feedback)

    return FunctionToolset([
        emit_choice_card, emit_spec_block, emit_html, emit_wireframe,
        get_artifact_feedback,
    ])

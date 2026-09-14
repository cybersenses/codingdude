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
from collections.abc import Iterator
from datetime import UTC, datetime

from pydantic_ai.toolsets import FunctionToolset


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ArtifactStore:
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
                        yield {'event': 'emitted', 'artifact': self._get(artifact_id)}
                    elif previous != status:
                        yield {'event': 'answered', 'artifact': self._get(artifact_id)}
            seen = current
            time.sleep(poll_seconds)

    def _get(self, artifact_id: str) -> dict:
        row = self._db._conn.execute(
            'SELECT * FROM artifacts WHERE id = ?', (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'no artifact with id {artifact_id!r}')
        return dict(row)

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

    def get_artifact_feedback(artifact_id: str) -> str:
        """Read the user's answer for an artifact (pick or edited content)."""
        feedback = store.feedback(artifact_id)
        if feedback is None:
            return 'pending — user has not answered yet'
        return json.dumps(feedback)

    return FunctionToolset([emit_choice_card, emit_spec_block, emit_html, get_artifact_feedback])

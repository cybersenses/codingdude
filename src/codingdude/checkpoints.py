"""Checkpoints: automatic snapshots of files before the agent modifies them.

Storage: plain file copies under
`~/.codingdude/checkpoints/<session_id>/<checkpoint_id>/<rel_path>`, with a
`metadata.json` per checkpoint. Works in every workdir — git repo or not.

Retention: capped per session (default 50) and by age (default 30 days),
both configurable via `[checkpoints]` in config.toml. Pruning happens on
capture.
"""

import json
import shutil
import time
import uuid
from pathlib import Path

CHECKPOINTS_DIRNAME = 'checkpoints'
DEFAULT_MAX_PER_SESSION = 50
DEFAULT_MAX_AGE_DAYS = 30


def _now() -> float:
    return time.time()


class CheckpointStore:
    """File-backed snapshot store enabling rollback of workdir state."""
    def __init__(self, home: Path, max_per_session: int = DEFAULT_MAX_PER_SESSION,
                 max_age_days: int = DEFAULT_MAX_AGE_DAYS):
        self.home = home
        self.max_per_session = max_per_session
        self.max_age_days = max_age_days

    def _session_dir(self, session_id: str) -> Path:
        return self.home / CHECKPOINTS_DIRNAME / session_id

    def begin(self, session_id: str) -> str:
        """Start a new checkpoint container (files captured lazily into it)."""
        self._prune(session_id)
        cp_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        cp_dir = self._session_dir(session_id) / cp_id
        cp_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            'id': cp_id,
            'session_id': session_id,
            'created_at': _now(),
            'files': {},
        }
        (cp_dir / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')
        return cp_id


    @staticmethod
    def _read_meta(meta_path: Path) -> 'dict | None':
        """Parse a checkpoint's metadata; None when missing or corrupt.

        A corrupt file (torn write from a killed worker) is reported as
        absent rather than crashing the run with a JSONDecodeError.
        """
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return None
        return meta if isinstance(meta, dict) and 'files' in meta else None

    def _ordered_ids(self, session_dir: Path) -> list[str]:
        """Checkpoint ids oldest-first by created_at.

        Name order is not reliably chronological: two checkpoints created in the
        same second share the timestamp *prefix* and then sort on a random uuid.
        """
        if not session_dir.exists():
            return []
        entries = []
        for cp_dir in session_dir.iterdir():
            if not cp_dir.is_dir():
                continue
            meta = self._read_meta(cp_dir / 'metadata.json')
            entries.append((meta.get('created_at', 0) if meta else 0, cp_dir.name))
        entries.sort()
        return [name for _created, name in entries]

    def capture_file(self, session_id: str, cp_id: str, workdir: Path, abs_path: Path) -> None:
        """Snapshot one file into the checkpoint (first touch per file)."""
        cp_dir = self._session_dir(session_id) / cp_id
        meta = self._read_meta(cp_dir / 'metadata.json')
        if meta is None:
            return
        try:
            rel = str(abs_path.relative_to(workdir.resolve())).replace('\\', '/')
        except ValueError:
            return
        if rel in meta['files']:
            return  # already captured in this checkpoint
        if not abs_path.exists():
            meta['files'][rel] = {'existed': False}
        else:
            dest = cp_dir / 'files' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, dest)
            meta['files'][rel] = {'existed': True}
        (cp_dir / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')

    def list_checkpoints(self, session_id: str) -> list[dict]:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []
        out = []
        for cp_dir in sorted(session_dir.iterdir(), key=lambda p: p.name, reverse=True):
            meta = self._read_meta(cp_dir / 'metadata.json')
            if meta is None:
                continue
            out.append({
                'id': meta['id'],
                'created_at': meta['created_at'],
                'files': sorted(meta['files'].keys()),
            })
        return out

    def restore_checkpoint(self, session_id: str, cp_id: str, workdir: Path) -> dict:
        """Restore every file captured in this checkpoint."""
        cp_dir = self._session_dir(session_id) / cp_id
        meta = self._read_meta(cp_dir / 'metadata.json')
        if meta is None:
            raise FileNotFoundError(f'no such (or corrupt) checkpoint: {cp_id}')
        restored = []
        for rel, info in meta['files'].items():
            target = workdir.resolve() / rel
            if info.get('existed'):
                src = cp_dir / 'files' / rel
                if src.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    restored.append(rel)
            else:
                if target.exists():
                    target.unlink()
                    restored.append(rel)
        return {'restored': restored}

    def restore_file(self, session_id: str, cp_id: str, rel_path: str, workdir: Path) -> dict:
        cp_dir = self._session_dir(session_id) / cp_id
        meta = self._read_meta(cp_dir / 'metadata.json')
        if meta is None:
            raise FileNotFoundError(f'no such (or corrupt) checkpoint: {cp_id}')
        info = meta['files'].get(rel_path)
        if not info:
            raise FileNotFoundError(f'{rel_path} not in checkpoint {cp_id}')
        target = workdir.resolve() / rel_path
        if info.get('existed'):
            src = cp_dir / 'files' / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        elif target.exists():
            target.unlink()
        return {'restored': rel_path}

    def rewind_to(self, session_id: str, cp_id: str, workdir: Path) -> dict:
        """Restore this checkpoint AND undo all later checkpoints, storing the
        discarded state as its own checkpoint (undo the undo)."""
        session_dir = self._session_dir(session_id)
        cps = self._ordered_ids(session_dir)
        if cp_id not in cps:
            raise FileNotFoundError(f'no such checkpoint: {cp_id}')
        # capture current state as a safety checkpoint before rewinding
        safety_id = self.begin(session_id)
        later = cps[cps.index(cp_id) + 1:]
        later_files: dict[str, list[str]] = {}
        for later_id in later:
            meta = self._read_meta(session_dir / later_id / 'metadata.json')
            if meta is None:
                continue
            for rel in meta['files']:
                later_files.setdefault(rel, [])
        live_workdir = Path(workdir).resolve()
        for rel in later_files:
            abs_path = live_workdir / rel
            if abs_path.exists():
                self.capture_file(session_id, safety_id, live_workdir, abs_path)
        restored = self.restore_checkpoint(session_id, cp_id, workdir)
        # Drop the now-undone later checkpoints; their state lives on in the
        # safety checkpoint, so the timeline reads "we rewound to here" (L5).
        for later_id in later:
            shutil.rmtree(session_dir / later_id, ignore_errors=True)
        return {'rewound_to': cp_id, 'safety_checkpoint': safety_id, **restored}

    def _prune(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return
        cutoff = _now() - self.max_age_days * 86400
        entries = []
        for cp_dir in session_dir.iterdir():
            meta = self._read_meta(cp_dir / 'metadata.json')
            if meta is None:
                continue
            entries.append((meta.get('created_at', 0), cp_dir))
        entries.sort(key=lambda e: e[0], reverse=True)
        # keep room for the checkpoint about to be created
        for _created, cp_dir in entries[self.max_per_session - 1 :]:
            shutil.rmtree(cp_dir, ignore_errors=True)
        for created, cp_dir in entries:
            if created < cutoff:
                shutil.rmtree(cp_dir, ignore_errors=True)

"""Skills: reusable procedures (SKILL.md files) with progressive disclosure.

Only the index (name + description) enters the context; the body is fetched
on demand via the `load_skill` tool — the same convention as the SKILL.md
ecosystem. Skills are global (one library in ~/.codingdude/skills), never
project-dependent; they may ship companion files (references, templates,
scripts) in their directory, exposed by name so nothing in a skill is
unreachable. Skills may declare `triggers`: phrases that make the engine
pre-load the body into a run automatically, without the model having to ask.
"""

import json
import re
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Split a SKILL.md into (meta, body).

    Two styles are supported: a JSON object before the first blank line
    (the original format), and `---`-delimited `key: value` lines (the
    common SKILL.md convention). Unknown formats fall back to "no meta".
    """
    if raw.startswith('---\n'):
        end = raw.find('\n---', 3)
        if end != -1:
            meta: dict = {}
            for line in raw[4:end].splitlines():
                if ':' not in line:
                    continue
                key, _, value = line.partition(':')
                value = value.strip()
                if value.startswith('[') and value.endswith(']'):
                    meta[key.strip()] = [
                        t.strip().strip('\"\'') for t in value[1:-1].split(',') if t.strip()
                    ]
                else:
                    meta[key.strip()] = value.strip('\"\'')
            return meta, raw[end + 4:].lstrip('\n')
    body_start = raw.find('\n\n')
    meta = json.loads(raw[:body_start]) if body_start != -1 else {}
    body = raw[body_start + 2:] if body_start != -1 else raw
    return meta, body


class SkillRegistry:
    """Discovers and loads SKILL.md files from the configured skill roots."""
    def __init__(self, home: Path):
        self.home = home

    def _dir(self) -> Path:
        return self.home / 'skills'

    def _scan(self) -> dict[str, dict]:
        """All installed skills (global library, project-independent)."""
        found: dict[str, dict] = {}
        for skill_md in sorted(self._dir().glob('*/SKILL.md')):
            try:
                raw = skill_md.read_text(encoding='utf-8').replace('\r\n', '\n')
                meta, body = _parse_frontmatter(raw)
                found[meta.get('name', skill_md.parent.name)] = {
                    'name': meta.get('name', skill_md.parent.name),
                    'description': meta.get('description', ''),
                    'body': body.strip(),
                    'path': skill_md.parent,
                    'triggers': [
                        str(t).lower() for t in meta.get('triggers', []) if t
                    ],
                }
            except (json.JSONDecodeError, OSError):
                continue
        return found

    @staticmethod
    def _companions(skill_dir: Path) -> list[str]:
        if not skill_dir.exists():
            return []
        return sorted(
            p.name for p in skill_dir.iterdir()
            if p.is_file() and p.name != 'SKILL.md'
        )

    def index(self) -> list[dict]:
        return [
            {'name': s['name'], 'description': s['description']}
            for s in self._scan().values()
        ]

    def companions(self, name: str) -> list[str]:
        skill = self._scan().get(name)
        return self._companions(skill['path']) if skill else []

    def directory(self, name: str) -> str | None:
        """Absolute path of the skill's directory (siblings live beside it)."""
        skill = self._scan().get(name)
        return str(skill['path']) if skill else None

    def load(self, name: str, file: str | None = None) -> str | None:
        """The skill body, or a companion file's text (path contained to the skill dir)."""
        skill = self._scan().get(name)
        if skill is None:
            return None
        if not file:
            return skill['body']
        base = Path(skill['path']).resolve()
        target = (base / file).resolve()
        if base != target and base not in target.parents:
            return None
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding='utf-8')
        except OSError:
            return None

    def detail(self) -> list[dict]:
        return [
            {
                'name': s['name'],
                'description': s['description'],
                'body': s['body'],
                'triggers': s['triggers'],
                'companions': self._companions(s['path']),
            }
            for s in self._scan().values()
        ]

    @staticmethod
    def _trigger_hit(trig: str, text: str) -> bool:
        """Exact phrase, or all trigger words present in any order."""
        if re.search(r'(?<!\w)' + re.escape(trig) + r'(?!\w)', text):
            return True
        words = trig.split()
        if len(words) > 1:
            return all(
                re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', text) for w in words
            )
        return False

    def matching(self, prompt: str, limit: int = 3, max_bytes: int = 24_000) -> list[dict]:
        """Skills whose trigger phrases appear in the prompt, best match first.

        Matching is word-boundary and case-insensitive, so 'adr' hits
        "record an ADR" but not "address". Caps keep auto-loading cheap.
        """
        text = prompt.lower()
        hits: list[tuple[int, str, dict]] = []
        for s in self._scan().values():
            score = 0
            for trig in s['triggers']:
                if self._trigger_hit(trig, text):
                    score += len(trig)
            if score:
                hits.append((score, s['name'], s))
        hits.sort(key=lambda t: (-t[0], t[1]))
        picked: list[dict] = []
        total = 0
        for _score, _name, s in hits:
            if len(picked) >= limit or total + len(s['body']) > max_bytes:
                break
            picked.append(s)
            total += len(s['body'])
        return picked

    def save(self, name: str, description: str, body: str) -> str:
        """Create/update a skill in the global skills directory."""
        directory = self.home / 'skills' / name
        directory.mkdir(parents=True, exist_ok=True)
        meta = json.dumps({'name': name, 'description': description})
        (directory / 'SKILL.md').write_text(f'{meta}\n\n{body.strip()}\n', encoding='utf-8')
        return str(directory / 'SKILL.md')

    def delete(self, name: str) -> bool:
        import shutil

        directory = self.home / 'skills' / name
        if directory.exists():
            shutil.rmtree(directory)
            return True
        return False


def build_skills_toolset(registry: SkillRegistry) -> FunctionToolset:
    """Agent tools for listing and loading skill bodies."""
    def load_skill(name: str, file: str | None = None) -> str:
        """Load a skill's full body by name, or one of its companion files.

        Companion files are referenced by bare filename within the skill's
        directory, e.g. load_skill('prototype', file='LOGIC.md').
        """
        from pydantic_ai import ModelRetry

        body = registry.load(name, file)
        if body is None:
            if file:
                files = ', '.join(registry.companions(name)) or '(none)'
                raise ModelRetry(
                    f'Skill {name!r} has no companion file {file!r}. '
                    f'Companion files: {files}'
                )
            available = ', '.join(s['name'] for s in registry.index()) or '(none)'
            raise ModelRetry(f'No skill named {name!r}. Available: {available}')
        if not file:
            companions = registry.companions(name)
            body += '\n\n---\nSkill directory: ' + (registry.directory(name) or '')
            if companions:
                body += (
                    '\nCompanion files: ' + ', '.join(companions)
                    + " — load any with load_skill('" + name
                    + "', file='<filename>')."
                )
        return body

    return FunctionToolset([load_skill])

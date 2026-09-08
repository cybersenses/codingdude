"""Skills: reusable procedures (SKILL.md files) with progressive disclosure.

Only the index (name + description) enters the context; the body is fetched
on demand via the `load_skill` tool — the same convention as the SKILL.md
ecosystem. Sources merge project-over-global per skill name.
"""

import json
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset


class SkillRegistry:
    def __init__(self, home: Path, workdir: Path):
        self.home = home
        self.workdir = workdir

    def _dirs(self) -> list[Path]:
        return [
            self.home / 'skills',
            self.workdir / '.codingdude' / 'skills',
        ]

    def _scan(self) -> dict[str, dict]:
        """All skills, project overriding global per name."""
        found: dict[str, dict] = {}
        for directory in self._dirs():
            if not directory.exists():
                continue
            for skill_md in sorted(directory.glob('*/SKILL.md')):
                try:
                    raw = skill_md.read_text(encoding='utf-8')
                    # Frontmatter: first line(s) of JSON before the first blank line.
                    body_start = raw.find('\n\n')
                    meta = json.loads(raw[:body_start]) if body_start != -1 else {}
                    body = raw[body_start + 2:] if body_start != -1 else raw
                    found[meta.get('name', skill_md.parent.name)] = {
                        'name': meta.get('name', skill_md.parent.name),
                        'description': meta.get('description', ''),
                        'body': body.strip(),
                    }
                except (json.JSONDecodeError, OSError):
                    continue
        return found

    def index(self) -> list[dict]:
        return [
            {'name': s['name'], 'description': s['description']}
            for s in self._scan().values()
        ]

    def load(self, name: str) -> str | None:
        skill = self._scan().get(name)
        return skill['body'] if skill else None

    def detail(self) -> list[dict]:
        return list(self._scan().values())

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
    def load_skill(name: str) -> str:
        """Load the full body of an installed skill by name."""
        body = registry.load(name)
        if body is None:
            available = ', '.join(s['name'] for s in registry.index()) or '(none)'
            from pydantic_ai import ModelRetry

            raise ModelRetry(f'No skill named {name!r}. Available: {available}')
        return body

    return FunctionToolset([load_skill])

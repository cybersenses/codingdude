"""R15: research pipeline — curated web research saved into reference/research/.

The agent drives research with the existing web_search/web_fetch tools; this
module provides the discipline (process rules live in the tool docstrings,
one source of truth) and the persistence path into the R11 reference
knowledgebase. Files land under `reference/research/`, so the existing
ReferenceStore index picks them up with no new retrieval path.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import _atomic_write

_URL = re.compile(r'https?://\S+')
_STAMP = re.compile(r'As of:', re.IGNORECASE)
_UNSAFE = re.compile(r'[^a-z0-9]+')


def _slug(topic: str) -> str:
    slug = _UNSAFE.sub('-', topic.strip().lower()).strip('-')
    if not slug:
        raise ValueError('topic must contain at least one word or digit character')
    return slug[:80].rstrip('-')


def build_research_toolset(workdir: Path | str) -> FunctionToolset:
    """The `save_research` tool, bound to the project Workdir."""

    def save_research(topic: str, markdown: str, replace: bool = False) -> str:
        """Save curated research findings as a project reference document.

        Write the full document yourself — do not dump raw search results. It MUST:
        1. Carry an `As of: <date>` stamp near the top (best practices age).
        2. Cite at least one source URL, attached to the claim it supports.
        3. Flag contradictions between sources and note confidence levels.

        Process discipline (follow it unless the user bounded the query):
        - Decompose the subject into subtopics/variants and research each.
        - Read up to 5 sources per subtopic, reliable-first (official docs,
          specs, RFCs, high-signal engineering sources — not content farms).
        - If sources wildly disagree, pull up to 5 more for that subtopic.
          Never exceed that escalation — converge or record the disagreement.
        - Before saving, present a findings summary to the user with ask_user
          for validation (soft gate — saving is not gated, but their feedback
          belongs in the doc).

        Saves to reference/research/<topic>.md and auto-joins the reference
        index on the next search_references call. Refuses to overwrite an
        existing doc unless replace=True (updates should be deliberate).
        Freshness is a human call: re-research only when the user asks.
        """
        if not markdown or not markdown.strip():
            raise ValueError('markdown is empty — write the curated document first')
        if not _STAMP.search(markdown):
            raise ValueError(
                'research document is missing an "As of: <date>" stamp — add it '
                f'(today: {_dt.date.today().isoformat()})'
            )
        if not _URL.search(markdown):
            raise ValueError(
                'research document cites no source URLs — attach at least one '
                'citation per major claim'
            )
        root = Path(workdir) / 'reference' / 'research'
        root.mkdir(parents=True, exist_ok=True)
        target = root / f'{_slug(topic)}.md'
        if target.exists() and target.stat().st_size > 0 and not replace:
            raise ValueError(
                f'{target} already exists — read it first, then either merge via '
                'edit_file or pass replace=True for a deliberate rewrite'
            )
        _atomic_write(target, markdown.rstrip() + '\n')
        return (
            f'saved reference/research/{target.name} — it is now indexed and '
            'findable via search_references'
        )

    return FunctionToolset([save_research])

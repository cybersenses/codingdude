"""CodingDude plugin system.

Phase 1: a composition function that builds every toolset from a PluginContext.
Phase 2 (later): each builder becomes a Plugin class with tools(), hooks(),
and instructions(). The PluginContext and build_all() interface stay the same.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset

from codingdude.approvals import ApprovalPolicy
from codingdude.ast_tools import build_ast_toolset
from codingdude.config import Config, parse_thinking
from codingdude.db import Database
from codingdude.deadcode import build_deadcode_toolset
from codingdude.mcp_config import load_merged_mcp_toolsets
from codingdude.memory import MemoryStore, build_memory_toolset
from codingdude.planning import build_planning_toolset
from codingdude.repo_map import build_repo_map_toolset
from codingdude.semantic import SemanticIndex, build_semantic_toolset
from codingdude.skills import SkillRegistry, build_skills_toolset
from codingdude.tools import (
    build_ask_user_toolset,
    build_audit_toolset,
    build_ci_toolset,
    build_coverage_toolset,
    build_delegation_toolset,
    build_git_toolset,
    build_knip_toolset,
    build_shell_toolset,
    build_toolset,
    build_web_toolset,
)


@dataclass
class PluginContext:
    """Everything a plugin can access about the host."""

    workdir: Path
    config: Config
    db: Database
    session_id: str
    home: Path
    shell_bin: str = "bash"
    test_command: str = "pytest -q"
    fix_loop: bool = False
    approvals: ApprovalPolicy | None = None
    subagent_model: Model | None = None
    thinking: str | None = None
    review_model: Model | None = None
    embedder: object | None = None
    on_edit: Callable | None = None
    capture: Callable | None = None
    emitter: Callable | None = None


def build_all(ctx: PluginContext) -> list[AbstractToolset]:
    """Build every toolset for the current run."""
    toolsets: list[AbstractToolset] = [
        build_toolset(
            ctx.workdir,
            on_edit=ctx.on_edit,
            approvals=ctx.approvals,
            capture=ctx.capture,
        ),
    ]

    if ctx.approvals is not None:
        toolsets.extend([
            build_shell_toolset(ctx.workdir, ctx.approvals, shell_bin=ctx.shell_bin),
            build_git_toolset(ctx.workdir, ctx.approvals),
            build_coverage_toolset(ctx.workdir, ctx.approvals),
            build_ask_user_toolset(ctx.approvals),
        ])

    thinking_setting = parse_thinking(ctx.thinking)
    if ctx.subagent_model is not None:
        toolsets.append(build_delegation_toolset(
            ctx.workdir, ctx.subagent_model, thinking=thinking_setting,
        ))

    toolsets.append(build_web_toolset())
    toolsets.append(build_ast_toolset(ctx.workdir))
    toolsets.append(build_deadcode_toolset(ctx.workdir))
    toolsets.append(build_repo_map_toolset(ctx.workdir))
    toolsets.append(build_knip_toolset(ctx.workdir))
    toolsets.append(build_ci_toolset(ctx.workdir))
    toolsets.append(build_audit_toolset(ctx.workdir))

    try:
        toolsets.extend(load_merged_mcp_toolsets(ctx.home, ctx.workdir))
    except Exception:
        pass

    if ctx.embedder is not None:
        toolsets.append(build_semantic_toolset(
            ctx.workdir, SemanticIndex(ctx.embedder, ctx.db),
        ))

    toolsets.append(build_planning_toolset(
        ctx.db, ctx.session_id, ctx.approvals, ctx.emitter,
        review_model=ctx.review_model, thinking=thinking_setting,
    ))

    registry = SkillRegistry(ctx.home)
    toolsets.append(build_skills_toolset(registry))
    toolsets.append(build_memory_toolset(MemoryStore(ctx.db), str(ctx.workdir)))

    return toolsets

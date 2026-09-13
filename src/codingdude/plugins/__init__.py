"""CodingDude plugin system.

Phase 1: a composition function that builds every toolset from a PluginContext.
Phase 2 (later): each builder becomes a Plugin class with tools(), hooks(),
and instructions(). The PluginContext and build_all() interface stay the same.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset

from codingdude.approvals import ApprovalPolicy
from codingdude.artifacts import build_artifacts_toolset
from codingdude.ast_tools import build_ast_toolset
from codingdude.config import Config, ThinkingSetting
from codingdude.db import Database
from codingdude.deadcode import build_deadcode_toolset
from codingdude.execution import ExecutionStore, build_execution_toolset
from codingdude.mcp_config import (
    load_merged_mcp_toolsets,
    merged_mcp_server_names,
    verify_mcp_toolsets,
)
from codingdude.memory import MemoryStore, build_memory_toolset
from codingdude.planning import build_planning_toolset
from codingdude.references import build_references_toolset
from codingdude.repo_map import build_repo_map_toolset
from codingdude.roadmap import RoadmapStore, build_roadmap_toolset
from codingdude.sandbox import build_sandbox_toolset
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
from codingdude.vision import build_vision_toolset


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
    thinking: ThinkingSetting | None = None
    review_model: Model | None = None
    vision_model: Model | None = None
    embedder: object | None = None
    on_edit: Callable | None = None
    capture: Callable | None = None
    emitter: Callable | None = None


async def build_all(ctx: PluginContext) -> list[AbstractToolset]:
    """Build every toolset for the current run."""
    toolsets: list[AbstractToolset] = [
        build_toolset(
            ctx.workdir,
            on_edit=ctx.on_edit,
            approvals=ctx.approvals,
            capture=ctx.capture,
        ),
    ]

    def on_render(rel_path: str) -> None:
        if ctx.emitter is not None:
            ctx.emitter({'type': 'RENDER_CAPTURED', 'path': rel_path})

    if ctx.approvals is not None:
        toolsets.extend([
            build_shell_toolset(
                ctx.workdir, ctx.approvals, shell_bin=ctx.shell_bin, on_render=on_render,
            ),
            build_git_toolset(ctx.workdir, ctx.approvals),
            build_coverage_toolset(ctx.workdir, ctx.approvals),
            build_sandbox_toolset(ctx.workdir, ctx.approvals),
            build_ask_user_toolset(ctx.approvals),
        ])

    thinking_setting = ctx.thinking
    if ctx.subagent_model is not None:
        toolsets.append(build_delegation_toolset(
            ctx.workdir, ctx.subagent_model, thinking=thinking_setting,
        ))

    toolsets.append(build_web_toolset())
    if ctx.vision_model is not None:
        toolsets.append(build_vision_toolset(
            ctx.vision_model, ctx.workdir, emitter=ctx.emitter,
        ))
    toolsets.append(build_ast_toolset(ctx.workdir))
    toolsets.append(build_deadcode_toolset(ctx.workdir))
    toolsets.append(build_repo_map_toolset(ctx.workdir))
    toolsets.append(build_knip_toolset(ctx.workdir))
    toolsets.append(build_ci_toolset(ctx.workdir))
    toolsets.append(build_audit_toolset(ctx.workdir))

    try:
        names = merged_mcp_server_names(ctx.home, ctx.workdir)
        mcp_toolsets = load_merged_mcp_toolsets(ctx.home, ctx.workdir)
        # Pre-flight: a flaky MCP spawn must degrade to "no MCP this run",
        # not kill the run mid-flight (agent can't fix itself otherwise).
        toolsets.extend(await verify_mcp_toolsets(names, mcp_toolsets))
    except Exception as exc:
        # MCP is optional: config/spawn problems degrade the run, they never
        # kill it — but they are never silent (self-review M7).
        logging.getLogger(__name__).warning(
            'MCP toolsets unavailable this run: %s', exc,
        )

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
    toolsets.append(build_roadmap_toolset(RoadmapStore(ctx.db), str(ctx.workdir)))
    toolsets.append(build_references_toolset(ctx.db, ctx.workdir))
    toolsets.append(build_artifacts_toolset(ctx.db, ctx.session_id))
    toolsets.append(
        build_execution_toolset(ExecutionStore(ctx.db, str(ctx.workdir)), ctx.session_id)
    )

    return toolsets

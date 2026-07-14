"""Runtime object discovery — scans agents/ for module-level Agno objects."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

from agno.agent import Agent
from agno.team import Team
from agno.workflow import Workflow
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter


def discover_runtime_objects(
    agents_dir: str = "agents",
    repo_root: Path | None = None,
) -> tuple[list, list, list, list, list]:
    """Scan agents/ for Agent, Team, Workflow, AsyncIOScheduler, and APIRouter instances.

    Returns (agents, teams, workflows, schedulers, routers).
    """
    agents: list = []
    teams: list = []
    workflows: list = []
    schedulers: list = []
    routers: list = []

    agents_path = Path(agents_dir)
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    for module_info in pkgutil.iter_modules([str(agents_path)]):
        try:
            module = importlib.import_module(f"{agents_dir}.{module_info.name}")
            for name, obj in inspect.getmembers(module):
                if name.startswith("_"):
                    continue
                if isinstance(obj, Agent):
                    agents.append(obj)
                elif isinstance(obj, Team):
                    teams.append(obj)
                elif isinstance(obj, Workflow):
                    workflows.append(obj)
                elif isinstance(obj, AsyncIOScheduler):
                    schedulers.append(obj)
                elif isinstance(obj, APIRouter):
                    routers.append(obj)
        except Exception as exc:
            print(
                f"[runtime] Warning: could not load {agents_dir}/{module_info.name}.py — {exc}"
            )

    return agents, teams, workflows, schedulers, routers
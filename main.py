"""RevCrew: AI revenue crew for B2B sales teams. Agno multi-agent system."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from agno.os import AgentOS

from app.runtime import discover_runtime_objects

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown: start schedulers, connect toolboxes."""
    # Schedulers are started by AgentOS when scheduler=True
    yield


def create_app() -> FastAPI:
    """Build the AgentOS + FastAPI application from discovered agents/."""
    agents, teams, workflows, schedulers, routers = discover_runtime_objects()

    base_app = FastAPI(lifespan=lifespan)

    agent_os = AgentOS(
        id="revcrew",
        name="RevCrew",
        description="An AI revenue crew for B2B sales teams: HubSpot, Slack & Instantly, human-in-the-loop by design.",
        agents=agents,
        teams=teams,
        workflows=workflows,
        base_app=base_app,
    )
    app = agent_os.get_app()

    # Mount webhook and intake routers
    from app.webhooks.instantly import router as instantly_router
    from app.webhooks.intake import router as intake_router
    from app.webhooks.slack import router as slack_router

    app.include_router(slack_router)
    app.include_router(instantly_router)
    app.include_router(intake_router)

    # Mount any additional routers discovered in agents/
    for router in routers:
        app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Attempt Agno Viz tracing attach (no-op unless AGNO_VIZ_* env vars set)
    try:
        from agno_viz.tracing import attach

        attach()
    except ImportError:
        pass

    return app


app = create_app()
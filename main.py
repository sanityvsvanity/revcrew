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
    # Start discovered schedulers (S0.7)
    for scheduler in _schedulers:
        scheduler.start()
    yield
    # Shutdown schedulers
    for scheduler in _schedulers:
        scheduler.shutdown(wait=False)


# Module-level reference for lifespan access
_schedulers: list = []


def create_app() -> FastAPI:
    """Build the AgentOS + FastAPI application from discovered agents/."""
    global _schedulers
    agents, teams, workflows, schedulers, routers = discover_runtime_objects()
    _schedulers = schedulers

    base_app = FastAPI(lifespan=lifespan)

    from app.config import settings

    agent_os_kwargs: dict = {
        "id": "revcrew",
        "name": "RevCrew",
        "description": "An AI revenue crew for B2B sales teams: HubSpot, Slack & Instantly, human-in-the-loop by design.",
        "agents": agents,
        "teams": teams,
        "workflows": workflows,
        "base_app": base_app,
    }

    # AgentOS auth (S5.2): bearer-token auth on AgentOS endpoints when
    # OS_SECURITY_KEY is set. Agno takes it via AgnoAPISettings — there is
    # no security_key kwarg on AgentOS itself.
    if settings.OS_SECURITY_KEY:
        from agno.os.settings import AgnoAPISettings

        agent_os_kwargs["settings"] = AgnoAPISettings(
            os_security_key=settings.OS_SECURITY_KEY,
            env="prod" if settings.ENV == "prod" else "dev",
        )
    elif not settings.DEMO_MODE:
        print("[main] Warning: OS_SECURITY_KEY not set — AgentOS endpoints are unauthenticated")

    agent_os = AgentOS(**agent_os_kwargs)
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
"""RevCrew: AI revenue crew for B2B sales teams. Agno multi-agent system."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from agno.os import AgentOS

from app.runtime import discover_runtime_objects

load_dotenv()

__version__ = "2.0.0"


def _sqlalchemy_url(url: str) -> str:
    """agno's PostgresDb wants the SQLAlchemy dialect; psycopg wants libpq."""
    return url if "+psycopg" in url else url.replace("postgresql://", "postgresql+psycopg://", 1)


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

    @base_app.get("/health")
    async def health(probe: int = 0):
        """Liveness (cheap, always) and, with ?probe=1, live integration states.

        The plain call is what Railway polls: process up, database answering.
        The probed call is what an operator opens: one real read per configured
        integration, four states each, never cached (app/probes.py).
        """
        from app.probes import DOWN, OK, run_probes, worst

        db = (await run_probes(["database"]))[0]
        body: dict = {
            "status": "ok" if db["state"] == OK else "degraded",
            "database": db["state"],
            "mode": "demo" if settings.DEMO_MODE else "live",
            "version": __version__,
        }
        if probe:
            results = await run_probes()
            body["integrations"] = {r["name"]: {k: r[k] for k in ("state", "detail", "latency_ms")} for r in results}
            body["status"] = "down" if worst([r["state"] for r in results]) == DOWN else body["status"]
        return body


    agent_os_kwargs: dict = {
        "id": "revcrew",
        "name": "RevCrew",
        "description": "An AI revenue crew for B2B sales teams: HubSpot, Slack & Instantly, human-in-the-loop by design.",
        "agents": agents,
        "teams": teams,
        "workflows": workflows,
        "base_app": base_app,
        # agno mounts its own /health; ours (database state + probes) wins.
        "on_route_conflict": "preserve_base_app",
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


    # Tracing. TRACING_ENABLED turns on agno's own OpenTelemetry exporter into
    # Postgres (agno_traces / agno_spans), which is what AgentOS renders as a
    # span tree per run. Failure to set it up is logged, never fatal: a
    # tracing outage must not take chat down with it.
    if settings.TRACING_ENABLED:
        try:
            from agno.db.postgres import PostgresDb
            from agno.tracing import setup_tracing

            setup_tracing(PostgresDb(db_url=_sqlalchemy_url(settings.DATABASE_URL)), batch_processing=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[main] Warning: tracing not enabled: {exc}")

    # Agno Viz bridge (additive): no-op unless the package and AGNO_VIZ_* are present.
    try:
        from agno_viz.tracing import attach

        attach()
    except ImportError:
        pass

    return app


app = create_app()
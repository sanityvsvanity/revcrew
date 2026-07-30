"""Interactive entry point: choose demo mode (no keys) or live mode (keys).

Run with .venv/bin/python start.py

Demo mode boots Postgres and runs the full pipeline with zero credentials.
Live mode collects credentials one integration at a time, checks each against
the real API before moving on, and writes .env. Skip anything with Enter;
every integration works independently.

Helpers are pure functions so tests cover env merging and the credential
checks without a TTY.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


# ── .env handling ──


def merge_env(text: str, updates: dict[str, str]) -> str:
    """Set KEY=value lines in env-file text, preserving comments and order.

    Existing keys are updated in place; new keys are appended at the end.
    """
    remaining = dict(updates)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[i] = f"{key}={remaining.pop(key)}"
    for key, value in remaining.items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_env(updates: dict[str, str]) -> Path:
    """Merge updates into .env (seeded from .env.example), backing up first."""
    env_path = ROOT / ".env"
    source = env_path if env_path.exists() else ROOT / ".env.example"
    text = source.read_text()
    if env_path.exists():
        (ROOT / ".env.bak").write_text(text)
    env_path.write_text(merge_env(text, updates))
    return env_path


# ── credential checks (best effort, never block) ──


def _get(url: str, headers: dict[str, str]) -> tuple[bool, str]:
    import httpx

    try:
        resp = httpx.get(url, headers=headers, timeout=8)
    except Exception as exc:
        return False, f"unreachable ({exc.__class__.__name__})"
    if resp.status_code == 200:
        return True, "ok"
    return False, f"HTTP {resp.status_code}"


def check_slack(token: str) -> tuple[bool, str]:
    import httpx

    try:
        resp = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        data = resp.json()
    except Exception as exc:
        return False, f"unreachable ({exc.__class__.__name__})"
    if data.get("ok"):
        return True, f"authed as {data.get('user', 'bot')} in {data.get('team', 'workspace')}"
    return False, data.get("error", "auth failed")


def check_hubspot(token: str) -> tuple[bool, str]:
    return _get(
        "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
        {"Authorization": f"Bearer {token}"},
    )


def check_anthropic(key: str) -> tuple[bool, str]:
    return _get(
        "https://api.anthropic.com/v1/models",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )


def check_ollama(host: str, api_key: str) -> tuple[bool, str]:
    if host:
        return _get(f"{host.rstrip('/')}/api/tags", {})
    return _get("https://ollama.com/api/tags", {"Authorization": f"Bearer {api_key}"})


def check_firecrawl(key: str) -> tuple[bool, str]:
    import httpx

    try:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            json={"query": "connectivity check", "limit": 1},
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
    except Exception as exc:
        return False, f"unreachable ({exc.__class__.__name__})"
    if resp.status_code == 200:
        return True, "ok (used one search credit to verify)"
    return False, f"HTTP {resp.status_code}"


def check_instantly(key: str) -> tuple[bool, str]:
    return _get(
        "https://api.instantly.ai/api/v2/campaigns?limit=1",
        {"Authorization": f"Bearer {key}"},
    )


# ── interaction ──


def ask(prompt: str) -> str:
    return input(f"{prompt}: ").strip()


def report(name: str, ok: bool, detail: str) -> None:
    mark = "ok" if ok else "FAILED"
    print(f"  [{mark}] {name}: {detail}")
    if not ok:
        print("         Stored anyway. Fix it and rerun start.py, checks are repeatable.")


def demo_flow() -> int:
    print("\nDemo mode: real approval gate, outbox and Postgres state, canned agent")
    print("outputs so it is deterministic and free. Starting Postgres...\n")
    subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT, check=False)
    result = subprocess.run([sys.executable, "-m", "demo.run_demo"], cwd=ROOT, check=False)
    if result.returncode == 0:
        print("\nDemo done. Next steps, in order of payoff:")
        print("  1. Rerun start.py and pick live mode to connect your own stack")
        print("  2. Edit app/icp.yaml so the qualifier scores your ICP, not ours")
        print("  3. README 'Setup, step by step' for Slack, HubSpot and Instantly")
    return result.returncode


def live_flow() -> int:
    print("\nLive mode. Each integration is optional and independent; Enter skips.")
    print("Have ready: whichever of Slack, HubSpot, Instantly, model keys you want.")
    print("Each credential is checked against the real API as you enter it.\n")

    updates: dict[str, str] = {}

    print("Model provider (pick one; Enter to skip all):")
    print("  ollama.cloud API key, a local Ollama host, or an Anthropic API key")
    ollama_key = ask("OLLAMA_API_KEY (ollama.cloud)")
    ollama_host = "" if ollama_key else ask("OLLAMA_HOST (local, e.g. http://localhost:11434)")
    anthropic_key = ask("ANTHROPIC_API_KEY (primary if no Ollama, else triage fallback)")
    if ollama_key or ollama_host:
        updates["OLLAMA_API_KEY"] = ollama_key
        updates["OLLAMA_HOST"] = ollama_host
        report("ollama", *check_ollama(ollama_host, ollama_key))
    if anthropic_key:
        updates["ANTHROPIC_API_KEY"] = anthropic_key
        report("anthropic", *check_anthropic(anthropic_key))

    print("\nResearch (optional): Firecrawl upgrades web search and page scraping.")
    print("Without it, research uses the free DuckDuckGo tier.")
    firecrawl_key = ask("FIRECRAWL_API_KEY")
    if firecrawl_key:
        updates["FIRECRAWL_API_KEY"] = firecrawl_key
        report("firecrawl", *check_firecrawl(firecrawl_key))

    print("\nSlack (README step 3 covers creating the app from slack/manifest.yaml):")
    slack_token = ask("SLACK_BOT_TOKEN (xoxb-...)")
    if slack_token:
        updates["SLACK_BOT_TOKEN"] = slack_token
        updates["SLACK_SIGNING_SECRET"] = ask("SLACK_SIGNING_SECRET")
        updates["SLACK_CHANNEL_ID"] = ask("SLACK_CHANNEL_ID")
        report("slack", *check_slack(slack_token))

    print("\nHubSpot (use a developer test account, not production):")
    hubspot_token = ask("HUBSPOT_PRIVATE_APP_TOKEN")
    if hubspot_token:
        updates["HUBSPOT_PRIVATE_APP_TOKEN"] = hubspot_token
        report("hubspot", *check_hubspot(hubspot_token))

    print("\nInstantly:")
    instantly_key = ask("INSTANTLY_API_KEY")
    if instantly_key:
        updates["INSTANTLY_API_KEY"] = instantly_key
        updates["INSTANTLY_WEBHOOK_SECRET"] = ask("INSTANTLY_WEBHOOK_SECRET (shared secret)")
        report("instantly", *check_instantly(instantly_key))

    if not updates:
        print("\nNothing configured. Run the demo instead, or rerun when you have keys.")
        return 0

    print("\nDEMO_MODE=false switches every configured integration to its live")
    print("adapter. Keeping DEMO_MODE=true runs live Slack chat with mocked CRM")
    print("and outreach, which is the safe way to try the approval flow.")
    if ask("Set DEMO_MODE=false now? (yes/no)").lower() in ("y", "yes"):
        updates["DEMO_MODE"] = "false"

    env_path = write_env(updates)
    print(f"\nWrote {env_path} ({'backup in .env.bak' if (ROOT / '.env.bak').exists() else 'new file'}).")
    print("Next:")
    print("  1. Edit app/icp.yaml so the qualifier scores your ICP")
    print("  2. Start the server: ./scripts/dev.sh")
    if slack_token:
        print("  3. Slack needs to reach the server: tunnel or deploy, README step 3")
    print("  Full checklist: README 'Setup, step by step'")
    return 0


def main() -> int:
    print("RevCrew")
    print("\nHow do you want to run it?")
    print("  1. Demo: full pipeline, local Postgres, zero keys (about 2 minutes)")
    print("  2. Live: connect your Slack, HubSpot, Instantly and models")
    choice = ask("\nPick 1 or 2")
    if choice.startswith("2") or choice.lower().startswith("l"):
        return live_flow()
    return demo_flow()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing was written unless it said so above.")
        sys.exit(130)

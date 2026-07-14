"""Test that runtime discovery finds the expected objects."""

import pytest

from app.runtime import discover_runtime_objects


def test_discovery_counts():
    """M1 expects: 5 agents, 1 team, 2 workflows."""
    agents, teams, workflows, schedulers, routers = discover_runtime_objects()

    agent_names = [a.name for a in agents]
    team_names = [t.name for t in teams]
    workflow_names = [w.name for w in workflows]

    print(f"Agents found: {agent_names}")
    print(f"Teams found: {team_names}")
    print(f"Workflows found: {workflow_names}")

    assert len(agents) == 5, f"Expected 5 agents, got {len(agents)}: {agent_names}"
    assert len(teams) == 1, f"Expected 1 team, got {len(teams)}: {team_names}"
    assert len(workflows) == 2, f"Expected 2 workflows, got {len(workflows)}: {workflow_names}"

    # Verify specific agents
    assert "researcher" in agent_names
    assert "qualifier" in agent_names
    assert "outreach_writer" in agent_names
    assert "crm_scribe" in agent_names
    assert "copilot" in agent_names

    # Verify team
    assert "gtm_desk" in team_names

    # Verify workflows
    assert "lead_pipeline" in workflow_names
    assert "reply_triage" in workflow_names
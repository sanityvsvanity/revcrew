"""The regression suite: one case per failure that has already happened.

Built on ``agno.eval`` (``Case``, ``run_cases``) with a ``Scorer`` for the check a judge cannot make:
whether every URL in a brief came out of a tool. agno's judge sees the input and the output, not the
tool results (``agno/eval/agent_as_judge.py``), so grounding is scored by code that reads the whole
``RunOutput``. The rule the pipeline enforces is applied here to a live run, so a prompt or model change
that brings invention back fails here before it reaches a rep.

The cases cost real tool calls and a live model, so they do not run on a schedule or in CI.
``scripts/evals.py`` runs them on demand, and ``--list`` reads ``SPECS`` only and builds no agent.
"""

"""The regression suite: one case per failure already paid for.

Built on ``agno.eval`` (``Case``, ``run_cases``) with a ``Scorer`` for the
check a judge cannot make: whether every URL in a brief came out of a tool.
``agno``'s judge sees the input and the output, never the tool results
(``agno/eval/agent_as_judge.py``), so "grounded" is scored by code that reads
the whole ``RunOutput`` — the same rule the pipeline enforces, applied to a
live run so a prompt or model change that reintroduces invention fails here
before it reaches a rep.

The cases cost real tool calls and a live model, so they never run on a
schedule or in CI. ``scripts/evals.py`` runs them on demand; ``--list`` reads
``SPECS`` only and builds no agent.
"""

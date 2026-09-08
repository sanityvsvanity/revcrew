# LESSONS — rules earned from failures, symptom → cause → rule

Most of these were paid for on a sibling system (a Chief-of-Staff copilot on the same stack,
2026-06 → 2026-09) and adopted here in v2.0.0 rather than re-learned. Each names the code that
enforces it; a rule without an enforcer is a wish.

| # | Symptom | Cause | Rule | Enforced by |
|---|---|---|---|---|
| L1 | Research briefs cited URLs no tool ever returned; 22/30 accounts had no evidence | The model completes patterns; a prompt rule reduces but cannot remove it | Ground after generation, in code, against the ledger of tool results. Remove, never rewrite prose, never add. | `app/research/grounding.py`, `tests/test_grounding.py`, `tests/test_pipeline_shape.py` |
| L2 | "Nothing found" was indistinguishable from "nothing looked for"; dead keys read as quiet days for days | Failures converted to empty strings between fetch and delivery | A miss is a row. Every provider call is recorded, including refusals; a quiet answer needs a verified-empty result. | `app/research/evidence.py`, `router.search` → `verified_empty` |
| L3 | A tool failed the same way hundreds of times in one turn until the tool-call limit | Tools raised, or returned failures with no signal that they were permanent | Every tool returns `{ok, error, error_class, do_not_retry}`; classification is code's job; an identical failure trips a breaker after 3 in 120 s. | `app/toolkits/_contract.py`, `tests/test_contract.py` |
| L4 | A "gate" was stepped around by the scheduled path | The workflow ran the push step right after opening the approval | A gate ends the workflow. The only path to an external write is the human's click. | `agents/pipelines.py`, `tests/test_pipeline_shape.py::test_workflow_ends_at_the_gate` |
| L5 | A research agent booted at 145K prompt tokens with another prospect's facts in context | History replay (`num_history_runs`) on a single-purpose agent | Pipeline agents carry no history and no memory. | `app/models.py::pipeline_agent_kwargs`, `tests/test_pipeline_shape.py` |
| L6 | The model answered "Sun Sep 7" for a Monday | It was handed digits and asked to do calendar arithmetic | Every date crosses into the model already labelled with its weekday, in the configured zone. | `pipeline_agent_kwargs` (`datetime_format` with `%A`), `TIMEZONE` |
| L7 | Structured output failed 100% on attempt 1 on a hosted model | Ollama Cloud returns 200 and drops the schema parameter; agno trusted the class flag | For `ollama.com`, construct the model with native structured outputs off so the schema goes in the prompt and the text is parsed. | `app/models.py::_build_ollama_model`, `TestOllamaCloudGuard` |
| L8 | A dashboard said healthy while every model call had been 401 for days | Health was remembered (a heartbeat) rather than measured | Health is a live, read-only probe with four states: ok, degraded, down, unconfigured. Agents never report system health. | `app/probes.py`, `/health?probe=1` |
| L9 | A metered browser session ran until the vendor's hard cap | Nothing on our side bounded spend | Every metered call is charged against a per-account budget before it runs; the refusal is a ledger row. | `app/research/budget.py`, `router._refuse` |
| L10 | Scraping a platform whose terms forbid it produced fragile, then litigated, data | No policy layer; the tool did whatever the URL said | A deny list applied before any tier, browser opt-in, robots.txt on direct fetches, `tos_class` on every row. | `app/research/policy.py`, `tests/test_research_policy.py` |
| L11 | Tests were green while the path they claimed to cover had never run | A fake that ignores the prompt cannot test the prompt; a shape that is not production's is not a test | Test the real step with a scripted *model* (agno's `Model` subclass) against a real database, and assert on what the tools were asked. | `tests/_scripted_model.py`, `test_research_step_grounds_what_the_model_invents` |
| L12 | An async pool created in one event loop was reused in another and raised "pool closed" | One process-global pool, many `asyncio.run` calls | The pool remembers its loop and rebuilds when the caller's loop differs or the pool was closed. | `app/db.py::get_pool` |
| L13 | An orientation doc claimed a feature the pinned framework version did not have | Docs written against idioms, not the installed version | Pin the framework exactly; state the version in the README; read the installed source before writing a rule about it. | `requirements.txt` (`agno==3.0.7`), this file |
| L14 | A hand-maintained copy of a fact the upstream payload already carried defaulted to wrong | Config and heuristics added where the API already said it | Read the upstream schema (SDK types, API docs) before adding an env var or a heuristic. Job boards, news feeds and Firecrawl metadata already state what earlier code inferred. | `app/research/providers/*` (typed SDK fields, no inference) |

| L15 | The browser tier "worked" in code review and failed three ways on its first real session | An SDK surface written from docs, not from a run | Run every third-party adapter once against the real service before it ships. Stagehand 4.0.2, measured 2026-09-08: pages hang off `stagehand.browser.context`, not `stagehand.context`; `extract(timeout=)` is milliseconds; the Model Gateway compiles the schema in strict mode, so every field must be required; link-ish fields come back as accessibility node ids, not URLs. | `app/research/providers/browser.py`, `docs/research-stack.md` "Verified live" |

## Framework notes (agno 3.0.7, verified against the installed source)

- **Async tools live in `Toolkit.async_functions`.** `Toolkit.register` puts a coroutine function
  there, not in `functions`; `Agent.arun` uses both, `Agent.run` uses only the sync map. Every path
  here is async. If a sync caller ever needs the researcher, register sync twins.
- **`run_context` is injected, not modelled.** A tool parameter named `run_context` is stripped from
  the model-facing schema and filled by agno at call time (`agno/tools/function.py`). The research
  tools use it to key ad-hoc runs.
- **A workflow step executor receives `StepInput`;** previous outputs are in `previous_step_outputs`
  (name → `StepOutput`) and `previous_step_content`. The v1 code read a non-existent `outputs`
  attribute; it only ever ran in the live path.
- **`Workflow` is keyword-only** and `Step(requires_confirmation=…)` became
  `Step(human_review=HumanReview(...))` in 3.0 (see ADR 0001 for why it is not used yet).
- **AgentOS mounts its own `/health`.** A `base_app` route on the same path needs
  `on_route_conflict="preserve_base_app"` or agno's wins silently.
- **`FirecrawlTools` pins `firecrawl-py==3.4.0`.** The current SDK (4.x) is `Firecrawl` /
  `AsyncFirecrawl` with v2 methods (`scrape(url, formats=[...], max_age=...)`, `search(query, sources=[...])`);
  install it directly and do not import the toolkit in the same process.

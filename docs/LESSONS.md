# Lessons

Rules that came out of failures, written as symptom, cause and rule. Most of them were first paid for on
an earlier internal system built on the same stack between June and September 2026, and were adopted
here in v2.0.0 instead of being re-learned. Each rule names the code or test that enforces it.

| # | Symptom | Cause | Rule | Enforced by |
|---|---|---|---|---|
| L1 | Research briefs cited URLs that no tool had returned; 22 of 30 accounts had no evidence | The model completes patterns. A prompt rule reduces this but does not remove it | Ground after generation, in code, against the ledger of tool results. Remove links, keep prose, add nothing | `app/research/grounding.py`, `tests/test_grounding.py`, `tests/test_pipeline_shape.py` |
| L2 | "Nothing found" could not be told apart from "nothing looked for"; dead keys read as quiet days for days | Failures were converted to empty strings between fetch and delivery | Every provider call is a row, including refusals. A quiet answer requires a verified-empty result | `app/research/evidence.py`, `router.search` and its `verified_empty` flag |
| L3 | A tool failed the same way hundreds of times in one turn until the tool-call limit stopped it | Tools raised, or returned failures with no signal that they were permanent | Every tool returns `{ok, error, error_class, do_not_retry}`. Classification is done in code. Three identical failures in 120 s trip a breaker | `app/toolkits/_contract.py`, `tests/test_contract.py` |
| L4 | A gate was bypassed on the scheduled path | The workflow ran the push step right after opening the approval | A gate ends the workflow. The only path to an external write is a human click | `agents/pipelines.py`, `tests/test_pipeline_shape.py::test_workflow_ends_at_the_gate` |
| L5 | A research agent started at 145K prompt tokens with another prospect's facts in context | History replay (`num_history_runs`) on a single-purpose agent | Pipeline agents carry no history and no memory | `app/models.py::pipeline_agent_kwargs`, `tests/test_pipeline_shape.py` |
| L6 | The model answered "Sun Sep 7" for a Monday | It was given digits and left to do calendar arithmetic | Every date crosses into the model already labelled with its weekday, in the configured zone | `pipeline_agent_kwargs` (`datetime_format` with `%A`), `TIMEZONE` |
| L7 | Structured output failed on every first attempt on a hosted model | Ollama Cloud returns HTTP 200 and drops the schema parameter; agno trusted the class flag | For `ollama.com`, construct the model with native structured outputs off so the schema goes in the prompt and the text is parsed | `app/models.py::_build_ollama_model`, `TestOllamaCloudGuard` |
| L8 | A dashboard reported healthy while every model call had been failing with 401 for days | Health was a stored heartbeat rather than a live check | Health comes from a live, read-only probe with four states: ok, degraded, down, unconfigured. Agents do not report system health | `app/probes.py`, `/health?probe=1` |
| L9 | A metered browser session ran until the vendor's own cap | Nothing on our side bounded spend | Every metered call is charged against a per-account budget before it runs, and a refusal is a ledger row | `app/research/budget.py`, `router._refuse` |
| L10 | Scraping a platform whose terms forbid it produced fragile data and, elsewhere, litigation | No policy layer; the tool followed whatever URL it was given | A deny list applied before any tier, browser opt-in, robots.txt on direct fetches, `tos_class` on every row | `app/research/policy.py`, `tests/test_research_policy.py` |
| L11 | Tests were green while the path they claimed to cover had never run | A fake that ignores the prompt cannot test the prompt, and a fixture that differs from production's shape does not test production | Test the real step with a scripted model (an agno `Model` subclass) against a real database, and assert on what the tools were asked | `tests/_scripted_model.py`, `test_research_step_grounds_what_the_model_invents` |
| L12 | An async pool opened in one event loop was reused in another and raised "pool closed" | One process-global pool across many `asyncio.run` calls | The pool remembers its loop and is rebuilt when the caller's loop differs or the pool was closed | `app/db.py::get_pool` |
| L13 | An orientation document described a feature the pinned framework version did not have | Documentation written from memory of the framework rather than the installed version | Pin the framework exactly, state the version in the README, and read the installed source before writing a rule about it | `requirements.txt` (`agno==3.0.7`), this file |
| L14 | A hand-maintained copy of a fact defaulted to wrong when the upstream payload already carried it | Configuration and heuristics were added where the API already stated the fact | Read the upstream schema (SDK types, API docs) before adding an env var or a heuristic. Job boards, news feeds and Firecrawl metadata already state what earlier code inferred | `app/research/providers/*` (typed SDK fields, no inference) |
| L15 | The browser tier passed code review and failed three ways on its first real session | The SDK surface was written from documentation rather than from a run | Run every third-party adapter once against the real service before it ships. Stagehand 4.0.2 on 2026-09-08: pages hang off `stagehand.browser.context`, not `stagehand.context`; `extract(timeout=)` is in milliseconds; the Model Gateway compiles the schema in strict mode, so every field must be required; link fields come back as accessibility node ids rather than URLs | `app/research/providers/browser.py`, `docs/research-stack.md` section "Verified live" |
| L16 | The app booted locally and failed on a clean CI install | A transitive dependency (`python-multipart`, needed by AgentOS form routes) was installed locally but not pinned | CI installs from `requirements.txt` into a clean environment and boots the server; a pin missing there fails the build | `.github/workflows/ci.yml` boot check |

## agno 3.0.7 notes, checked against the installed source

- Async tools are registered in `Toolkit.async_functions`, not `functions`. `Agent.arun` uses both
  maps; `Agent.run` uses only the sync map. Every path in this app is async. If a sync caller ever needs
  the researcher, register sync twins of the tools.
- A tool parameter named `run_context` is removed from the model-facing schema and filled in by agno at
  call time (`agno/tools/function.py`). The research tools use it to key ad-hoc runs.
- A workflow step executor receives a `StepInput`. Previous outputs are in `previous_step_outputs`
  (a dict of step name to `StepOutput`) and `previous_step_content`. The v1 code read an `outputs`
  attribute that does not exist; it only ever ran on the live path.
- `Workflow` is keyword-only, and `Step(requires_confirmation=...)` became
  `Step(human_review=HumanReview(...))` in 3.0. ADR 0001 explains why it is not used yet.
- AgentOS registers its own `/health`. A `base_app` route on the same path needs
  `on_route_conflict="preserve_base_app"`; otherwise agno's route wins without a warning.
- `FirecrawlTools` pins `firecrawl-py==3.4.0`. The current SDK (4.x) exposes `Firecrawl` and
  `AsyncFirecrawl` with v2 methods such as `scrape(url, formats=[...], max_age=...)` and
  `search(query, sources=[...])`. Install it directly and do not import the toolkit in the same process.

#!/usr/bin/env python
"""Run the regression suite on demand.

    .venv/bin/python scripts/evals.py --list
    .venv/bin/python scripts/evals.py --case fabricated_url
    .venv/bin/python scripts/evals.py --tag researcher
    .venv/bin/python scripts/evals.py --all --json out/evals.json

Exit code is 0 only when every selected case passed, so this can gate a deploy.
Needs a live model provider and, for the researcher cases, at least DuckDuckGo
reachable; each case is priced by the research budget like any other run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="print the cases and the incidents they guard",
    )
    ap.add_argument(
        "--case", action="append", default=[], help="run one case by name (repeatable)"
    )
    ap.add_argument("--tag", help="run every case carrying this tag")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", help="write the suite result to this path")
    args = ap.parse_args()

    from evals.cases import SPECS

    if args.list or not (args.case or args.tag or args.all):
        for spec in SPECS:
            print(f"{spec.name:32} {spec.agent:12} {', '.join(spec.tags)}")
            print(f"{'':32} {spec.incident}")
        return 0

    from dotenv import load_dotenv

    load_dotenv()

    from agno.eval.suite import run_cases

    from evals.cases import build_cases

    names = set(args.case) if args.case else None
    cases = build_cases(names)
    if args.tag:
        cases = [c for c in cases if args.tag in c.tags]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    # run_cases is agno's sync wrapper: it owns the event loop for the whole suite.
    result = run_cases(cases)
    payload = (
        result.to_dict()
        if hasattr(result, "to_dict")
        else {"passed": getattr(result, "passed", None)}
    )
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
    passed = bool(getattr(result, "passed", False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

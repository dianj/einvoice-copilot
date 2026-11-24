"""Routing with and without the calibrated route check, on evals/decisions/einvoice.route.jsonl.

1. `--collect`: run the current router (the JSON route call + the code rules) on every case with the real model and
   save the result (evals/decisions/runs/einvoice.route.router.json). The gate's own answers come from
   `python -m copilot.decide.cli collect --question einvoice.route`.
2. Grade both: the router alone, and the router with the check (ask instead of guessing when the calibrated route
   answer disagrees or is not sure). A clear case should be routed right; an unclear one should be asked about.

    python evals/decisions/route_eval.py --collect
    python evals/decisions/route_eval.py [--suffix .qwen3.8-27b]
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from copilot import config, decisions  # noqa: E402
from copilot.decide import Action, Calibration, apply_temperature  # noqa: E402
from copilot.decide.core import Decision, choose_action  # noqa: E402
from copilot.graph import prompts  # noqa: E402
from copilot.graph.nodes.route import apply_code_rules, detect_countries  # noqa: E402
from copilot.llm import complete_json  # noqa: E402

HERE = Path(__file__).parent
RUNS = HERE / "runs"


async def collect() -> Path:
    rows = []
    RUNS.mkdir(exist_ok=True)
    for line in (HERE / "einvoice.route.jsonl").read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        result = await complete_json(prompts.ROUTE_SYSTEM, prompts.route_user(
            case["text"], case["history"], case["has_attachment"], has_draft=case["has_draft"]),
            prompts.ROUTE_SCHEMA, "route", max_tokens=400)
        raw = result.data.get("intent", "out_of_scope")
        countries = sorted(set(result.data.get("countries") or []) & set(prompts.COUNTRY_NAMES)
                           | detect_countries(case["text"]))
        final, clarify = apply_code_rules(raw, countries, case["text"], case["has_attachment"], case["has_draft"])
        rows.append({"id": case["id"], "raw": raw, "final": final, "clarify": clarify, "ms": result.ms})
        print(f"{case['id']:<6} raw {raw:<18} final {final:<18} {result.ms} ms")
    suffix = "" if config.LLM_MODEL == "gemma-4-26b-a4b-it" else f".{config.LLM_MODEL}"
    out = RUNS / f"einvoice.route.router{suffix}.json"
    out.write_text(json.dumps({"model": config.LLM_MODEL, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    return out


def gate_decision(row: dict, cal: Calibration | None, model: str) -> Decision:
    usable = cal is not None and cal.model == model and cal.prompt_hash == decisions.ROUTE.prompt_hash()
    probs = apply_temperature(row["probs_raw"], cal.temperature if usable else 1.0) if row["probs_raw"] else {}
    label = max(probs, key=probs.get) if probs else None
    action = choose_action(decisions.ROUTE, label, probs[label], usable) if label else Action.CONFIRM
    return Decision(decisions.ROUTE.id, label, probs.get(label), None, probs, row["probs_raw"] or {}, action,
                    "policy" if usable else "uncalibrated", row["latency_ms"], None)


def outcome(expected, asked: bool, routed: str) -> str:
    if expected == "unclear":
        return "asked (right)" if asked else "guessed"
    ok = expected if isinstance(expected, list) else [expected]
    if asked:
        return "asked (not needed)"
    return "routed right" if routed in ok else "routed wrong"


def grade(suffix: str = "") -> dict:
    cases = {json.loads(line)["id"]: json.loads(line)
             for line in (HERE / "einvoice.route.jsonl").read_text(encoding="utf-8").splitlines()}
    router = json.loads((RUNS / f"einvoice.route.router{suffix}.json").read_text(encoding="utf-8"))
    gate_run = json.loads((RUNS / f"einvoice.route{suffix}.json").read_text(encoding="utf-8"))
    model = gate_run["model"]
    cal_dir = config.CALIBRATION_DIR
    cal = Calibration.load(cal_dir / model, decisions.ROUTE.id) or Calibration.load(cal_dir, decisions.ROUTE.id)
    gates = {r["id"]: r for r in gate_run["rows"]}
    alone, checked, notes = Counter(), Counter(), []
    for row in router["rows"]:
        expected = cases[row["id"]]["expected"]
        asked = row["final"] == "clarify"
        alone[outcome(expected, asked, row["final"])] += 1
        reason = None
        if not asked and row["final"] == row["raw"]:          # code rules decided otherwise: they stand
            reason = decisions.route_check(row["final"], gate_decision(gates[row["id"]], cal, model))
        result = outcome(expected, asked or reason is not None, row["final"])
        checked[result] += 1
        if result in ("routed wrong", "guessed", "asked (not needed)"):
            notes.append(f"{row['id']}: expected {expected}, router {row['final']}, check {reason or 'kept'}")
    keys = ["routed right", "asked (right)", "routed wrong", "guessed", "asked (not needed)"]
    print(f"model {model}, {len(router['rows'])} cases")
    print("| | " + " | ".join(keys) + " |")
    print("|---|" + "---|" * len(keys))
    print("| router alone | " + " | ".join(str(alone[k]) for k in keys) + " |")
    print("| router + check | " + " | ".join(str(checked[k]) for k in keys) + " |")
    print("\n".join(notes))
    return {"alone": dict(alone), "checked": dict(checked)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--suffix", default="")
    args = parser.parse_args(argv)
    if args.collect:
        print(f"saved {asyncio.run(collect())}")
    else:
        grade(args.suffix)


if __name__ == "__main__":
    main()

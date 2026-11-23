"""Retrieval benchmark: hit@k, MRR, date-filter violations and the abstention threshold, per embedder and ranking.

    python evals/retrieval_benchmark.py                       # both ONNX models, vector-only vs hybrid
    python evals/retrieval_benchmark.py --embedder fake       # smoke run (CI): wiring only, numbers meaningless

No LLM involved. Writes evals/results/retrieval.md (committed) and retrieval.json (details, not committed).
"""
import argparse
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from copilot.kb.embedder import FakeEmbedder, OnnxEmbedder  # noqa: E402
from copilot.kb.retriever import Retriever, all_chunks  # noqa: E402

QUESTIONS = ROOT / "evals" / "benchmark" / "questions.yaml"
RESULTS = ROOT / "evals" / "results"
MODELS = ["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
          "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"]
K = 6


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    default = data["default_as_of"]
    questions = []
    for q in data["questions"]:
        as_of = q.get("as_of", default)
        questions.append({**q, "as_of": as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)),
                          "answerable": q.get("answerable", True), "expected": q.get("expected", [])})
    return questions


def calibrate(answerable: list[float], unanswerable: list[float]) -> dict:
    """The threshold with the best balanced accuracy (midpoint between neighbouring scores); ties: the widest gap."""
    scores = sorted(set(answerable + unanswerable))
    best = None
    for low, high in zip(scores, scores[1:], strict=False):
        threshold = (low + high) / 2
        tpr = sum(s >= threshold for s in answerable) / len(answerable)
        tnr = sum(s < threshold for s in unanswerable) / len(unanswerable)
        key = ((tpr + tnr) / 2, high - low)
        if best is None or key > best[0]:
            best = (key, threshold, tpr, tnr)
    if best is None:
        return {"threshold": None}
    (balanced, _), threshold, tpr, tnr = best
    return {"threshold": round(threshold, 3), "balanced_accuracy": round(balanced, 3),
            "answerable_kept": round(tpr, 3), "unanswerable_refused": round(tnr, 3)}


def abstention(results: list[dict], threshold: float) -> dict:
    refused = [r for r in results if r["top_score"] < threshold]
    unanswerable = [r for r in results if not r["answerable"]]
    correct = [r for r in refused if not r["answerable"]]
    return {"precision": round(len(correct) / len(refused), 3) if refused else None,
            "recall": round(len(correct) / len(unanswerable), 3) if unanswerable else None}


def run(retriever: Retriever, questions: list[dict], hybrid: bool) -> dict:
    results, latencies, violations = [], [], 0
    for q in questions:
        started = time.perf_counter()
        found = retriever.search_sync(q["question"], q["as_of"], k=K, hybrid=hybrid)
        latencies.append((time.perf_counter() - started) * 1000)
        docs = [p.doc_id for p in found.passages]
        violations += sum(not (p.valid_from <= q["as_of"] and (p.valid_to is None or q["as_of"] <= p.valid_to))
                          for p in found.passages)
        rank = next((i + 1 for i, d in enumerate(docs) if d in q["expected"]), None)
        results.append({"id": q["id"], "kind": q["kind"], "answerable": q["answerable"], "docs": docs,
                        "rank": rank, "top_score": found.top_vector_score})
    graded = [r for r in results if r["answerable"]]
    summary = {f"hit@{k}": round(sum(r["rank"] is not None and r["rank"] <= k for r in graded) / len(graded), 3)
               for k in (1, 3, K)}
    summary["mrr"] = round(sum(1 / r["rank"] for r in graded if r["rank"]) / len(graded), 3)
    summary["date_violations"] = violations
    summary["ms_median"] = round(statistics.median(latencies), 1)
    kinds = sorted({r["kind"] for r in graded})
    summary["hit@3_by_kind"] = {kind: round(sum(r["rank"] is not None and r["rank"] <= 3 for r in graded
                                                if r["kind"] == kind) / sum(r["kind"] == kind for r in graded), 3)
                                for kind in kinds}
    summary["calibration"] = calibrate([r["top_score"] for r in graded],
                                       [r["top_score"] for r in results if not r["answerable"]])
    summary["abstention_at_min_score"] = abstention(results, retriever.embedder.min_score)
    summary["min_score"] = retriever.embedder.min_score
    summary["misses"] = [f"{r['id']} -> {r['docs'][:3]}" for r in graded if not r["rank"] or r["rank"] > 3]
    return {"summary": summary, "results": results}


def markdown(report: dict, questions: list[dict]) -> str:
    answerable = sum(q["answerable"] for q in questions)
    lines = ["# Retrieval benchmark", "",
             f"{len(questions)} questions ({answerable} answerable, {len(questions) - answerable} not in the "
             f"documents), k = {K}, generated by `evals/retrieval_benchmark.py` on {date.today().isoformat()}.",
             "A hit means one of the expected documents is among the top k passages.", "",
             "| Embedder | Ranking | hit@1 | hit@3 | hit@6 | MRR | Date-filter violations | Median ms |",
             "|---|---|---|---|---|---|---|---|"]
    for name, runs in report.items():
        for ranking, data in runs.items():
            s = data["summary"]
            lines.append(f"| {name.split('/')[-1]} | {ranking} | {s['hit@1']:.3f} | {s['hit@3']:.3f} | "
                         f"{s['hit@6']:.3f} | {s['mrr']:.3f} | {s['date_violations']} | {s['ms_median']} |")
    lines += ["", "## hit@3 by question kind", "", "| Embedder | Ranking | " +
              " | ".join(next(iter(next(iter(report.values())).values()))["summary"]["hit@3_by_kind"]) + " |"]
    kinds = list(next(iter(next(iter(report.values())).values()))["summary"]["hit@3_by_kind"])
    lines.append("|---|---|" + "---|" * len(kinds))
    for name, runs in report.items():
        for ranking, data in runs.items():
            by_kind = data["summary"]["hit@3_by_kind"]
            lines.append(f"| {name.split('/')[-1]} | {ranking} | " + " | ".join(f"{by_kind[k]:.2f}" for k in kinds)
                         + " |")
    lines += ["", "## Abstention (\"not in the documents\")", "",
              "On the top vector similarity. \"Best threshold\" has the best balanced accuracy between answerable and "
              "unanswerable questions; the configured `min_score` instead sits just below the lowest answerable "
              "question. On-topic questions the documents do not answer (a German VAT rate, payroll in Orlavia) "
              "score as high as answerable ones, so a similarity threshold can only refuse clearly off-topic "
              "questions without losing answerable ones. It is a cheap first gate: the answer step must still say "
              "\"not in the documents\" when the passages do not answer, and the LLM evals measure that.", "",
              "| Embedder | Best threshold | Answerable kept | Unanswerable refused | Configured min_score | "
              "Precision | Recall |", "|---|---|---|---|---|---|---|"]
    for name, runs in report.items():
        s = runs["vector"]["summary"]
        c, a = s["calibration"], s["abstention_at_min_score"]
        lines.append(f"| {name.split('/')[-1]} | {c.get('threshold')} | {c.get('answerable_kept')} | "
                     f"{c.get('unanswerable_refused')} | {s['min_score']} | {a['precision']} | {a['recall']} |")
    lines += ["", "## Misses at k = 3", ""]
    for name, runs in report.items():
        for ranking, data in runs.items():
            misses = data["summary"]["misses"]
            lines.append(f"- **{name.split('/')[-1]}, {ranking}:** " + ("; ".join(misses) if misses else "none"))
    return "\n".join(lines) + "\n"


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedder", choices=["onnx", "fake"], default="onnx")
    parser.add_argument("--models", nargs="*", default=MODELS)
    parser.add_argument("--output", default="retrieval", help="file name stem in evals/results/")
    args = parser.parse_args(argv)
    questions = load_questions()
    embedders = [FakeEmbedder()] if args.embedder == "fake" else [OnnxEmbedder(m) for m in args.models]
    chunks = all_chunks()
    report = {}
    for embedder in embedders:
        retriever = Retriever(chunks, embedder, index_path=None)
        report[embedder.name] = {"vector": run(retriever, questions, hybrid=False),
                                 "hybrid": run(retriever, questions, hybrid=True)}
        for ranking, data in report[embedder.name].items():
            s = data["summary"]
            print(f"{embedder.name} {ranking}: hit@1 {s['hit@1']} hit@3 {s['hit@3']} hit@6 {s['hit@6']} "
                  f"mrr {s['mrr']} violations {s['date_violations']} calibration {s['calibration']}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.embedder == "onnx":
        (RESULTS / f"{args.output}.md").write_text(markdown(report, questions), encoding="utf-8")
        (RESULTS / f"{args.output}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    main()

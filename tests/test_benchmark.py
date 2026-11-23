"""The retrieval benchmark script: question file, calibration maths and a smoke run with the fake embedder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import retrieval_benchmark as bench  # noqa: E402

from copilot.corpus.loader import corpus  # noqa: E402


def test_question_file_is_large_enough_and_cites_real_documents():
    questions = bench.load_questions()
    doc_ids = {d.doc_id for d in corpus()}
    assert len(questions) >= 60 and sum(not q["answerable"] for q in questions) >= 10
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        assert set(q["expected"]) <= doc_ids and bool(q["expected"]) == q["answerable"], q["id"]
    kinds = {q["kind"] for q in questions}
    assert {"version", "obligation", "rule", "none", "bg"} <= kinds


def test_calibration_picks_the_widest_clean_gap():
    result = bench.calibrate([0.7, 0.8, 0.9], [0.1, 0.2, 0.5])
    assert result == {"threshold": 0.6, "balanced_accuracy": 1.0, "answerable_kept": 1.0, "unanswerable_refused": 1.0}
    assert bench.calibrate([0.5], [0.5]) == {"threshold": None}
    assert bench.abstention([{"answerable": False, "top_score": 0.1}, {"answerable": True, "top_score": 0.2}],
                            0.3) == {"precision": 0.5, "recall": 1.0}


def test_smoke_run_with_the_fake_embedder():
    report = bench.main(["--embedder", "fake"])
    runs = report["fake-hashing-256"]
    assert set(runs) == {"vector", "hybrid"}
    for data in runs.values():
        assert data["summary"]["date_violations"] == 0
        assert len(data["results"]) == len(bench.load_questions())

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from ragops.config import MetricThreshold, ThresholdCatalog
from ragops.contracts import (
    BaselineDocument,
    EvalProgress,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    EvaluationReport,
    MetricSummary,
)
from ragops.evaluation import (
    build_baseline,
    evaluate_gate,
    read_baseline,
    render_gate_report,
    write_baseline,
)

THRESHOLDS = ThresholdCatalog(
    metrics={
        "ndcg_at_10": MetricThreshold(maximum_absolute_drop=0.01),
        "faithfulness": MetricThreshold(maximum_absolute_drop=0.02),
    }
)


def report_for(scores: dict[str, float], *, dataset: str = "scifact") -> EvaluationReport:
    now = datetime.now(UTC)
    run = EvalRun(
        id=uuid4(),
        spec=EvalRunSpec(dataset=dataset, variants=("bm25",), seed=42),
        state=EvalRunState.COMPLETED,
        progress=EvalProgress(completed_queries=1, total_queries=1),
        git_commit="abc123",
        created_at=now,
        completed_at=now,
    )
    return EvaluationReport(
        run=run,
        metrics=tuple(
            MetricSummary(
                metric=metric,
                variant="bm25",
                mean=value,
                interval_low=value,
                interval_high=value,
                query_count=1,
            )
            for metric, value in scores.items()
        ),
        latencies=(),
    )


def baseline_for(scores: dict[str, float], *, dataset: str = "scifact") -> BaselineDocument:
    return BaselineDocument(
        dataset=dataset,
        split="test",
        run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        metrics={"bm25": scores},
    )


def test_gate_passes_when_metrics_hold_within_tolerance() -> None:
    result = evaluate_gate(
        report_for({"ndcg_at_10": 0.59}),
        baseline_for({"ndcg_at_10": 0.60}),
        THRESHOLDS,
    )

    assert result.passed
    assert result.breaches == ()
    assert result.metrics[0].delta == pytest.approx(-0.01)


def test_gate_fails_when_a_metric_drops_past_its_tolerance() -> None:
    result = evaluate_gate(
        report_for({"ndcg_at_10": 0.50}),
        baseline_for({"ndcg_at_10": 0.60}),
        THRESHOLDS,
    )

    assert not result.passed
    assert [metric.metric for metric in result.breaches] == ["ndcg_at_10"]
    assert "BREACH" in render_gate_report(result)


def test_gate_ignores_metrics_without_a_declared_threshold() -> None:
    result = evaluate_gate(
        report_for({"ndcg_at_10": 0.60, "recall_at_10": 0.10}),
        baseline_for({"ndcg_at_10": 0.60, "recall_at_10": 0.90}),
        THRESHOLDS,
    )

    assert result.passed
    assert [metric.metric for metric in result.metrics] == ["ndcg_at_10"]


def test_gate_rejects_a_run_missing_a_baselined_metric() -> None:
    with pytest.raises(ValueError, match="does not report baselined metric"):
        evaluate_gate(
            report_for({"recall_at_10": 0.9}),
            baseline_for({"ndcg_at_10": 0.60}),
            THRESHOLDS,
        )


def test_gate_rejects_a_baseline_for_another_dataset() -> None:
    with pytest.raises(ValueError, match="baseline dataset does not match"):
        evaluate_gate(
            report_for({"ndcg_at_10": 0.60}),
            baseline_for({"ndcg_at_10": 0.60}, dataset="nfcorpus"),
            THRESHOLDS,
        )


def test_baseline_round_trips_through_a_committed_file(tmp_path: Path) -> None:
    report = report_for({"ndcg_at_10": 0.60, "recall_at_10": 0.80})
    baseline = build_baseline(report, variant_hashes={"bm25": "hash-1"})
    path = tmp_path / "baselines" / "main.json"
    write_baseline(baseline, path)

    assert read_baseline(path) == baseline
    assert baseline.run_id == report.run.id
    assert baseline.git_commit == "abc123"
    assert baseline.variant_hashes == {"bm25": "hash-1"}
    assert baseline.metrics == {"bm25": {"ndcg_at_10": 0.60, "recall_at_10": 0.80}}
    assert json.loads(path.read_text())["dataset"] == "scifact"


def test_reading_a_malformed_baseline_reports_the_path(tmp_path: Path) -> None:
    path = tmp_path / "main.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        read_baseline(path)


def test_a_gated_run_round_trips_from_its_own_baseline() -> None:
    report = report_for({"ndcg_at_10": 0.6712})
    baseline = build_baseline(report, variant_hashes={"bm25": "hash-1"})

    result = evaluate_gate(report, baseline, THRESHOLDS)

    assert result.passed
    assert result.baseline_run_id == report.run.id
    assert result.metrics[0].delta == 0.0

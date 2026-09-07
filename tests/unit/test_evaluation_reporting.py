import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ragops.contracts import (
    EvalProgress,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    QueryResult,
    StageTiming,
)
from ragops.evaluation import (
    build_evaluation_report,
    render_markdown_report,
    write_report_files,
)


def completed_run(*, total_queries: int = 2) -> EvalRun:
    now = datetime.now(UTC)
    return EvalRun(
        id=uuid4(),
        spec=EvalRunSpec(dataset="fixture", variants=("bm25",), seed=42),
        state=EvalRunState.COMPLETED,
        progress=EvalProgress(
            completed_queries=total_queries,
            total_queries=total_queries,
        ),
        created_at=now,
        completed_at=now,
    )


def result(run_id: UUID, query_id: str, score: float, latency_ms: float) -> QueryResult:
    return QueryResult(
        run_id=run_id,
        variant="bm25",
        query_id=query_id,
        ranked_document_ids=(),
        stage_timings=(StageTiming(stage="sparse_retrieve", duration_ms=latency_ms),),
        deterministic_scores={
            "ndcg_at_10": score,
            "recall_at_10": score,
            "recall_at_100": score,
            "mrr_at_10": score,
        },
    )


def test_report_aggregates_metrics_intervals_and_latency_percentiles() -> None:
    run = completed_run()
    report = build_evaluation_report(
        run,
        (result(run.id, "q-1", 1.0, 10.0), result(run.id, "q-2", 0.0, 30.0)),
        bootstrap_resamples=200,
    )

    assert len(report.metrics) == 4
    assert all(summary.mean == 0.5 for summary in report.metrics)
    assert all(summary.interval_low == 0.0 for summary in report.metrics)
    assert all(summary.interval_high == 1.0 for summary in report.metrics)
    assert all(summary.query_count == 2 for summary in report.metrics)
    assert len(report.latencies) == 1
    assert report.latencies[0].p50_ms == 20.0
    assert report.latencies[0].p95_ms == pytest.approx(29.0)


def test_report_and_markdown_rendering_are_deterministic() -> None:
    run = completed_run()
    results = (
        result(run.id, "q-1", 1.0, 10.0),
        result(run.id, "q-2", 0.0, 30.0),
    )

    first = build_evaluation_report(run, results, bootstrap_resamples=100)
    second = build_evaluation_report(run, tuple(reversed(results)), bootstrap_resamples=100)
    markdown = render_markdown_report(first)

    assert first == second
    assert f"# Retrieval evaluation `{run.id}`" in markdown
    assert "| bm25 | nDCG@10 | 0.5000 | [0.0000, 1.0000] | 2 |" in markdown
    assert "| bm25 | sparse_retrieve | 20.00 | 29.00 | 2 |" in markdown
    assert markdown.endswith("\n")


def test_report_rejects_incomplete_or_inconsistent_runs() -> None:
    run = completed_run()
    incomplete = run.model_copy(update={"state": EvalRunState.RETRIEVING})

    with pytest.raises(ValueError, match="state 'retrieving'"):
        build_evaluation_report(incomplete, (result(run.id, "q-1", 1.0, 1.0),))
    with pytest.raises(ValueError, match="result count"):
        build_evaluation_report(run, (result(run.id, "q-1", 1.0, 1.0),))


def two_variant_run(*, total_queries: int = 8) -> EvalRun:
    now = datetime.now(UTC)
    return EvalRun(
        id=uuid4(),
        spec=EvalRunSpec(dataset="fixture", variants=("bm25", "dense"), seed=42),
        state=EvalRunState.COMPLETED,
        progress=EvalProgress(completed_queries=total_queries, total_queries=total_queries),
        created_at=now,
        completed_at=now,
    )


def variant_result(run_id: UUID, variant: str, query_id: str, score: float) -> QueryResult:
    return QueryResult(
        run_id=run_id,
        variant=variant,
        query_id=query_id,
        ranked_document_ids=(),
        stage_timings=(),
        deterministic_scores={
            "ndcg_at_10": score,
            "recall_at_10": score,
            "recall_at_100": score,
            "mrr_at_10": score,
        },
    )


def test_paired_bootstrap_detects_a_consistent_per_query_win() -> None:
    """A small but unanimous per-query gap is significant once queries are paired."""
    run = two_variant_run()
    query_ids = [f"q-{index}" for index in range(4)]
    # Query difficulty swings widely; dense is better on every single query by 0.1.
    difficulty = [0.1, 0.4, 0.7, 0.85]
    results = tuple(
        variant_result(run.id, "bm25", query_id, base)
        for query_id, base in zip(query_ids, difficulty, strict=True)
    ) + tuple(
        variant_result(run.id, "dense", query_id, base + 0.1)
        for query_id, base in zip(query_ids, difficulty, strict=True)
    )

    report = build_evaluation_report(run, results, bootstrap_resamples=500)
    ndcg = next(
        comparison for comparison in report.comparisons if comparison.metric == "ndcg_at_10"
    )

    assert ndcg.variant_a == "bm25"
    assert ndcg.variant_b == "dense"
    assert ndcg.difference == pytest.approx(-0.1)
    assert ndcg.significant
    assert ndcg.interval_high < 0

    # The unpaired per-variant intervals overlap, which is exactly why the paired
    # comparison is the statistic the README should quote.
    means = {summary.variant: summary for summary in report.metrics}
    assert means["bm25"].interval_high > means["dense"].interval_low


def test_paired_bootstrap_reports_no_significance_for_a_coin_flip() -> None:
    run = two_variant_run()
    query_ids = [f"q-{index}" for index in range(4)]
    # Each variant wins on half the queries by the same margin.
    results = tuple(
        variant_result(run.id, "bm25", query_id, score)
        for query_id, score in zip(query_ids, (0.9, 0.1, 0.9, 0.1), strict=True)
    ) + tuple(
        variant_result(run.id, "dense", query_id, score)
        for query_id, score in zip(query_ids, (0.1, 0.9, 0.1, 0.9), strict=True)
    )

    report = build_evaluation_report(run, results, bootstrap_resamples=500)
    ndcg = next(
        comparison for comparison in report.comparisons if comparison.metric == "ndcg_at_10"
    )

    assert ndcg.difference == pytest.approx(0.0)
    assert not ndcg.significant
    assert ndcg.interval_low < 0 < ndcg.interval_high


def test_comparisons_cover_every_variant_pair_and_metric() -> None:
    run = two_variant_run()
    query_ids = [f"q-{index}" for index in range(4)]
    results = tuple(
        variant_result(run.id, variant, query_id, 0.5)
        for variant in ("bm25", "dense")
        for query_id in query_ids
    )

    report = build_evaluation_report(run, results, bootstrap_resamples=100)

    assert len(report.comparisons) == 4  # one pair x four metrics
    assert {comparison.metric for comparison in report.comparisons} == {
        "ndcg_at_10",
        "recall_at_10",
        "recall_at_100",
        "mrr_at_10",
    }
    assert "## Variant comparisons" in render_markdown_report(report)


def test_a_single_variant_run_has_nothing_to_compare() -> None:
    run = completed_run()
    report = build_evaluation_report(
        run,
        (result(run.id, "q-1", 1.0, 10.0), result(run.id, "q-2", 0.0, 30.0)),
        bootstrap_resamples=100,
    )

    assert report.comparisons == ()
    assert "## Variant comparisons" not in render_markdown_report(report)


def test_report_files_are_archived_under_the_run_id(tmp_path: Path) -> None:
    run = completed_run()
    report = build_evaluation_report(
        run,
        (result(run.id, "q-1", 1.0, 10.0), result(run.id, "q-2", 0.0, 30.0)),
        bootstrap_resamples=100,
    )

    markdown_path, json_path = write_report_files(report, tmp_path)

    assert markdown_path == tmp_path / str(run.id) / "report.md"
    assert json_path == tmp_path / str(run.id) / "report.json"
    assert markdown_path.read_text(encoding="utf-8") == render_markdown_report(report)
    assert json.loads(json_path.read_text(encoding="utf-8"))["run"]["id"] == str(run.id)

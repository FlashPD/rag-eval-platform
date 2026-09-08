"""Aggregation and rendering for completed retrieval evaluation runs."""

import hashlib
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from math import floor
from pathlib import Path

from ragops.contracts import (
    Comparison,
    EvalRun,
    EvalRunState,
    EvaluationReport,
    LatencySummary,
    MetricSummary,
    QueryResult,
)
from ragops.evaluation.retrieval_metrics import RETRIEVAL_METRIC_NAMES

DEFAULT_BOOTSTRAP_RESAMPLES = 2_000
_METRIC_LABELS = {
    "ndcg_at_10": "nDCG@10",
    "recall_at_10": "Recall@10",
    "recall_at_100": "Recall@100",
    "mrr_at_10": "MRR@10",
}


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot calculate a mean without values")
    return sum(values) / len(values)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile without values")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower_index = floor(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


def _bootstrap_mean_interval(
    values: Sequence[float], *, seed: int, resamples: int
) -> tuple[float, float]:
    if resamples <= 0:
        raise ValueError("bootstrap resamples must be positive")
    if len(values) == 1:
        return values[0], values[0]
    generator = random.Random(seed)
    sample_size = len(values)
    bootstrap_means = sorted(
        _mean([values[generator.randrange(sample_size)] for _ in range(sample_size)])
        for _ in range(resamples)
    )
    return _percentile(bootstrap_means, 0.025), _percentile(bootstrap_means, 0.975)


def _paired_bootstrap_difference(
    values_a: Sequence[float], values_b: Sequence[float], *, seed: int, resamples: int
) -> tuple[float, float]:
    """Return a 95% interval for the mean per-query difference between two variants.

    Queries are resampled once per iteration and both variants are read at the same
    indices, so the interval reflects the paired difference rather than the much wider
    spread of two independently estimated means. Query difficulty varies far more than
    the gap between variants on the same query, and pairing cancels that shared term.
    """
    if len(values_a) != len(values_b):
        raise ValueError("paired comparison requires one value per variant per query")
    if resamples <= 0:
        raise ValueError("bootstrap resamples must be positive")
    differences = [value_a - value_b for value_a, value_b in zip(values_a, values_b, strict=True)]
    if len(differences) == 1:
        return differences[0], differences[0]
    generator = random.Random(seed)
    sample_size = len(differences)
    bootstrap_means = sorted(
        _mean([differences[generator.randrange(sample_size)] for _ in range(sample_size)])
        for _ in range(resamples)
    )
    return _percentile(bootstrap_means, 0.025), _percentile(bootstrap_means, 0.975)


def _derived_seed(seed: int, variant: str, metric: str) -> int:
    digest = hashlib.sha256(f"{seed}:{variant}:{metric}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def build_variant_comparisons(
    variants: Sequence[str],
    paired_values: Mapping[tuple[str, str], Mapping[str, float]],
    *,
    seed: int,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> tuple[Comparison, ...]:
    """Compare every variant pair on every metric with a paired bootstrap.

    ``difference`` is variant A minus variant B, so a positive value means A scored
    higher. A comparison is significant only when the interval excludes zero.
    """
    comparisons: list[Comparison] = []
    for index, variant_a in enumerate(variants):
        for variant_b in variants[index + 1 :]:
            for metric in RETRIEVAL_METRIC_NAMES:
                by_query_a = paired_values[(variant_a, metric)]
                by_query_b = paired_values[(variant_b, metric)]
                if by_query_a.keys() != by_query_b.keys():
                    raise ValueError(
                        f"variants {variant_a!r} and {variant_b!r} were not evaluated "
                        f"on the same queries for metric {metric!r}"
                    )
                query_ids = sorted(by_query_a)
                values_a = [by_query_a[query_id] for query_id in query_ids]
                values_b = [by_query_b[query_id] for query_id in query_ids]
                interval_low, interval_high = _paired_bootstrap_difference(
                    values_a,
                    values_b,
                    seed=_derived_seed(seed, f"{variant_a}|{variant_b}", metric),
                    resamples=bootstrap_resamples,
                )
                comparisons.append(
                    Comparison(
                        metric=metric,
                        variant_a=variant_a,
                        variant_b=variant_b,
                        difference=_mean(values_a) - _mean(values_b),
                        interval_low=interval_low,
                        interval_high=interval_high,
                        significant=interval_low > 0 or interval_high < 0,
                    )
                )
    return tuple(comparisons)


def build_evaluation_report(
    run: EvalRun,
    results: Sequence[QueryResult],
    *,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> EvaluationReport:
    """Aggregate persisted query results into quality and latency summaries."""
    if run.state is not EvalRunState.COMPLETED:
        raise ValueError(f"cannot report an evaluation run in state {run.state.value!r}")
    if not results:
        raise ValueError("cannot report an evaluation run without query results")
    if len(results) != run.progress.total_queries:
        raise ValueError(
            "persisted result count does not match the completed run: "
            f"results={len(results)}, expected={run.progress.total_queries}"
        )

    metric_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    # Comparisons need each score kept against its query so the two variants in a pair
    # can be resampled together; the flat lists above cannot preserve that alignment.
    paired_values: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    latency_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for result in results:
        if result.run_id != run.id:
            raise ValueError(f"query {result.query_id!r} belongs to a different evaluation run")
        if result.variant not in run.spec.variants:
            raise ValueError(f"query {result.query_id!r} has unexpected variant {result.variant!r}")
        for metric in RETRIEVAL_METRIC_NAMES:
            try:
                value = result.deterministic_scores[metric]
            except KeyError as error:
                raise ValueError(
                    f"query {result.query_id!r} is missing metric {metric!r}"
                ) from error
            if result.query_id in paired_values[(result.variant, metric)]:
                raise ValueError(
                    f"query {result.query_id!r} has duplicate results for "
                    f"variant {result.variant!r}"
                )
            metric_values[(result.variant, metric)].append(value)
            paired_values[(result.variant, metric)][result.query_id] = value
        for timing in result.stage_timings:
            latency_values[(result.variant, timing.stage)].append(timing.duration_ms)

    expected_per_variant = run.progress.total_queries // len(run.spec.variants)
    metrics: list[MetricSummary] = []
    for variant in run.spec.variants:
        for metric in RETRIEVAL_METRIC_NAMES:
            values = metric_values[(variant, metric)]
            if len(values) != expected_per_variant:
                raise ValueError(
                    f"variant {variant!r} has {len(values)} results; "
                    f"expected {expected_per_variant}"
                )
            ordered_values = sorted(values)
            interval_low, interval_high = _bootstrap_mean_interval(
                ordered_values,
                seed=_derived_seed(run.spec.seed, variant, metric),
                resamples=bootstrap_resamples,
            )
            metrics.append(
                MetricSummary(
                    metric=metric,
                    variant=variant,
                    mean=_mean(ordered_values),
                    interval_low=interval_low,
                    interval_high=interval_high,
                    query_count=len(ordered_values),
                )
            )

    latencies = tuple(
        summary
        for variant in run.spec.variants
        for summary in (
            LatencySummary(
                variant=variant,
                stage=stage,
                p50_ms=_percentile(values, 0.50),
                p95_ms=_percentile(values, 0.95),
                sample_count=len(values),
            )
            for (result_variant, stage), values in sorted(latency_values.items())
            if result_variant == variant
        )
    )
    comparisons = (
        build_variant_comparisons(
            run.spec.variants,
            paired_values,
            seed=run.spec.seed,
            bootstrap_resamples=bootstrap_resamples,
        )
        if len(run.spec.variants) > 1
        else ()
    )
    return EvaluationReport(
        run=run,
        metrics=tuple(metrics),
        latencies=latencies,
        comparisons=comparisons,
    )


def render_markdown_report(report: EvaluationReport) -> str:
    """Render a stable Markdown report suitable for versioned artifacts."""
    run = report.run
    lines = [
        f"# Retrieval evaluation `{run.id}`",
        "",
        f"- Dataset: `{run.spec.dataset}` (`{run.spec.split}`)",
        f"- Variants: {', '.join(f'`{variant}`' for variant in run.spec.variants)}",
        f"- Seed: `{run.spec.seed}`",
        f"- Results: `{run.progress.completed_queries}`",
        "- Indexes: "
        + ", ".join(
            f"`{variant}`=`{fingerprint}`"
            for variant, fingerprint in sorted(run.index_fingerprints.items())
        ),
        "",
        "## Retrieval quality",
        "",
        "| Variant | Metric | Mean | 95% CI | Queries |",
        "|---|---|---:|---:|---:|",
    ]
    lines.extend(
        "| "
        f"{summary.variant} | {_METRIC_LABELS.get(summary.metric, summary.metric)} | "
        f"{summary.mean:.4f} | [{summary.interval_low:.4f}, {summary.interval_high:.4f}] | "
        f"{summary.query_count} |"
        for summary in report.metrics
    )
    lines.extend(
        [
            "",
            "## Stage latency",
            "",
            "| Variant | Stage | P50 (ms) | P95 (ms) | Samples |",
            "|---|---|---:|---:|---:|",
        ]
    )
    if report.latencies:
        lines.extend(
            f"| {summary.variant} | {summary.stage} | {summary.p50_ms:.2f} | "
            f"{summary.p95_ms:.2f} | {summary.sample_count} |"
            for summary in report.latencies
        )
    else:
        lines.append("| — | — | — | — | 0 |")

    if report.comparisons:
        lines.extend(
            [
                "",
                "## Variant comparisons",
                "",
                "Paired bootstrap over queries. A difference is significant only when its",
                "95% interval excludes zero.",
                "",
                "| Variant A | Variant B | Metric | A - B | 95% CI | Significant |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        lines.extend(
            f"| {comparison.variant_a} | {comparison.variant_b} | "
            f"{_METRIC_LABELS.get(comparison.metric, comparison.metric)} | "
            f"{comparison.difference:+.4f} | "
            f"[{comparison.interval_low:+.4f}, {comparison.interval_high:+.4f}] | "
            f"{'yes' if comparison.significant else 'no'} |"
            for comparison in report.comparisons
        )
    return "\n".join(lines) + "\n"


def write_report_files(report: EvaluationReport, directory: Path) -> tuple[Path, Path]:
    """Archive a rendered run under ``directory/<run_id>/`` and return the written paths.

    Reports are kept as files as well as rows so a run stays reviewable in a diff and
    survives the database it was computed from.
    """
    run_directory = directory / str(report.run.id)
    run_directory.mkdir(parents=True, exist_ok=True)
    markdown_path = run_directory / "report.md"
    json_path = run_directory / "report.json"
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path

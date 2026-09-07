"""Regression gating of a completed evaluation run against a committed baseline."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ragops.config import ThresholdCatalog
from ragops.contracts import (
    BaselineDocument,
    EvaluationReport,
    GateMetricResult,
    GateResult,
)

# Absolute drops are compared with a small slack so a regression exactly equal to
# the declared tolerance passes despite floating-point representation error.
_TOLERANCE_EPSILON = 1e-9


def build_baseline(
    report: EvaluationReport, *, variant_hashes: Mapping[str, str]
) -> BaselineDocument:
    """Capture a completed run's metrics as a committable baseline document."""
    metrics: dict[str, dict[str, float]] = {}
    for summary in report.metrics:
        metrics.setdefault(summary.variant, {})[summary.metric] = summary.mean
    return BaselineDocument(
        dataset=report.run.spec.dataset,
        split=report.run.spec.split,
        run_id=report.run.id,
        git_commit=report.run.git_commit,
        recorded_at=datetime.now(UTC),
        variant_hashes=dict(variant_hashes),
        metrics=metrics,
    )


def read_baseline(path: Path) -> BaselineDocument:
    """Load and validate a committed baseline file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"baseline file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"baseline file is not valid JSON: {path}") from error
    return BaselineDocument.model_validate(payload)


def write_baseline(baseline: BaselineDocument, path: Path) -> None:
    """Write a baseline as stable, diff-friendly JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(baseline.model_dump_json())
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate_gate(
    report: EvaluationReport,
    baseline: BaselineDocument,
    thresholds: ThresholdCatalog,
) -> GateResult:
    """Compare a completed run to its baseline and report every threshold breach.

    Only metrics recorded in the baseline that also declare a tolerance are gated.
    A variant present in the run but absent from the baseline is new and ungated;
    a baselined variant or metric missing from the run makes the comparison
    incomplete and is rejected rather than silently passed.
    """
    run_spec = report.run.spec
    if baseline.dataset != run_spec.dataset:
        raise ValueError(
            "baseline dataset does not match the run: "
            f"baseline={baseline.dataset!r}, run={run_spec.dataset!r}"
        )
    if baseline.split != run_spec.split:
        raise ValueError(
            "baseline split does not match the run: "
            f"baseline={baseline.split!r}, run={run_spec.split!r}"
        )

    observed = {(summary.variant, summary.metric): summary.mean for summary in report.metrics}
    results: list[GateMetricResult] = []
    for variant in sorted(baseline.metrics):
        for metric in sorted(baseline.metrics[variant]):
            threshold = thresholds.metrics.get(metric)
            if threshold is None:
                continue
            try:
                observed_value = observed[(variant, metric)]
            except KeyError as error:
                raise ValueError(
                    f"run {report.run.id} does not report baselined metric "
                    f"{metric!r} for variant {variant!r}"
                ) from error
            tolerance = threshold.maximum_absolute_drop
            baseline_value = baseline.metrics[variant][metric]
            drop = baseline_value - observed_value
            results.append(
                GateMetricResult(
                    variant=variant,
                    metric=metric,
                    baseline=baseline_value,
                    observed=observed_value,
                    tolerance=tolerance,
                    breached=drop - tolerance > _TOLERANCE_EPSILON,
                )
            )

    if not results:
        raise ValueError("baseline and thresholds share no gated metrics")
    return GateResult(
        passed=not any(result.breached for result in results),
        dataset=run_spec.dataset,
        run_id=report.run.id,
        baseline_run_id=baseline.run_id,
        metrics=tuple(results),
    )


def render_gate_report(result: GateResult) -> str:
    """Render the per-metric diff a failing build should print."""
    status = "PASSED" if result.passed else "FAILED"
    lines = [
        f"# Regression gate {status}",
        "",
        f"- Dataset: `{result.dataset}`",
        f"- Run: `{result.run_id}`",
        f"- Baseline run: `{result.baseline_run_id}`",
        "",
        "| Variant | Metric | Baseline | Observed | Delta | Tolerance | Status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    lines.extend(
        f"| {metric.variant} | {metric.metric} | {metric.baseline:.4f} | "
        f"{metric.observed:.4f} | {metric.delta:+.4f} | {metric.tolerance:.4f} | "
        f"{'BREACH' if metric.breached else 'ok'} |"
        for metric in result.metrics
    )
    return "\n".join(lines) + "\n"

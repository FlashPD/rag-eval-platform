"""Regression gating of a completed evaluation run against a committed baseline."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ragops.config import ThresholdCatalog
from ragops.contracts import (
    BaselineDocument,
    EvalRunSpec,
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
        sample_size=report.run.spec.sample_size,
        seed=report.run.spec.seed,
        generation_sample_size=report.run.spec.generation_sample_size,
        generation_variants=report.run.spec.generation_variants,
        generator_profile=report.run.spec.generator_profile,
        judge_profiles=report.run.spec.judge_profiles,
        generation_prompt_version=report.run.spec.generation_prompt_version,
        judge_prompt_version=report.run.spec.judge_prompt_version,
        run_id=report.run.id,
        git_commit=report.run.git_commit,
        recorded_at=datetime.now(UTC),
        variant_hashes=dict(variant_hashes),
        index_fingerprints=report.run.index_fingerprints,
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
    try:
        return BaselineDocument.model_validate(payload)
    except ValidationError as error:
        # A baseline written by an older schema fails here. Name the file, because
        # the fix is to regenerate it with `ragops eval baseline`, not to debug a
        # traceback in CI output.
        raise ValueError(f"baseline file does not match the current schema: {path}\n{error}") from (
            error
        )


def write_baseline(baseline: BaselineDocument, path: Path) -> None:
    """Write a baseline as stable, diff-friendly JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(baseline.model_dump_json())
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_comparable(baseline: BaselineDocument, run_spec: EvalRunSpec) -> None:
    """Reject a comparison whose two sides did not evaluate the same benchmark.

    A gate only means something when the baseline and the run scored the same
    queries. Differences in dataset, split, or query sample produce deltas that
    measure the benchmark rather than the change under review, which is worse
    than no gate at all because it looks authoritative.
    """
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
    if baseline.sample_size != run_spec.sample_size:
        raise ValueError(
            "baseline sample size does not match the run: "
            f"baseline={baseline.sample_size}, run={run_spec.sample_size}; "
            "a full-dataset run and a sampled run are different benchmarks"
        )
    # The seed only chooses which queries are sampled. A run with no sample size
    # evaluates every query, so its seed cannot change the set being compared.
    if run_spec.sample_size is not None and baseline.seed != run_spec.seed:
        raise ValueError(
            "baseline seed does not match the run: "
            f"baseline={baseline.seed}, run={run_spec.seed}; "
            "a different seed samples a different set of queries"
        )
    for label, baseline_value, run_value in (
        (
            "generation sample size",
            baseline.generation_sample_size,
            run_spec.generation_sample_size,
        ),
        ("generation variants", baseline.generation_variants, run_spec.generation_variants),
        ("generator profile", baseline.generator_profile, run_spec.generator_profile),
        ("judge profiles", baseline.judge_profiles, run_spec.judge_profiles),
        (
            "generation prompt version",
            baseline.generation_prompt_version,
            run_spec.generation_prompt_version,
        ),
        ("judge prompt version", baseline.judge_prompt_version, run_spec.judge_prompt_version),
    ):
        if baseline_value != run_value:
            raise ValueError(
                f"baseline {label} does not match the run: "
                f"baseline={baseline_value!r}, run={run_value!r}"
            )


def _ensure_index_fingerprints_match(baseline: BaselineDocument, report: EvaluationReport) -> None:
    observed = report.run.index_fingerprints
    mismatches = {
        variant: (fingerprint, observed.get(variant))
        for variant, fingerprint in baseline.index_fingerprints.items()
        if observed.get(variant) != fingerprint
    }
    if mismatches:
        raise ValueError(
            "baseline index fingerprints do not match the run: "
            f"mismatches={mismatches}; "
            "re-ingestion or index configuration changes require a new reviewed baseline"
        )


def evaluate_gate(
    report: EvaluationReport,
    baseline: BaselineDocument,
    thresholds: ThresholdCatalog,
) -> GateResult:
    """Compare a completed run to its baseline and report every threshold breach.

    The run and the baseline must describe the same benchmark; see
    ``_ensure_comparable``. Only metrics recorded in the baseline that also declare
    a tolerance are gated. A variant present in the run but absent from the baseline
    is new and ungated; a baselined variant or metric missing from the run makes the
    comparison incomplete and is rejected rather than silently passed.
    """
    run_spec = report.run.spec
    _ensure_comparable(baseline, run_spec)
    _ensure_index_fingerprints_match(baseline, report)

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

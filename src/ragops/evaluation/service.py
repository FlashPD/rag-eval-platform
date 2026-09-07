"""Application service for creating, executing, and gating evaluation runs."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, ThresholdCatalog, VariantRegistry
from ragops.contracts import (
    BaselineDocument,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    EvaluationReport,
    GateResult,
)
from ragops.evaluation.gate import build_baseline, evaluate_gate, read_baseline
from ragops.evaluation.reporting import build_evaluation_report
from ragops.evaluation.repository import SqlAlchemyEvaluationDataRepository
from ragops.evaluation.runner import RetrievalEvaluationRunner
from ragops.persistence.repositories import SqlAlchemyEvaluationRunRepository
from ragops.retrieval.pipeline import SearchExecutor


async def run_retrieval_evaluation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    search: SearchExecutor,
    datasets: DatasetCatalog,
    variants: VariantRegistry,
    spec: EvalRunSpec,
    git_commit: str | None = None,
    image_digest: str | None = None,
) -> EvalRun:
    """Create, queue, and execute one retrieval-only evaluation run."""
    if spec.generation_enabled:
        raise ValueError("retrieval evaluation cannot enable generation")
    manifest = datasets.get(spec.dataset)
    if spec.split != manifest.default_split:
        raise ValueError(f"dataset {spec.dataset!r} does not serve split {spec.split!r}")
    variant_hashes = {
        variant_name: variants.get(variant_name).configuration_hash
        for variant_name in spec.variants
    }
    async with sessions.begin() as session:
        runs = SqlAlchemyEvaluationRunRepository(session)
        run = await runs.create(
            spec,
            variant_hashes=variant_hashes,
            git_commit=git_commit,
            image_digest=image_digest,
        )
        run = await runs.set_state(run.id, EvalRunState.QUEUED)

    return await RetrievalEvaluationRunner(
        sessions,
        search=search,
        datasets=datasets,
        variants=variants,
    ).run(run.id)


async def get_evaluation_report(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> EvaluationReport:
    """Load a completed run and aggregate its persisted results."""
    report, _ = await _load_report_and_hashes(sessions, run_id)
    return report


async def _load_report_and_hashes(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> tuple[EvaluationReport, dict[str, str]]:
    async with sessions() as session:
        runs = SqlAlchemyEvaluationRunRepository(session)
        run = await runs.get(run_id)
        if run is None:
            raise KeyError(f"evaluation run not found: {run_id}")
        variant_hashes = await runs.get_variant_hashes(run_id)
        results = await SqlAlchemyEvaluationDataRepository(session).load_results(run_id)
    return build_evaluation_report(run, results), variant_hashes


async def build_run_baseline(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> BaselineDocument:
    """Capture a completed run as the baseline document to commit for review."""
    report, variant_hashes = await _load_report_and_hashes(sessions, run_id)
    return build_baseline(report, variant_hashes=variant_hashes)


async def gate_evaluation_run(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    *,
    baseline_path: Path,
    thresholds: ThresholdCatalog,
) -> GateResult:
    """Compare a completed run against the committed baseline for its dataset."""
    report, _ = await _load_report_and_hashes(sessions, run_id)
    return evaluate_gate(report, read_baseline(baseline_path), thresholds)

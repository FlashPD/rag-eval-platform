"""Application service for creating, executing, and gating evaluation runs."""

from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, ThresholdCatalog, VariantRegistry
from ragops.contracts import (
    EVALUATION_JOB_KIND,
    BaselineDocument,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    EvaluationReport,
    GateResult,
    JobSpec,
)
from ragops.evaluation.gate import build_baseline, evaluate_gate, read_baseline
from ragops.evaluation.reporting import build_evaluation_report
from ragops.evaluation.repository import SqlAlchemyEvaluationDataRepository
from ragops.evaluation.runner import RetrievalEvaluationRunner
from ragops.persistence.job_queue import SqlAlchemyJobQueue
from ragops.persistence.repositories import SqlAlchemyEvaluationRunRepository
from ragops.retrieval.pipeline import SearchExecutor


def _resolve_variant_hashes(
    spec: EvalRunSpec, datasets: DatasetCatalog, variants: VariantRegistry
) -> dict[str, str]:
    """Validate a spec against the configured catalogs and pin its variant hashes."""
    if spec.generation_enabled:
        raise ValueError("retrieval evaluation cannot enable generation")
    manifest = datasets.get(spec.dataset)
    if spec.split != manifest.default_split:
        raise ValueError(f"dataset {spec.dataset!r} does not serve split {spec.split!r}")
    return {
        variant_name: variants.get(variant_name).configuration_hash
        for variant_name in spec.variants
    }


async def create_retrieval_evaluation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    datasets: DatasetCatalog,
    variants: VariantRegistry,
    spec: EvalRunSpec,
    git_commit: str | None = None,
    image_digest: str | None = None,
    enqueue: bool = False,
) -> EvalRun:
    """Create a queued retrieval evaluation run, optionally with a job to execute it.

    The run row and its job are written in one transaction. Splitting them would
    allow a crash in between to leave a queued run that no worker will ever claim.
    """
    variant_hashes = _resolve_variant_hashes(spec, datasets, variants)
    async with sessions.begin() as session:
        runs = SqlAlchemyEvaluationRunRepository(session)
        run = await runs.create(
            spec,
            variant_hashes=variant_hashes,
            git_commit=git_commit,
            image_digest=image_digest,
        )
        run = await runs.set_state(run.id, EvalRunState.QUEUED)
        if enqueue:
            await SqlAlchemyJobQueue(session).enqueue(
                JobSpec(
                    kind=EVALUATION_JOB_KIND,
                    payload={"run_id": str(run.id)},
                    # Keyed on the run, so a retried enqueue for the same run cannot
                    # put a second worker on the same work.
                    idempotency_key=f"{EVALUATION_JOB_KIND}:{run.id}",
                )
            )
    return run


async def submit_retrieval_evaluation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    datasets: DatasetCatalog,
    variants: VariantRegistry,
    spec: EvalRunSpec,
    git_commit: str | None = None,
    image_digest: str | None = None,
) -> EvalRun:
    """Queue a retrieval evaluation for a worker to execute, without running it here."""
    return await create_retrieval_evaluation(
        sessions,
        datasets=datasets,
        variants=variants,
        spec=spec,
        git_commit=git_commit,
        image_digest=image_digest,
        enqueue=True,
    )


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
    """Create, queue, and execute one retrieval-only evaluation run in this process."""
    run = await create_retrieval_evaluation(
        sessions,
        datasets=datasets,
        variants=variants,
        spec=spec,
        git_commit=git_commit,
        image_digest=image_digest,
    )
    return await RetrievalEvaluationRunner(
        sessions,
        search=search,
        datasets=datasets,
        variants=variants,
    ).run(run.id)


async def get_evaluation_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> EvalRun:
    """Load one evaluation run record."""
    async with sessions() as session:
        run = await SqlAlchemyEvaluationRunRepository(session).get(run_id)
    if run is None:
        raise KeyError(f"evaluation run not found: {run_id}")
    return run


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


class EvaluationService(Protocol):
    """The evaluation operations the HTTP API depends on."""

    async def submit(self, spec: EvalRunSpec) -> EvalRun: ...

    async def get(self, run_id: UUID) -> EvalRun: ...


class DatabaseEvaluationService:
    """Bind the evaluation services to one database and configuration bundle."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        datasets: DatasetCatalog,
        variants: VariantRegistry,
        git_commit: str | None = None,
        image_digest: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._datasets = datasets
        self._variants = variants
        self._git_commit = git_commit
        self._image_digest = image_digest

    async def submit(self, spec: EvalRunSpec) -> EvalRun:
        return await submit_retrieval_evaluation(
            self._sessions,
            datasets=self._datasets,
            variants=self._variants,
            spec=spec,
            git_commit=self._git_commit,
            image_digest=self._image_digest,
        )

    async def get(self, run_id: UUID) -> EvalRun:
        return await get_evaluation_run(self._sessions, run_id)

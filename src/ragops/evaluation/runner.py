"""Resumable retrieval, generation, and judge benchmark execution."""

import hashlib
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, VariantRegistry
from ragops.contracts import (
    AnswerRequest,
    EvalRun,
    EvalRunState,
    EvaluationQuery,
    QueryResult,
    SearchRequest,
)
from ragops.evaluation.answer_metrics import (
    compute_answer_metrics,
    compute_scifact_rationale_precision,
    scifact_gold_label,
)
from ragops.evaluation.judging import VersionedJudgePromptRenderer
from ragops.evaluation.repository import SqlAlchemyEvaluationDataRepository
from ragops.evaluation.retrieval_metrics import compute_retrieval_metrics
from ragops.generation.service import AnswerService
from ragops.persistence.repositories import SqlAlchemyEvaluationRunRepository
from ragops.protocols import Judge
from ragops.retrieval.pipeline import SearchExecutor
from ragops.telemetry import record_judge_verdict

EVALUATION_RETRIEVAL_DEPTH = 100


def select_evaluation_queries(
    queries: Sequence[EvaluationQuery], *, sample_size: int | None, seed: int
) -> tuple[EvaluationQuery, ...]:
    """Select a stable sample independent of database and input ordering."""
    ordered = sorted(queries, key=lambda query: query.external_id)
    if sample_size is None:
        return tuple(ordered)
    if sample_size > len(ordered):
        raise ValueError(f"sample size {sample_size} exceeds the {len(ordered)} available queries")

    def sample_key(query: EvaluationQuery) -> tuple[bytes, str]:
        digest = hashlib.sha256(f"{seed}:{query.external_id}".encode()).digest()
        return digest, query.external_id

    selected = sorted(ordered, key=sample_key)[:sample_size]
    return tuple(sorted(selected, key=lambda query: query.external_id))


class RetrievalEvaluationRunner:
    """Execute and persist every query/variant work item in an evaluation run."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        search: SearchExecutor,
        datasets: DatasetCatalog,
        variants: VariantRegistry,
        answer_service: AnswerService | None = None,
        judge_renderer: VersionedJudgePromptRenderer | None = None,
        judges: Mapping[str, Judge] | None = None,
    ) -> None:
        self._sessions = sessions
        self._search = search
        self._datasets = datasets
        self._variants = variants
        self._answer_service = answer_service
        self._judge_renderer = judge_renderer
        self._judges = dict(judges or {})

    async def run(self, run_id: UUID) -> EvalRun:
        run = await self._get_run(run_id)
        if run.state in {
            EvalRunState.COMPLETED,
            EvalRunState.FAILED,
            EvalRunState.CANCELLED,
        }:
            return run
        if run.state is EvalRunState.CREATED:
            raise ValueError("evaluation run must be queued before execution")
        if run.spec.generation_enabled and self._answer_service is None:
            raise ValueError("generation-enabled evaluation requires an answer service")
        missing_judges = set(run.spec.judge_profiles) - self._judges.keys()
        if missing_judges or (run.spec.judge_profiles and self._judge_renderer is None):
            raise ValueError(f"evaluation judge profiles are unavailable: {sorted(missing_judges)}")

        try:
            return await self._run_retrieval(run)
        except Exception:
            await self._mark_failed(run_id)
            raise

    async def _run_retrieval(self, run: EvalRun) -> EvalRun:
        if run.state is EvalRunState.QUEUED:
            run = await self._set_state(run.id, EvalRunState.PREPARING)

        manifest = self._datasets.get(run.spec.dataset)
        if run.spec.split != manifest.default_split:
            raise ValueError(
                f"retrieval serves split {manifest.default_split!r}, not {run.spec.split!r}"
            )
        queries = await self._load_queries(
            dataset_name=run.spec.dataset,
            dataset_version=manifest.version,
            split=run.spec.split,
        )
        queries = select_evaluation_queries(
            queries,
            sample_size=run.spec.sample_size,
            seed=run.spec.seed,
        )
        if not queries:
            raise ValueError("evaluation dataset contains no queries")

        expected_hashes = await self._get_variant_hashes(run.id)
        expected_index_fingerprints = dict(run.index_fingerprints)
        current_hashes = {
            variant_name: self._variants.get(variant_name).configuration_hash
            for variant_name in run.spec.variants
        }
        if expected_hashes != current_hashes:
            raise ValueError(
                "evaluation variant configuration changed after run creation: "
                f"expected={expected_hashes}, current={current_hashes}"
            )

        total_work = len(queries) * len(run.spec.variants)
        if run.state is EvalRunState.PREPARING:
            run = await self._set_progress(
                run.id,
                completed_queries=run.progress.completed_queries,
                total_queries=total_work,
            )
            run = await self._set_state(run.id, EvalRunState.RETRIEVING)
        elif run.state is EvalRunState.RETRIEVING:
            run = await self._set_progress(
                run.id,
                completed_queries=run.progress.completed_queries,
                total_queries=total_work,
            )

        if run.state is EvalRunState.RETRIEVING:
            completed = await self._completed_work(run.id)
            for query in queries:
                current = await self._get_run(run.id)
                if current.state is EvalRunState.CANCELLED:
                    return current
                for variant_name in run.spec.variants:
                    if (query.id, variant_name) in completed:
                        continue
                    await self._evaluate_one(
                        run.id,
                        query,
                        dataset_name=run.spec.dataset,
                        variant_name=variant_name,
                        expected_hashes=expected_hashes,
                        expected_index_fingerprints=expected_index_fingerprints,
                    )
            run = await self._get_run(run.id)
            if run.state is EvalRunState.CANCELLED:
                return run
            if run.progress.completed_queries != total_work:
                raise ValueError(
                    "evaluation result count does not match expected work: "
                    f"completed={run.progress.completed_queries}, expected={total_work}"
                )
            missing_index_fingerprints = set(run.spec.variants) - run.index_fingerprints.keys()
            if missing_index_fingerprints:
                missing = ", ".join(sorted(missing_index_fingerprints))
                raise ValueError(f"evaluation did not record index fingerprints for: {missing}")
            run = await self._set_state(
                run.id,
                EvalRunState.GENERATING if run.spec.generation_enabled else EvalRunState.SCORING,
            )

        generation_queries = select_evaluation_queries(
            queries,
            sample_size=run.spec.generation_sample_size,
            seed=run.spec.seed,
        )
        generation_variants = run.spec.generation_variants or run.spec.variants
        if run.state is EvalRunState.GENERATING:
            assert self._answer_service is not None
            persisted = {
                (result.query_id, result.variant): result
                for result in await self._load_results(run.id)
            }
            for query in generation_queries:
                for variant_name in generation_variants:
                    result = persisted[(query.external_id, variant_name)]
                    if result.answer is not None:
                        continue
                    current = await self._get_run(run.id)
                    if current.state is EvalRunState.CANCELLED:
                        return current
                    answer = await self._answer_service.answer(
                        AnswerRequest(
                            query=query.text,
                            dataset=run.spec.dataset,
                            variant=variant_name,
                            generator_profile=run.spec.generator_profile or "default",
                            prompt_version=run.spec.generation_prompt_version,
                        )
                    )
                    scores = compute_answer_metrics(answer, query.qrels).as_score_dict()
                    gold_label: str | None = None
                    if run.spec.dataset == "scifact":
                        gold_label = scifact_gold_label(query.metadata).value
                        scores["scifact_label_accuracy"] = float(
                            answer.verification_label is not None
                            and answer.verification_label.value == gold_label
                        )
                        scores["scifact_rationale_precision"] = compute_scifact_rationale_precision(
                            answer, query.metadata
                        )
                    async with self._sessions.begin() as session:
                        await SqlAlchemyEvaluationDataRepository(session).update_answer(
                            run_id=run.id,
                            query_id=query.id,
                            variant=variant_name,
                            answer=answer,
                            deterministic_scores=scores,
                            scifact_gold_label=gold_label,
                        )
            run = await self._set_state(
                run.id,
                EvalRunState.JUDGING if run.spec.judge_profiles else EvalRunState.SCORING,
            )

        if run.state is EvalRunState.JUDGING:
            assert self._judge_renderer is not None
            persisted = {
                (result.query_id, result.variant): result
                for result in await self._load_results(run.id)
            }
            for query in generation_queries:
                for variant_name in generation_variants:
                    result = persisted[(query.external_id, variant_name)]
                    if result.answer is None:
                        raise ValueError("judge stage found a missing generated answer")
                    missing_profiles = [
                        profile
                        for profile in run.spec.judge_profiles
                        if profile not in result.judge_records
                    ]
                    if not missing_profiles:
                        continue
                    request = self._judge_renderer.render_for_query(query.text, result.answer)
                    verdicts = {
                        profile: await self._judges[profile].judge(request)
                        for profile in missing_profiles
                    }
                    for profile, verdict in verdicts.items():
                        record_judge_verdict(profile=profile, verdict=verdict, source="offline")
                    async with self._sessions.begin() as session:
                        await SqlAlchemyEvaluationDataRepository(session).update_judges(
                            run_id=run.id,
                            query_id=query.id,
                            variant=variant_name,
                            verdicts=verdicts,
                        )
            run = await self._set_state(run.id, EvalRunState.SCORING)

        if run.state is EvalRunState.SCORING:
            run = await self._set_state(run.id, EvalRunState.COMPLETED)
        return run

    async def _evaluate_one(
        self,
        run_id: UUID,
        query: EvaluationQuery,
        dataset_name: str,
        variant_name: str,
        expected_hashes: dict[str, str],
        expected_index_fingerprints: dict[str, str],
    ) -> None:
        response = await self._search.search(
            SearchRequest(
                query=query.text,
                dataset=dataset_name,
                variant=variant_name,
                k=EVALUATION_RETRIEVAL_DEPTH,
            )
        )
        if response.variant_hash != expected_hashes[variant_name]:
            raise ValueError(f"retrieval response has an unexpected hash for {variant_name}")
        expected_fingerprint = expected_index_fingerprints.get(variant_name)
        if expected_fingerprint is None:
            await self._pin_index_fingerprint(
                run_id,
                variant=variant_name,
                fingerprint=response.index_fingerprint,
            )
            expected_index_fingerprints[variant_name] = response.index_fingerprint
        elif response.index_fingerprint != expected_fingerprint:
            raise ValueError(
                f"retrieval response used a different index for {variant_name}: "
                f"expected={expected_fingerprint}, observed={response.index_fingerprint}"
            )
        ranked_document_ids = tuple(hit.document_id for hit in response.hits)
        scores = compute_retrieval_metrics(ranked_document_ids, query.qrels)
        result = QueryResult(
            run_id=run_id,
            variant=variant_name,
            query_id=query.external_id,
            ranked_document_ids=ranked_document_ids,
            stage_timings=response.timings,
            deterministic_scores=scores.as_score_dict(),
        )
        async with self._sessions.begin() as session:
            await SqlAlchemyEvaluationDataRepository(session).add_result(result, query_id=query.id)

    async def _get_run(self, run_id: UUID) -> EvalRun:
        async with self._sessions() as session:
            run = await SqlAlchemyEvaluationRunRepository(session).get(run_id)
        if run is None:
            raise KeyError(f"evaluation run not found: {run_id}")
        return run

    async def _get_variant_hashes(self, run_id: UUID) -> dict[str, str]:
        async with self._sessions() as session:
            return await SqlAlchemyEvaluationRunRepository(session).get_variant_hashes(run_id)

    async def _pin_index_fingerprint(self, run_id: UUID, *, variant: str, fingerprint: str) -> None:
        async with self._sessions.begin() as session:
            await SqlAlchemyEvaluationRunRepository(session).pin_index_fingerprint(
                run_id,
                variant=variant,
                fingerprint=fingerprint,
            )

    async def _load_queries(
        self, *, dataset_name: str, dataset_version: str, split: str
    ) -> tuple[EvaluationQuery, ...]:
        async with self._sessions() as session:
            return await SqlAlchemyEvaluationDataRepository(session).load_queries(
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                split=split,
            )

    async def _completed_work(self, run_id: UUID) -> set[tuple[UUID, str]]:
        async with self._sessions() as session:
            return await SqlAlchemyEvaluationDataRepository(session).completed_work(run_id)

    async def _load_results(self, run_id: UUID) -> tuple[QueryResult, ...]:
        async with self._sessions() as session:
            return await SqlAlchemyEvaluationDataRepository(session).load_results(run_id)

    async def _set_state(self, run_id: UUID, state: EvalRunState) -> EvalRun:
        async with self._sessions.begin() as session:
            return await SqlAlchemyEvaluationRunRepository(session).set_state(run_id, state)

    async def _set_progress(
        self, run_id: UUID, *, completed_queries: int, total_queries: int
    ) -> EvalRun:
        async with self._sessions.begin() as session:
            return await SqlAlchemyEvaluationRunRepository(session).set_progress(
                run_id,
                completed_queries=completed_queries,
                total_queries=total_queries,
            )

    async def _mark_failed(self, run_id: UUID) -> None:
        run = await self._get_run(run_id)
        if run.state not in {
            EvalRunState.COMPLETED,
            EvalRunState.FAILED,
            EvalRunState.CANCELLED,
        }:
            await self._set_state(run_id, EvalRunState.FAILED)

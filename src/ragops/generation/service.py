"""Provider-neutral orchestration for structured, cited answers."""

import logging
from collections.abc import Callable, Mapping, Sequence
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from opentelemetry.trace import get_tracer

from ragops.contracts import (
    AnswerRequest,
    AnswerResponse,
    Confidence,
    GenerationOutcome,
    Passage,
    SearchRequest,
)
from ragops.generation.errors import GenerationFailure
from ragops.generation.prompting import VersionedAnswerPromptRenderer
from ragops.generation.validation import validate_citations
from ragops.protocols import Answerer, Generator
from ragops.retrieval.pipeline import SearchExecutor
from ragops.telemetry import record_generation_answer

LOGGER = logging.getLogger(__name__)


class OnlineSampler(Protocol):
    async def submit(self, *, query: str, answer: AnswerResponse) -> bool: ...


class AnswerService(Protocol):
    async def answer(self, request: AnswerRequest) -> AnswerResponse: ...


def _new_trace_id() -> str:
    return uuid4().hex


class CitedAnswerer:
    """Render, generate, validate, and classify one answer attempt."""

    def __init__(
        self,
        *,
        generator: Generator,
        prompt_renderer: VersionedAnswerPromptRenderer,
        trace_id_factory: Callable[[], str] = _new_trace_id,
    ) -> None:
        if not generator.provider.strip() or not generator.model.strip():
            raise ValueError("generator provider and model cannot be blank")
        self._generator = generator
        self._prompt_renderer = prompt_renderer
        self._trace_id_factory = trace_id_factory
        self._tracer = get_tracer(__name__)

    async def answer(self, query: str, contexts: Sequence[Passage]) -> AnswerResponse:
        ordered_contexts = tuple(
            sorted(contexts, key=lambda passage: (passage.retrieval_rank, passage.local_id))
        )
        with self._tracer.start_as_current_span("render_prompt"):
            request = self._prompt_renderer.render(
                query=query,
                contexts=ordered_contexts,
                trace_id=self._trace_id_factory(),
            )
        try:
            with self._tracer.start_as_current_span("generate") as span:
                span.set_attribute("gen_ai.system", self._generator.provider)
                span.set_attribute("gen_ai.request.model", self._generator.model)
                span.set_attribute("ragops.prompt.version", request.prompt_version)
                span.set_attribute("ragops.prompt.hash", request.rendered_prompt_hash)
                result = await self._generator.generate(request)
                span.set_attribute("gen_ai.response.model", result.model)
                span.set_attribute("gen_ai.usage.input_tokens", result.usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", result.usage.output_tokens)
                span.set_attribute("ragops.llm.cost_usd", float(result.usage.cost_usd))
                span.set_attribute("ragops.cache.hit", result.cache_hit)
        except GenerationFailure as error:
            return AnswerResponse(
                answer="",
                citations=(),
                abstained=False,
                confidence=Confidence.LOW,
                contexts=ordered_contexts,
                usage=error.usage,
                outcome=error.outcome,
                trace_id=request.trace_id,
                provider=self._generator.provider,
                model=self._generator.model,
                generator_configuration_hash=self._generator.configuration_hash,
                prompt_version=request.prompt_version,
                rendered_prompt_hash=request.rendered_prompt_hash,
                provider_request_id=error.provider_request_id,
                cache_hit=False,
                error=str(error),
            )

        if (
            result.provider != self._generator.provider
            or result.model != self._generator.model
            or result.generator_configuration_hash != self._generator.configuration_hash
        ):
            raise ValueError(
                "generator result provenance does not match its configured provider and model"
            )

        with self._tracer.start_as_current_span("validate_output"):
            citation_validation = validate_citations(result.output, ordered_contexts)
        if not citation_validation.valid:
            outcome = GenerationOutcome.CITATION_ERROR
        elif result.output.abstained:
            outcome = GenerationOutcome.ABSTAINED
        else:
            outcome = GenerationOutcome.OK
        return AnswerResponse(
            answer=result.output.answer,
            citations=result.output.citations,
            abstained=result.output.abstained,
            confidence=result.output.confidence,
            verification_label=result.output.verification_label,
            rationale_sentences=result.output.rationale_sentences,
            contexts=ordered_contexts,
            usage=result.usage,
            outcome=outcome,
            trace_id=request.trace_id,
            provider=result.provider,
            model=result.model,
            generator_configuration_hash=result.generator_configuration_hash,
            prompt_version=request.prompt_version,
            rendered_prompt_hash=request.rendered_prompt_hash,
            provider_request_id=result.provider_request_id,
            cache_hit=result.cache_hit,
            citation_validation=citation_validation,
        )


class RetrievalCitedAnswerService:
    """Retrieve top-ranked passages and pass their stable IDs to an answerer."""

    def __init__(
        self,
        *,
        search: SearchExecutor,
        answerers: Mapping[str, Answerer],
        prompt_version: str,
        context_count: int = 10,
        online_sampler: OnlineSampler | None = None,
    ) -> None:
        if not 1 <= context_count <= 100:
            raise ValueError("answer context count must be between 1 and 100")
        self._search = search
        if not answerers:
            raise ValueError("at least one answerer profile is required")
        self._answerers = dict(answerers)
        self._prompt_version = prompt_version
        self._context_count = context_count
        self._online_sampler = online_sampler

    async def answer(self, request: AnswerRequest) -> AnswerResponse:
        if request.prompt_version is not None and request.prompt_version != self._prompt_version:
            raise ValueError(
                f"answer service uses prompt {self._prompt_version!r}, "
                f"not {request.prompt_version!r}"
            )
        try:
            answerer = self._answerers[request.generator_profile]
        except KeyError as error:
            choices = ", ".join(sorted(self._answerers))
            raise KeyError(
                f"unknown generator profile {request.generator_profile!r}; "
                f"available profiles: {choices}"
            ) from error
        response = await self._search.search(
            SearchRequest(
                query=request.query,
                dataset=request.dataset,
                variant=request.variant,
                k=self._context_count,
            )
        )
        contexts = tuple(
            Passage(
                local_id=f"[{hit.rank}]",
                document_id=hit.document_id,
                title=hit.title,
                text=hit.text,
                retrieval_rank=hit.rank,
                retrieval_score=hit.score,
            )
            for hit in response.hits
        )
        started = perf_counter()
        answer = await answerer.answer(request.query, contexts)
        record_generation_answer(answer, duration_seconds=perf_counter() - started)
        if self._online_sampler is not None:
            try:
                await self._online_sampler.submit(query=request.query, answer=answer)
            except Exception:
                # Sampling is best-effort observability and must not turn a valid
                # user answer into a 500 when the queue is temporarily unavailable.
                LOGGER.exception("failed to enqueue online evaluation for %s", answer.trace_id)
        return answer


class DatasetRoutingAnswerService:
    """Select a prompt-specialized answer service without weakening the API contract."""

    def __init__(
        self,
        *,
        default: AnswerService,
        by_dataset: Mapping[str, AnswerService],
        by_prompt_version: Mapping[str, AnswerService] | None = None,
    ) -> None:
        self._default = default
        self._by_dataset = dict(by_dataset)
        self._by_prompt_version = dict(by_prompt_version or {})

    async def answer(self, request: AnswerRequest) -> AnswerResponse:
        if request.prompt_version is not None:
            try:
                return await self._by_prompt_version[request.prompt_version].answer(request)
            except KeyError as error:
                raise ValueError(
                    f"no answer service is configured for prompt {request.prompt_version!r}"
                ) from error
        return await self._by_dataset.get(request.dataset, self._default).answer(request)

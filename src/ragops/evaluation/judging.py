"""Versioned judge prompts, OpenAI execution, and immutable caching."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import openai
from openai import AsyncOpenAI
from openai.types.responses import ResponseUsage
from opentelemetry.trace import get_tracer
from pydantic import ValidationError

from ragops.config import LLMProfile, PricingTable
from ragops.contracts import (
    AnswerResponse,
    JudgeOutput,
    JudgeRequest,
    JudgeVerdict,
    Passage,
    TokenUsage,
)
from ragops.generation.errors import (
    GenerationProviderError,
    GenerationRefusalError,
    GenerationSchemaError,
    GenerationTimeoutError,
)
from ragops.protocols import Judge

_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class VersionedJudgePromptRenderer:
    prompt_root: Path = Path("prompts/judge")
    version: str = "judge-v1"
    system_prompt: str = field(init=False)

    def __post_init__(self) -> None:
        if _VERSION.fullmatch(self.version) is None:
            raise ValueError(f"invalid judge prompt version: {self.version!r}")
        path = self.prompt_root / self.version / "system.txt"
        try:
            prompt = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValueError(f"judge prompt version not found: {self.version!r}") from error
        if not prompt.strip():
            raise ValueError(f"judge system prompt is blank: {path}")
        object.__setattr__(self, "system_prompt", prompt)

    def render(self, answer: AnswerResponse) -> JudgeRequest:
        return self.render_values(
            query="(question supplied separately)",
            answer=answer.answer,
            abstained=answer.abstained,
            citations=answer.citations,
            contexts=answer.contexts,
            trace_id=answer.trace_id,
        )

    def render_values(
        self,
        *,
        query: str,
        answer: str,
        abstained: bool,
        citations: tuple[str, ...],
        contexts: tuple[Passage, ...],
        trace_id: str,
    ) -> JudgeRequest:
        root = ElementTree.Element("judge_input")
        question = ElementTree.SubElement(root, "question", trust="untrusted")
        question.text = query
        generated = ElementTree.SubElement(
            root,
            "answer",
            trust="untrusted",
            abstained=str(abstained).lower(),
            citations=",".join(citations),
        )
        generated.text = answer
        passages = ElementTree.SubElement(root, "passages", trust="untrusted")
        for passage in contexts:
            node = ElementTree.SubElement(
                passages,
                "passage",
                local_id=passage.local_id,
                document_id=passage.document_id,
            )
            node.text = f"{passage.title}\n{passage.text}"
        return JudgeRequest(
            query=query,
            answer=answer,
            abstained=abstained,
            citations=citations,
            contexts=contexts,
            system_prompt=self.system_prompt,
            user_prompt=ElementTree.tostring(root, encoding="unicode"),
            prompt_version=self.version,
            trace_id=trace_id,
        )

    def render_for_query(self, query: str, answer: AnswerResponse) -> JudgeRequest:
        return self.render_values(
            query=query,
            answer=answer.answer,
            abstained=answer.abstained,
            citations=answer.citations,
            contexts=answer.contexts,
            trace_id=answer.trace_id,
        )


class OpenAIJudge:
    provider = "openai"

    def __init__(
        self,
        *,
        profile: LLMProfile,
        pricing: PricingTable,
        prompt_version: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if profile.provider != self.provider:
            raise ValueError(f"OpenAIJudge cannot use provider {profile.provider!r}")
        self._profile = profile
        self._pricing = pricing
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._timeout_seconds = timeout_seconds
        self.model = profile.model
        self.configuration_hash = profile.configuration_hash
        self.prompt_version = prompt_version
        self._tracer = get_tracer(__name__)

    async def judge(self, request: JudgeRequest) -> JudgeVerdict:
        try:
            with self._tracer.start_as_current_span("judge") as span:
                span.set_attribute("gen_ai.system", self.provider)
                span.set_attribute("gen_ai.request.model", self.model)
                span.set_attribute("ragops.prompt.version", self.prompt_version)
                span.set_attribute("ragops.prompt.hash", request.rendered_prompt_hash)
                response = await self._client.responses.parse(
                    model=self.model,
                    instructions=request.system_prompt,
                    input=request.user_prompt,
                    max_output_tokens=self._profile.max_tokens,
                    text_format=JudgeOutput,
                    reasoning=(
                        {"effort": self._profile.effort}
                        if self._profile.effort is not None
                        else openai.omit
                    ),
                    temperature=(
                        self._profile.temperature
                        if self._profile.temperature is not None
                        else openai.omit
                    ),
                    prompt_cache_key=request.rendered_prompt_hash[:64],
                    store=False,
                    timeout=self._timeout_seconds,
                )
                traced_usage = self._usage(response.usage)
                span.set_attribute("gen_ai.usage.input_tokens", traced_usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", traced_usage.output_tokens)
                span.set_attribute("ragops.llm.cost_usd", float(traced_usage.cost_usd))
                if response.output_parsed is not None:
                    span.set_attribute(
                        "ragops.judge.faithfulness", response.output_parsed.faithfulness
                    )
                    span.set_attribute("ragops.judge.relevance", response.output_parsed.relevance)
        except openai.APITimeoutError as error:
            raise GenerationTimeoutError("OpenAI judging timed out") from error
        except (openai.APIConnectionError, openai.APIStatusError) as error:
            raise GenerationProviderError(
                f"OpenAI judging failed: {error}",
                provider_request_id=getattr(error, "request_id", None),
            ) from error
        except ValidationError as error:
            raise GenerationSchemaError(
                f"OpenAI returned an invalid judge verdict: {error}"
            ) from error

        usage = self._usage(response.usage)
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "refusal":
                        raise GenerationRefusalError(
                            content.refusal or "OpenAI refused the judge request",
                            usage=usage,
                            provider_request_id=response.id,
                        )
        if response.status != "completed" or response.output_parsed is None:
            raise GenerationSchemaError(
                "OpenAI did not return a complete parsed judge verdict",
                usage=usage,
                provider_request_id=response.id,
            )
        output = response.output_parsed
        return JudgeVerdict(
            **output.model_dump(),
            provider=self.provider,
            judge_model=self.model,
            judge_configuration_hash=self.configuration_hash,
            judge_prompt_version=self.prompt_version,
            rendered_prompt_hash=request.rendered_prompt_hash,
            usage=usage,
            provider_request_id=response.id,
        )

    def _usage(self, raw: ResponseUsage | None) -> TokenUsage:
        if raw is None:
            return TokenUsage(input_tokens=0, output_tokens=0)
        input_tokens = raw.input_tokens
        output_tokens = raw.output_tokens
        details = raw.input_tokens_details
        cached = int(details.cached_tokens)
        cache_write = int(details.cache_write_tokens)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached,
            cache_write_input_tokens=cache_write,
            cost_usd=self._pricing.calculate_cost(
                provider=self.provider,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached,
                cache_write_input_tokens=cache_write,
            ),
        )


def build_judge_cache_key(judge: Judge, request: JudgeRequest) -> str:
    canonical = json.dumps(
        {
            "provider": judge.provider,
            "model": judge.model,
            "configuration_hash": judge.configuration_hash,
            "prompt_version": judge.prompt_version,
            "rendered_prompt_hash": request.rendered_prompt_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CachingJudge:
    def __init__(self, *, judge: Judge, cache: JudgeCache) -> None:
        self._judge = judge
        self._cache = cache
        self.provider = judge.provider
        self.model = judge.model
        self.configuration_hash = judge.configuration_hash
        self.prompt_version = judge.prompt_version

    async def judge(self, request: JudgeRequest) -> JudgeVerdict:
        key = build_judge_cache_key(self, request)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached.model_copy(
                update={
                    "usage": TokenUsage(input_tokens=0, output_tokens=0),
                    "provider_request_id": None,
                    "cache_hit": True,
                }
            )
        verdict = await self._judge.judge(request)
        await self._cache.put(key, verdict)
        return verdict


class JudgeCache(Protocol):
    """Small structural interface kept here to avoid coupling judge code to SQLAlchemy."""

    async def get(self, key: str) -> JudgeVerdict | None: ...

    async def put(self, key: str, verdict: JudgeVerdict) -> None: ...

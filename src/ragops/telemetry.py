"""Process-wide OpenTelemetry and Prometheus setup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from threading import Lock
from time import perf_counter

from fastapi import FastAPI, Request, Response
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ragops.config import Settings
from ragops.contracts import AnswerResponse, JudgeVerdict

_CONFIGURE_LOCK = Lock()
_CONFIGURED = False

_meter = metrics.get_meter("ragops")
_http_requests = _meter.create_counter(
    "ragops.http.server.requests",
    description="HTTP requests received by the API",
    unit="{request}",
)
_http_duration = _meter.create_histogram(
    "ragops.http.server.duration",
    description="HTTP request duration",
    unit="s",
)
_retrieval_stage_duration = _meter.create_histogram(
    "ragops.retrieval.stage.duration",
    description="Retrieval pipeline stage duration",
    unit="ms",
)
_generation_duration = _meter.create_histogram(
    "ragops.generation.duration", description="Answer generation duration", unit="s"
)
_generation_outcomes = _meter.create_counter(
    "ragops.generation.outcomes", description="Generation outcomes", unit="{answer}"
)
_llm_tokens = _meter.create_counter(
    "ragops.llm.tokens", description="Provider token use", unit="{token}"
)
_llm_cost = _meter.create_counter(
    "ragops.llm.cost", description="Incremental provider cost", unit="USD"
)
_judge_scores = _meter.create_histogram(
    "ragops.judge.score", description="Offline and online judge scores", unit="1"
)


def configure_telemetry(settings: Settings) -> None:
    """Install the process-wide providers once.

    Prometheus always reads metrics from ``/metrics``. OTLP trace export is
    enabled only when an endpoint is configured, keeping tests and direct local
    commands independent of the collector.
    """
    global _CONFIGURED
    with _CONFIGURE_LOCK:
        if _CONFIGURED:
            return

        resource = Resource.create({SERVICE_NAME: settings.telemetry_service_name})
        tracer_provider = TracerProvider(resource=resource)
        if settings.otlp_endpoint is not None:
            endpoint = settings.otlp_endpoint.rstrip("/")
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
            )
        trace.set_tracer_provider(tracer_provider)

        metrics.set_meter_provider(
            MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()])
        )
        _CONFIGURED = True


def instrument_fastapi(application: FastAPI) -> None:
    """Add request tracing and low-cardinality service metrics to an app."""
    FastAPIInstrumentor.instrument_app(
        application,
        excluded_urls="healthz,readyz,metrics",
    )

    @application.middleware("http")
    async def record_http_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            attributes = {
                "http.request.method": request.method,
                "http.route": route_path,
                "http.response.status_code": status_code,
            }
            _http_requests.add(1, attributes)
            _http_duration.record(perf_counter() - started, attributes)


def prometheus_response() -> Response:
    """Render the process metric registry in Prometheus exposition format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_retrieval_stage(*, stage: str, duration_ms: float, dataset: str, variant: str) -> None:
    """Record one retrieval stage without query- or document-level labels."""
    _retrieval_stage_duration.record(
        duration_ms,
        {"stage": stage, "dataset": dataset, "variant": variant},
    )


def record_generation_answer(answer: AnswerResponse, *, duration_seconds: float) -> None:
    attributes: dict[str, str | int] = {
        "provider": answer.provider,
        "model": answer.model,
        "outcome": answer.outcome.value,
        "cache_hit": int(answer.cache_hit),
    }
    _generation_duration.record(duration_seconds, attributes)
    _generation_outcomes.add(1, attributes)
    for token_type, count in (
        ("input", answer.usage.input_tokens),
        ("cached_input", answer.usage.cached_input_tokens),
        ("cache_write_input", answer.usage.cache_write_input_tokens),
        ("output", answer.usage.output_tokens),
    ):
        _llm_tokens.add(count, {**attributes, "role": "generator", "token_type": token_type})
    _llm_cost.add(float(answer.usage.cost_usd), {**attributes, "role": "generator"})


def record_judge_verdict(*, profile: str, verdict: JudgeVerdict, source: str) -> None:
    attributes: dict[str, str | int] = {
        "provider": verdict.provider,
        "model": verdict.judge_model,
        "profile": profile,
        "source": source,
        "cache_hit": int(verdict.cache_hit),
    }
    _judge_scores.record(verdict.faithfulness, {**attributes, "metric": "faithfulness"})
    _judge_scores.record(verdict.relevance, {**attributes, "metric": "relevance"})
    _llm_cost.add(float(verdict.usage.cost_usd), {**attributes, "role": "judge"})

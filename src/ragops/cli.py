"""Command-line entry point for ragops."""

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from ragops import __version__
from ragops.config import Settings, load_config_bundle
from ragops.contracts import EVALUATION_JOB_KIND, EvalRunSpec
from ragops.evaluation import (
    build_run_baseline,
    gate_evaluation_run,
    get_evaluation_report,
    render_gate_report,
    render_markdown_report,
    run_retrieval_evaluation,
    write_baseline,
    write_report_files,
)
from ragops.ingestion.artifacts import Bm25sIndexBuilder
from ragops.ingestion.embedders import SentenceTransformerEmbedder
from ragops.ingestion.service import IngestionService
from ragops.persistence import create_engine, create_session_factory
from ragops.provenance import resolve_git_commit, resolve_image_digest
from ragops.retrieval.factory import build_retrieval_pipeline
from ragops.worker import JobWorker, build_evaluation_job_handler

DEFAULT_BASELINE_DIRECTORY = Path("evals/baselines")
DEFAULT_REPORT_DIRECTORY = Path("evals/runs")
GATE_BREACHED_EXIT_CODE = 1
GATE_NOT_COMPARABLE_EXIT_CODE = 2


def _variant_names(value: str) -> tuple[str, ...]:
    names = tuple(name.strip() for name in value.split(",") if name.strip())
    if not names:
        raise argparse.ArgumentTypeError("at least one variant is required")
    if len(set(names)) != len(names):
        raise argparse.ArgumentTypeError("variants must be unique")
    return names


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="ragops")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    ingest = commands.add_parser("ingest", help="ingest and index a configured BEIR dataset")
    ingest.add_argument("--dataset", required=True)
    ingest.add_argument("--split")
    ingest.add_argument("--device")
    ingest.add_argument("--write-batch-size", type=int, default=500)
    ingest.add_argument("--embedding-batch-size", type=int, default=64)

    evaluation = commands.add_parser("eval", help="manage evaluation runs")
    evaluation_commands = evaluation.add_subparsers(dest="evaluation_command")
    evaluation_run = evaluation_commands.add_parser(
        "run", help="run a retrieval evaluation in this process"
    )
    evaluation_run.add_argument("--dataset", required=True)
    evaluation_run.add_argument("--split")
    evaluation_run.add_argument("--variants", required=True, type=_variant_names)
    evaluation_run.add_argument("--sample-size", type=int)
    evaluation_run.add_argument("--seed", type=int, default=42)
    evaluation_run.add_argument("--device")
    evaluation_report = evaluation_commands.add_parser(
        "report", help="render a completed evaluation run"
    )
    evaluation_report.add_argument("run_id", type=UUID)
    evaluation_report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    evaluation_report.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIRECTORY)
    evaluation_report.add_argument(
        "--no-save", action="store_true", help="print the report without archiving it"
    )
    evaluation_gate = evaluation_commands.add_parser(
        "gate", help="compare a completed run against a committed baseline"
    )
    evaluation_gate.add_argument("run_id", type=UUID)
    evaluation_gate.add_argument(
        "--baseline",
        type=Path,
        help="baseline file (default: evals/baselines/<dataset>.json)",
    )
    evaluation_gate.add_argument("--format", choices=("markdown", "json"), default="markdown")
    evaluation_baseline = evaluation_commands.add_parser(
        "baseline", help="write a completed run's metrics as a committable baseline"
    )
    evaluation_baseline.add_argument("run_id", type=UUID)
    evaluation_baseline.add_argument(
        "--output",
        type=Path,
        help="output file (default: evals/baselines/<dataset>.json)",
    )

    worker = commands.add_parser("worker", help="execute queued evaluation jobs")
    worker.add_argument("--worker-id")
    worker.add_argument("--lease-seconds", type=int)
    worker.add_argument("--poll-interval", type=float)
    worker.add_argument("--device")
    worker.add_argument("--once", action="store_true", help="process at most one job, then exit")
    return parser


async def _ingest(arguments: argparse.Namespace) -> int:
    settings = Settings()
    bundle = load_config_bundle(settings.configuration_directory)
    manifest = bundle.datasets.get(arguments.dataset)
    profile = bundle.models.embeddings["default"]
    if profile.dimension != 384:
        raise ValueError("v1 ingestion requires a 384-dimensional embedding profile")

    engine = create_engine(settings.database_url)
    try:
        service = IngestionService(
            create_session_factory(engine),
            download_root=settings.artifact_directory / "datasets",
            artifact_root=settings.artifact_directory,
            sparse_index_builder=Bm25sIndexBuilder(),
        )
        result = await service.ingest(
            name=arguments.dataset,
            manifest=manifest,
            embedder=SentenceTransformerEmbedder(
                profile.model,
                normalized=profile.normalize,
                batch_size=arguments.embedding_batch_size,
                device=arguments.device,
                cache_directory=settings.model_cache_directory,
            ),
            split=arguments.split,
            write_batch_size=arguments.write_batch_size,
            embedding_batch_size=arguments.embedding_batch_size,
        )
        print(result.model_dump_json(indent=2))
        return 0
    finally:
        await engine.dispose()


async def _run_evaluation(arguments: argparse.Namespace) -> int:
    settings = Settings()
    bundle = load_config_bundle(settings.configuration_directory)
    manifest = bundle.datasets.get(arguments.dataset)
    spec = EvalRunSpec(
        dataset=arguments.dataset,
        split=arguments.split or manifest.default_split,
        variants=arguments.variants,
        sample_size=arguments.sample_size,
        seed=arguments.seed,
    )
    engine = create_engine(settings.database_url)
    try:
        sessions = create_session_factory(engine)
        search = build_retrieval_pipeline(
            bundle,
            sessions,
            artifact_root=settings.artifact_directory,
            device=arguments.device or settings.model_device,
            model_cache_directory=settings.model_cache_directory,
        )
        result = await run_retrieval_evaluation(
            sessions,
            search=search,
            datasets=bundle.datasets,
            variants=bundle.variants,
            spec=spec,
            git_commit=resolve_git_commit(),
            image_digest=resolve_image_digest(),
        )
        print(result.model_dump_json(indent=2))
        return 0
    finally:
        await engine.dispose()


async def _report_evaluation(arguments: argparse.Namespace) -> int:
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        report = await get_evaluation_report(create_session_factory(engine), arguments.run_id)
        if arguments.format == "json":
            print(report.model_dump_json(indent=2))
        else:
            print(render_markdown_report(report), end="")
        if not arguments.no_save:
            markdown_path, json_path = write_report_files(report, arguments.output_dir)
            print(f"\nsaved {markdown_path} and {json_path}")
        return 0
    finally:
        await engine.dispose()


async def _gate_evaluation(arguments: argparse.Namespace) -> int:
    settings = Settings()
    bundle = load_config_bundle(settings.configuration_directory)
    engine = create_engine(settings.database_url)
    try:
        try:
            result = await gate_evaluation_run(
                create_session_factory(engine),
                arguments.run_id,
                baseline_path=arguments.baseline,
                thresholds=bundle.thresholds,
            )
        except (FileNotFoundError, KeyError, ValueError) as error:
            # A gate that cannot compare is not a passing gate, but it is also not a
            # quality regression. CI needs to tell the two apart: exit 1 means the
            # numbers got worse, exit 2 means the comparison itself is unusable.
            message = error.args[0] if isinstance(error, KeyError) else error
            print(f"cannot evaluate gate: {message}", file=sys.stderr)
            return GATE_NOT_COMPARABLE_EXIT_CODE
        if arguments.format == "json":
            print(result.model_dump_json(indent=2))
        else:
            print(render_gate_report(result), end="")
        return 0 if result.passed else GATE_BREACHED_EXIT_CODE
    finally:
        await engine.dispose()


async def _write_baseline(arguments: argparse.Namespace) -> int:
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        baseline = await build_run_baseline(create_session_factory(engine), arguments.run_id)
        output = arguments.output or DEFAULT_BASELINE_DIRECTORY / f"{baseline.dataset}.json"
        write_baseline(baseline, output)
        print(f"wrote baseline for run {baseline.run_id} to {output}")
        return 0
    finally:
        await engine.dispose()


async def _run_worker(arguments: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    bundle = load_config_bundle(settings.configuration_directory)
    engine = create_engine(settings.database_url)
    try:
        sessions = create_session_factory(engine)
        search = build_retrieval_pipeline(
            bundle,
            sessions,
            artifact_root=settings.artifact_directory,
            device=arguments.device or settings.model_device,
            model_cache_directory=settings.model_cache_directory,
        )
        worker = JobWorker(
            sessions,
            handlers={
                EVALUATION_JOB_KIND: build_evaluation_job_handler(
                    sessions,
                    search=search,
                    datasets=bundle.datasets,
                    variants=bundle.variants,
                )
            },
            worker_id=arguments.worker_id,
            lease_seconds=arguments.lease_seconds or settings.worker_lease_seconds,
            poll_interval_seconds=(
                arguments.poll_interval or settings.worker_poll_interval_seconds
            ),
        )
        if arguments.once:
            job = await worker.run_once()
            print("no job was available" if job is None else job.model_dump_json(indent=2))
            return 0

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            # Windows event loops do not implement signal handlers; a KeyboardInterrupt
            # still unwinds the loop there.
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signal_name, stop.set)
        print(f"worker {worker.worker_id} polling for jobs; press ctrl-c to stop")
        await worker.run_forever(stop=stop)
        print(f"worker {worker.worker_id} stopped")
        return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "ingest":
        return asyncio.run(_ingest(arguments))
    if arguments.command == "eval" and arguments.evaluation_command == "run":
        return asyncio.run(_run_evaluation(arguments))
    if arguments.command == "eval" and arguments.evaluation_command == "report":
        return asyncio.run(_report_evaluation(arguments))
    if arguments.command == "eval" and arguments.evaluation_command == "gate":
        return asyncio.run(_gate_evaluation(arguments))
    if arguments.command == "eval" and arguments.evaluation_command == "baseline":
        return asyncio.run(_write_baseline(arguments))
    if arguments.command == "worker":
        return asyncio.run(_run_worker(arguments))
    parser.print_help()
    return 0

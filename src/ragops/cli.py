"""Command-line entry point for ragops."""

import argparse
import asyncio
from collections.abc import Sequence

from ragops import __version__
from ragops.config import Settings, load_config_bundle
from ragops.ingestion.artifacts import Bm25sIndexBuilder
from ragops.ingestion.embedders import SentenceTransformerEmbedder
from ragops.ingestion.service import IngestionService
from ragops.persistence import create_engine, create_session_factory


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
            ),
            split=arguments.split,
            write_batch_size=arguments.write_batch_size,
            embedding_batch_size=arguments.embedding_batch_size,
        )
        print(result.model_dump_json(indent=2))
        return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "ingest":
        return asyncio.run(_ingest(arguments))
    parser.print_help()
    return 0

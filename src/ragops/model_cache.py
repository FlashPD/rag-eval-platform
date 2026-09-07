"""Configuration for model-provider caches used by local adapters."""

import os
from pathlib import Path


def configure_huggingface_cache(cache_directory: Path | None) -> str | None:
    """Route Hugging Face and Xet files to an explicit writable directory."""
    if cache_directory is None:
        return None
    resolved = cache_directory.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    xet_directory = resolved / "xet"
    xet_directory.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(resolved)
    os.environ["HF_XET_CACHE"] = str(xet_directory)
    return str(resolved)

import os
from pathlib import Path

import pytest

from ragops.model_cache import configure_huggingface_cache


def test_configure_huggingface_cache_routes_hub_and_xet_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_XET_CACHE", raising=False)
    cache_directory = tmp_path / "models"

    configured = configure_huggingface_cache(cache_directory)

    assert configured == str(cache_directory.resolve())
    assert os.environ["HF_HOME"] == configured
    assert os.environ["HF_XET_CACHE"] == str(cache_directory.resolve() / "xet")
    assert (cache_directory / "xet").is_dir()

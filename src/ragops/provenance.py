"""Provenance of an evaluation run: the code and image that produced it."""

import os
import subprocess
from pathlib import Path

IMAGE_DIGEST_VARIABLE = "RAGOPS_IMAGE_DIGEST"


def resolve_git_commit(repository: Path | None = None) -> str | None:
    """Return the current commit, or ``None`` outside a working git checkout.

    A run recorded without a commit is still usable; refusing to evaluate because
    the code is not in a repository would block the container and CI paths.
    """
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository or Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def resolve_image_digest() -> str | None:
    """Return the container image digest published by the deployment environment."""
    return os.environ.get(IMAGE_DIGEST_VARIABLE) or None

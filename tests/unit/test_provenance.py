import subprocess
from pathlib import Path

import pytest

from ragops.provenance import IMAGE_DIGEST_VARIABLE, resolve_git_commit, resolve_image_digest


def test_resolve_git_commit_reads_the_checkout(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.email", "test@example.com"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("content", encoding="utf-8")
    subprocess.run(("git", "add", "file.txt"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "--quiet", "-m", "initial"), cwd=tmp_path, check=True)

    commit = resolve_git_commit(tmp_path)

    assert commit is not None
    assert len(commit) == 40


def test_resolve_git_commit_returns_none_outside_a_repository(tmp_path: Path) -> None:
    # A run outside a checkout is still recorded, just without a commit.
    assert resolve_git_commit(tmp_path) is None


def test_resolve_image_digest_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(IMAGE_DIGEST_VARIABLE, "sha256:abc")
    assert resolve_image_digest() == "sha256:abc"

    monkeypatch.setenv(IMAGE_DIGEST_VARIABLE, "")
    assert resolve_image_digest() is None

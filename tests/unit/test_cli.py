from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import ragops.cli as cli
from ragops.cli import build_parser, main
from ragops.contracts import (
    BaselineDocument,
    EvalProgress,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    EvaluationReport,
    GateMetricResult,
    GateResult,
    LatencySummary,
    MetricSummary,
)
from ragops.evaluation import read_baseline

CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"


def test_cli_reports_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])

    assert capsys.readouterr().out == "0.1.0\n"


def test_eval_run_parser_accepts_comma_separated_variants() -> None:
    arguments = build_parser().parse_args(
        [
            "eval",
            "run",
            "--dataset",
            "scifact",
            "--variants",
            "bm25, hybrid_rrf",
            "--sample-size",
            "50",
            "--seed",
            "7",
        ]
    )

    assert arguments.command == "eval"
    assert arguments.evaluation_command == "run"
    assert arguments.variants == ("bm25", "hybrid_rrf")
    assert arguments.sample_size == 50
    assert arguments.seed == 7


def test_eval_run_parser_rejects_duplicate_variants() -> None:
    with pytest.raises(SystemExit, match="2"):
        build_parser().parse_args(
            ["eval", "run", "--dataset", "scifact", "--variants", "bm25,bm25"]
        )


def test_eval_run_command_builds_and_executes_spec(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        async def dispose(self) -> None:
            captured["disposed"] = True

    async def fake_run_retrieval_evaluation(
        sessions: object,
        *,
        search: object,
        datasets: object,
        variants: object,
        spec: EvalRunSpec,
        git_commit: str | None = None,
        image_digest: str | None = None,
    ) -> EvalRun:
        captured["sessions"] = sessions
        captured["search"] = search
        captured["spec"] = spec
        captured["git_commit"] = git_commit
        captured["image_digest"] = image_digest
        return EvalRun(
            id=uuid4(),
            spec=spec,
            state=EvalRunState.COMPLETED,
            progress=EvalProgress(completed_queries=2, total_queries=2),
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

    bundle = cli.load_config_bundle(CONFIG_DIRECTORY)
    settings = SimpleNamespace(
        configuration_directory=CONFIG_DIRECTORY,
        database_url="sqlite+aiosqlite:///:memory:",
        artifact_directory=Path("artifacts"),
        model_cache_directory=Path("artifacts/models"),
        model_device=None,
    )
    sessions = object()
    search = object()
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "load_config_bundle", lambda _: bundle)
    monkeypatch.setattr(cli, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(cli, "create_session_factory", lambda _: sessions)
    monkeypatch.setattr(cli, "build_retrieval_pipeline", lambda *args, **kwargs: search)
    monkeypatch.setattr(cli, "run_retrieval_evaluation", fake_run_retrieval_evaluation)
    monkeypatch.setattr(cli, "resolve_git_commit", lambda: "commit-sha")
    monkeypatch.setattr(cli, "resolve_image_digest", lambda: "sha256:image")

    exit_code = main(
        [
            "eval",
            "run",
            "--dataset",
            "fixture",
            "--variants",
            "bm25",
            "--sample-size",
            "2",
        ]
    )

    assert exit_code == 0
    assert captured["spec"] == EvalRunSpec(
        dataset="fixture",
        split="test",
        variants=("bm25",),
        sample_size=2,
        seed=42,
    )
    assert captured["disposed"] is True
    assert captured["git_commit"] == "commit-sha"
    assert captured["image_digest"] == "sha256:image"
    assert '"state": "completed"' in capsys.readouterr().out


def test_eval_report_command_renders_markdown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    run_id = uuid4()
    now = datetime.now(UTC)
    run = EvalRun(
        id=run_id,
        spec=EvalRunSpec(dataset="fixture", variants=("bm25",)),
        state=EvalRunState.COMPLETED,
        progress=EvalProgress(completed_queries=1, total_queries=1),
        created_at=now,
        completed_at=now,
    )
    report = EvaluationReport(
        run=run,
        metrics=(
            MetricSummary(
                metric="ndcg_at_10",
                variant="bm25",
                mean=1.0,
                interval_low=1.0,
                interval_high=1.0,
                query_count=1,
            ),
        ),
        latencies=(
            LatencySummary(
                variant="bm25",
                stage="sparse_retrieve",
                p50_ms=1.0,
                p95_ms=1.0,
                sample_count=1,
            ),
        ),
    )
    captured: dict[str, object] = {}

    class FakeEngine:
        async def dispose(self) -> None:
            captured["disposed"] = True

    async def fake_get_evaluation_report(sessions: object, requested_run_id: object) -> object:
        captured["sessions"] = sessions
        captured["run_id"] = requested_run_id
        return report

    settings = SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:")
    sessions = object()
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(cli, "create_session_factory", lambda _: sessions)
    monkeypatch.setattr(cli, "get_evaluation_report", fake_get_evaluation_report)

    exit_code = main(["eval", "report", str(run_id), "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert captured["run_id"] == run_id
    assert captured["disposed"] is True
    assert f"# Retrieval evaluation `{run_id}`" in capsys.readouterr().out
    assert (tmp_path / str(run_id) / "report.md").exists()
    assert (tmp_path / str(run_id) / "report.json").exists()


def test_eval_report_command_can_skip_archiving(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    run_id = uuid4()
    now = datetime.now(UTC)
    report = EvaluationReport(
        run=EvalRun(
            id=run_id,
            spec=EvalRunSpec(dataset="fixture", variants=("bm25",)),
            state=EvalRunState.COMPLETED,
            progress=EvalProgress(completed_queries=1, total_queries=1),
            created_at=now,
            completed_at=now,
        ),
        metrics=(
            MetricSummary(
                metric="ndcg_at_10",
                variant="bm25",
                mean=1.0,
                interval_low=1.0,
                interval_high=1.0,
                query_count=1,
            ),
        ),
        latencies=(),
    )

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    async def fake_get_evaluation_report(sessions: object, requested: object) -> object:
        return report

    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(cli, "create_session_factory", lambda _: object())
    monkeypatch.setattr(cli, "get_evaluation_report", fake_get_evaluation_report)

    exit_code = main(["eval", "report", str(run_id), "--output-dir", str(tmp_path), "--no-save"])

    assert exit_code == 0
    assert not (tmp_path / str(run_id)).exists()
    assert "saved" not in capsys.readouterr().out


def test_eval_gate_command_exits_non_zero_on_regression(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = uuid4()
    baseline_run_id = uuid4()
    captured: dict[str, object] = {}

    class FakeEngine:
        async def dispose(self) -> None:
            captured["disposed"] = True

    async def fake_gate_evaluation_run(
        sessions: object,
        requested_run_id: object,
        *,
        baseline_path: Path,
        thresholds: object,
    ) -> GateResult:
        captured["run_id"] = requested_run_id
        captured["baseline_path"] = baseline_path
        return GateResult(
            passed=False,
            dataset="scifact",
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            metrics=(
                GateMetricResult(
                    variant="bm25",
                    metric="ndcg_at_10",
                    baseline=0.60,
                    observed=0.50,
                    tolerance=0.01,
                    breached=True,
                ),
            ),
        )

    bundle = cli.load_config_bundle(CONFIG_DIRECTORY)
    settings = SimpleNamespace(
        configuration_directory=CONFIG_DIRECTORY,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "load_config_bundle", lambda _: bundle)
    monkeypatch.setattr(cli, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(cli, "create_session_factory", lambda _: object())
    monkeypatch.setattr(cli, "gate_evaluation_run", fake_gate_evaluation_run)

    exit_code = main(["eval", "gate", str(run_id), "--baseline", "evals/baselines/main.json"])

    assert exit_code == 1
    assert captured["run_id"] == run_id
    assert captured["baseline_path"] == Path("evals/baselines/main.json")
    assert captured["disposed"] is True
    assert "# Regression gate FAILED" in capsys.readouterr().out


def test_eval_baseline_command_writes_the_requested_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    run_id = uuid4()
    baseline = BaselineDocument(
        dataset="scifact",
        split="test",
        run_id=run_id,
        recorded_at=datetime.now(UTC),
        metrics={"bm25": {"ndcg_at_10": 0.6}},
    )

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    async def fake_build_run_baseline(sessions: object, requested: object) -> BaselineDocument:
        return baseline

    settings = SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(cli, "create_session_factory", lambda _: object())
    monkeypatch.setattr(cli, "build_run_baseline", fake_build_run_baseline)

    output = tmp_path / "main.json"
    exit_code = main(["eval", "baseline", str(run_id), "--output", str(output)])

    assert exit_code == 0
    assert read_baseline(output) == baseline
    assert str(output) in capsys.readouterr().out

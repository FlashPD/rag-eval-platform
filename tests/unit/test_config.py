from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ragops.config import LLMProfile, Settings, load_config_bundle
from ragops.contracts import DenseStageConfig, FusionStageConfig, VariantConfig

CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"


def test_loads_checked_in_configuration() -> None:
    bundle = load_config_bundle(CONFIG_DIRECTORY)

    hybrid = bundle.variants.get("hybrid_rrf")
    assert hybrid.fusion == FusionStageConfig(method="rrf", k=60)
    assert len(hybrid.configuration_hash) == 64
    assert bundle.datasets.get("fixture").source == "local"
    assert bundle.datasets.get("nfcorpus").checksum == "a89dba18a62ef92f7d323ec890a0d38d"
    assert bundle.datasets.get("fiqa").checksum == "17918ed23cd04fb15047f73e6c3bd9d9"
    assert bundle.models.embeddings["default"].dimension == 384
    assert bundle.thresholds.metrics["ndcg_at_10"].maximum_absolute_drop == 0.01


def test_variant_hash_is_deterministic() -> None:
    first = VariantConfig(
        name="dense",
        dense=DenseStageConfig(model="example/model", k=10),
    )
    second = VariantConfig.model_validate(first.model_dump())

    assert first.configuration_hash == second.configuration_hash


def test_llm_profile_hash_covers_provider_model_and_parameters() -> None:
    first = LLMProfile(
        provider="openai",
        model="example/model",
        effort="medium",
        temperature=0,
        max_tokens=1_024,
    )
    same = LLMProfile.model_validate(first.model_dump())
    changed = first.model_copy(update={"max_tokens": 2_048})

    assert first.configuration_hash == same.configuration_hash
    assert first.configuration_hash != changed.configuration_hash


def test_fusion_requires_both_retrieval_stages() -> None:
    with pytest.raises(ValidationError, match="fusion requires both"):
        VariantConfig(
            name="invalid",
            dense=DenseStageConfig(model="example/model"),
            fusion=FusionStageConfig(),
        )


def test_pricing_uses_decimal_arithmetic() -> None:
    pricing = load_config_bundle(CONFIG_DIRECTORY).pricing

    cost = pricing.calculate_cost(
        provider="openai",
        model="gpt-5.4-mini-2026-03-17",
        input_tokens=2_500,
        output_tokens=300,
    )

    assert cost == Decimal("0.003225")


def test_settings_use_ragops_environment_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGOPS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("RAGOPS_MODEL_CACHE_DIRECTORY", "tmp/model-cache")

    settings = Settings()
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.model_cache_directory == Path("tmp/model-cache")


def test_settings_compose_an_ssl_rds_url_from_secret_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAGOPS_DATABASE_URL", raising=False)
    monkeypatch.setenv("RAGOPS_DATABASE_HOST", "database.example.us-east-1.rds.amazonaws.com")
    monkeypatch.setenv("RAGOPS_DATABASE_PORT", "5433")
    monkeypatch.setenv("RAGOPS_DATABASE_NAME", "ragops_production")
    monkeypatch.setenv("RAGOPS_DATABASE_USER", "application")
    monkeypatch.setenv("RAGOPS_DATABASE_PASSWORD", "p@ss:/word")

    settings = Settings(_env_file=None)

    assert settings.database_url == (
        "postgresql+asyncpg://application:p%40ss%3A%2Fword@"
        "database.example.us-east-1.rds.amazonaws.com:5433/ragops_production?ssl=require"
    )
    assert settings.database_password is not None
    assert settings.database_password.get_secret_value() == "p@ss:/word"


def test_settings_require_complete_database_components() -> None:
    with pytest.raises(ValidationError, match="database_user, database_password"):
        Settings(_env_file=None, database_host="database.example")


def test_settings_reject_a_url_mixed_with_database_components() -> None:
    with pytest.raises(ValidationError, match="either database_url or database component"):
        Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///:memory:",
            database_host="database.example",
            database_user="application",
            database_password="secret",
        )

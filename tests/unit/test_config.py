from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ragops.config import Settings, load_config_bundle
from ragops.contracts import DenseStageConfig, FusionStageConfig, VariantConfig

CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"


def test_loads_checked_in_configuration() -> None:
    bundle = load_config_bundle(CONFIG_DIRECTORY)

    hybrid = bundle.variants.get("hybrid_rrf")
    assert hybrid.fusion == FusionStageConfig(method="rrf", k=60)
    assert len(hybrid.configuration_hash) == 64
    assert bundle.datasets.get("fixture").source == "local"
    assert bundle.models.embeddings["default"].dimension == 384
    assert bundle.thresholds.metrics["ndcg_at_10"].maximum_absolute_drop == 0.01


def test_variant_hash_is_deterministic() -> None:
    first = VariantConfig(
        name="dense",
        dense=DenseStageConfig(model="example/model", k=10),
    )
    second = VariantConfig.model_validate(first.model_dump())

    assert first.configuration_hash == second.configuration_hash


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
        provider="anthropic",
        model="claude-opus-5",
        input_tokens=2_500,
        output_tokens=300,
    )

    assert cost == Decimal("0.02000")


def test_settings_use_ragops_environment_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGOPS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("RAGOPS_MODEL_CACHE_DIRECTORY", "tmp/model-cache")

    settings = Settings()
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.model_cache_directory == Path("tmp/model-cache")

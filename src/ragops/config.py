"""Validated application and experiment configuration."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, PositiveFloat, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ragops.contracts.base import Contract
from ragops.contracts.retrieval import VariantConfig


class Settings(BaseSettings):
    """Environment-backed service settings."""

    model_config = SettingsConfigDict(
        env_prefix="RAGOPS_",
        env_file=".env",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "postgresql+asyncpg://ragops:ragops@localhost:5432/ragops"
    configuration_directory: Path = Path("config")
    artifact_directory: Path = Path("artifacts")
    model_device: str | None = None
    worker_poll_interval_seconds: PositiveFloat = 1.0
    worker_lease_seconds: PositiveInt = 300


class EmbeddingProfile(Contract):
    provider: Literal["sentence_transformers"]
    model: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    normalize: bool = True


class RerankerProfile(Contract):
    provider: Literal["sentence_transformers"]
    model: str = Field(min_length=1)


class LLMProfile(Contract):
    provider: Literal["anthropic", "openai"]
    model: str = Field(min_length=1)
    effort: Literal["low", "medium", "high"] | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(gt=0)


class ModelCatalog(Contract):
    embeddings: dict[str, EmbeddingProfile]
    rerankers: dict[str, RerankerProfile]
    generators: dict[str, LLMProfile]
    judges: dict[str, LLMProfile]


class ModelPricing(Contract):
    input_per_million_tokens: Decimal = Field(ge=0)
    output_per_million_tokens: Decimal = Field(ge=0)
    cached_input_per_million_tokens: Decimal | None = Field(default=None, ge=0)


class PricingTable(Contract):
    providers: dict[str, dict[str, ModelPricing]]

    def calculate_cost(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Decimal:
        if min(input_tokens, output_tokens, cached_input_tokens) < 0:
            raise ValueError("token counts cannot be negative")
        if cached_input_tokens > input_tokens:
            raise ValueError("cached input tokens cannot exceed total input tokens")

        try:
            pricing = self.providers[provider][model]
        except KeyError as error:
            raise ValueError(f"no pricing configured for {provider}/{model}") from error

        million = Decimal(1_000_000)
        cached_rate = (
            pricing.cached_input_per_million_tokens
            if pricing.cached_input_per_million_tokens is not None
            else pricing.input_per_million_tokens
        )
        uncached_input = input_tokens - cached_input_tokens
        return (
            Decimal(uncached_input) * pricing.input_per_million_tokens
            + Decimal(cached_input_tokens) * cached_rate
            + Decimal(output_tokens) * pricing.output_per_million_tokens
        ) / million


class MetricThreshold(Contract):
    maximum_absolute_drop: float = Field(ge=0)


class ThresholdCatalog(Contract):
    metrics: dict[str, MetricThreshold]


class RemoteDatasetManifest(Contract):
    source: Literal["remote"]
    version: str = Field(min_length=1)
    default_split: str = Field(default="test", min_length=1)
    license_name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    checksum_algorithm: Literal["md5", "sha256"]
    checksum: str = Field(pattern=r"^[a-f0-9]+$")


class LocalDatasetManifest(Contract):
    source: Literal["local"]
    version: str = Field(min_length=1)
    default_split: str = Field(default="test", min_length=1)
    license_name: str = Field(min_length=1)
    path: Path


DatasetManifest = Annotated[
    RemoteDatasetManifest | LocalDatasetManifest, Field(discriminator="source")
]


class DatasetCatalog(Contract):
    datasets: dict[str, DatasetManifest]

    def get(self, name: str) -> DatasetManifest:
        try:
            return self.datasets[name]
        except KeyError as error:
            choices = ", ".join(sorted(self.datasets))
            raise KeyError(f"unknown dataset {name!r}; available datasets: {choices}") from error


class VariantRegistry(Contract):
    variants: dict[str, VariantConfig]

    @model_validator(mode="after")
    def validate_names(self) -> "VariantRegistry":
        mismatches = [key for key, variant in self.variants.items() if key != variant.name]
        if mismatches:
            raise ValueError(f"variant names must match their registry keys: {mismatches}")
        return self

    def get(self, name: str) -> VariantConfig:
        try:
            return self.variants[name]
        except KeyError as error:
            choices = ", ".join(sorted(self.variants))
            raise KeyError(f"unknown variant {name!r}; available variants: {choices}") from error


class ConfigBundle(Contract):
    datasets: DatasetCatalog
    variants: VariantRegistry
    models: ModelCatalog
    pricing: PricingTable
    thresholds: ThresholdCatalog


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"configuration file not found: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {path}: {error}") from error

    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return value


def load_variant_registry(path: Path) -> VariantRegistry:
    raw = _read_yaml(path)
    raw_variants = raw.get("variants")
    if not isinstance(raw_variants, dict):
        raise ValueError(f"'variants' must be a mapping: {path}")

    variants: dict[str, VariantConfig] = {}
    for name, value in raw_variants.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError(f"each variant must be a named mapping: {path}")
        variants[name] = VariantConfig.model_validate({"name": name, **value})
    return VariantRegistry(variants=variants)


def load_dataset_catalog(path: Path) -> DatasetCatalog:
    catalog = DatasetCatalog.model_validate(_read_yaml(path))
    resolved: dict[str, DatasetManifest] = {}
    for name, manifest in catalog.datasets.items():
        if isinstance(manifest, LocalDatasetManifest) and not manifest.path.is_absolute():
            manifest = manifest.model_copy(update={"path": (path.parent / manifest.path).resolve()})
        resolved[name] = manifest
    return DatasetCatalog(datasets=resolved)


def load_config_bundle(directory: Path) -> ConfigBundle:
    return ConfigBundle(
        datasets=load_dataset_catalog(directory / "datasets.yaml"),
        variants=load_variant_registry(directory / "variants.yaml"),
        models=ModelCatalog.model_validate(_read_yaml(directory / "models.yaml")["models"]),
        pricing=PricingTable.model_validate(_read_yaml(directory / "pricing.yaml")),
        thresholds=ThresholdCatalog.model_validate(_read_yaml(directory / "thresholds.yaml")),
    )

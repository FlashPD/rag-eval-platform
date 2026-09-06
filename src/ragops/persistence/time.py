"""Timestamp normalization at persistence boundaries."""

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    """Return an aware UTC timestamp even when a test database drops timezone data."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def optional_as_utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None

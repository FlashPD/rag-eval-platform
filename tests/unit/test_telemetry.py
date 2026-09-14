from unittest.mock import Mock, patch

from ragops.config import Settings
from ragops.telemetry import _build_metric_readers


def test_otlp_metrics_are_exported_alongside_prometheus() -> None:
    prometheus_reader = Mock()
    otlp_exporter = Mock()
    periodic_reader = Mock()

    with (
        patch(
            "ragops.telemetry.PrometheusMetricReader",
            return_value=prometheus_reader,
        ),
        patch("ragops.telemetry.OTLPMetricExporter", return_value=otlp_exporter) as exporter,
        patch(
            "ragops.telemetry.PeriodicExportingMetricReader",
            return_value=periodic_reader,
        ) as periodic,
    ):
        readers = _build_metric_readers(
            Settings(_env_file=None, otlp_endpoint="http://collector:4318/")
        )

    exporter.assert_called_once_with(endpoint="http://collector:4318/v1/metrics")
    periodic.assert_called_once_with(otlp_exporter)
    assert readers == [prometheus_reader, periodic_reader]

"""Evaluation metrics, execution, reporting, and regression gates."""

from ragops.evaluation.calibration import (
    compute_calibration_agreement,
    load_calibration_labels,
    render_calibration_markdown,
    run_calibration,
)
from ragops.evaluation.gate import (
    build_baseline,
    evaluate_gate,
    read_baseline,
    render_gate_report,
    write_baseline,
)
from ragops.evaluation.reporting import (
    build_evaluation_report,
    build_variant_comparisons,
    render_markdown_report,
    write_report_files,
)
from ragops.evaluation.retrieval_metrics import compute_retrieval_metrics
from ragops.evaluation.runner import RetrievalEvaluationRunner, select_evaluation_queries
from ragops.evaluation.service import (
    DatabaseEvaluationService,
    EvaluationService,
    build_run_baseline,
    create_retrieval_evaluation,
    gate_evaluation_run,
    get_evaluation_report,
    get_evaluation_run,
    run_retrieval_evaluation,
    submit_retrieval_evaluation,
)

__all__ = [
    "DatabaseEvaluationService",
    "EvaluationService",
    "RetrievalEvaluationRunner",
    "build_baseline",
    "build_evaluation_report",
    "build_run_baseline",
    "build_variant_comparisons",
    "compute_calibration_agreement",
    "compute_retrieval_metrics",
    "create_retrieval_evaluation",
    "evaluate_gate",
    "gate_evaluation_run",
    "get_evaluation_report",
    "get_evaluation_run",
    "load_calibration_labels",
    "read_baseline",
    "render_calibration_markdown",
    "render_gate_report",
    "render_markdown_report",
    "run_calibration",
    "run_retrieval_evaluation",
    "select_evaluation_queries",
    "submit_retrieval_evaluation",
    "write_baseline",
    "write_report_files",
]

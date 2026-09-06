import pytest
from pydantic import ValidationError

from ragops.contracts import EvalRunSpec, EvalRunState, ensure_state_transition


def test_generation_profile_is_required_when_generation_is_enabled() -> None:
    with pytest.raises(ValidationError, match="generator_profile"):
        EvalRunSpec(dataset="scifact", variants=("bm25",), generation_enabled=True)


def test_eval_run_lifecycle_accepts_forward_and_terminal_transitions() -> None:
    ensure_state_transition(EvalRunState.CREATED, EvalRunState.QUEUED)
    ensure_state_transition(EvalRunState.RETRIEVING, EvalRunState.SCORING)
    ensure_state_transition(EvalRunState.RETRIEVING, EvalRunState.FAILED)


def test_eval_run_lifecycle_rejects_skipped_stage() -> None:
    with pytest.raises(ValueError, match="created -> retrieving"):
        ensure_state_transition(EvalRunState.CREATED, EvalRunState.RETRIEVING)

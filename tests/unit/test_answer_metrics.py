from ragops.contracts import (
    AnswerResponse,
    CitationValidation,
    Confidence,
    GenerationOutcome,
    Passage,
    SciFactLabel,
    TokenUsage,
)
from ragops.evaluation.answer_metrics import (
    compute_answer_metrics,
    compute_scifact_rationale_precision,
    macro_f1,
    scifact_gold_label,
)


def answer(*, abstained: bool = False) -> AnswerResponse:
    citations = () if abstained else ("[1]",)
    return AnswerResponse(
        answer="Insufficient context." if abstained else "Supported [1].",
        citations=citations,
        abstained=abstained,
        confidence=Confidence.LOW if abstained else Confidence.HIGH,
        contexts=(
            Passage(
                local_id="[1]",
                document_id="doc-1",
                title="Evidence",
                text="Sentence zero. Sentence one.",
                retrieval_rank=1,
                retrieval_score=0.9,
            ),
            Passage(
                local_id="[2]",
                document_id="doc-2",
                title="Distractor",
                text="Other text.",
                retrieval_rank=2,
                retrieval_score=0.5,
            ),
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        outcome=GenerationOutcome.ABSTAINED if abstained else GenerationOutcome.OK,
        trace_id="trace-1",
        provider="openai",
        model="test-model",
        generator_configuration_hash="a" * 64,
        prompt_version="answer-v1",
        rendered_prompt_hash="b" * 64,
        citation_validation=CitationValidation(valid=True),
    )


def test_answer_metrics_are_deterministic_from_context_and_qrels() -> None:
    scores = compute_answer_metrics(answer(), {"doc-1": 1, "doc-3": 1})

    assert scores.citation_validity == 1
    assert scores.context_precision == 0.5
    assert scores.abstention_correctness == 1


def test_correct_abstention_requires_no_relevant_retrieved_context() -> None:
    assert compute_answer_metrics(answer(abstained=True), {"doc-3": 1}).abstention_correctness == 1


def test_scifact_label_rationale_precision_and_macro_f1() -> None:
    metadata = {
        "doc-1": [{"label": "SUPPORT", "sentences": [0, 1]}],
    }
    prediction = answer().model_copy(
        update={
            "verification_label": SciFactLabel.SUPPORT,
            "rationale_sentences": {"[1]": (1, 8), "[2]": (0,)},
        }
    )

    assert scifact_gold_label(metadata) is SciFactLabel.SUPPORT
    assert compute_scifact_rationale_precision(prediction, metadata) == 1 / 3
    assert (
        macro_f1(
            [SciFactLabel.SUPPORT, SciFactLabel.CONTRADICT, SciFactLabel.NOT_ENOUGH_INFO],
            [SciFactLabel.SUPPORT, SciFactLabel.CONTRADICT, None],
        )
        == 2 / 3
    )


def test_scifact_empty_evidence_is_not_enough_info() -> None:
    assert scifact_gold_label({}) is SciFactLabel.NOT_ENOUGH_INFO

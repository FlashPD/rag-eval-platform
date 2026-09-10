"""Human-label loading and Cohen's kappa agreement reporting."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ragops.contracts import CalibrationAgreement, CalibrationLabel, JudgeVerdict
from ragops.evaluation.judging import VersionedJudgePromptRenderer
from ragops.protocols import Judge


def cohens_kappa(human: Sequence[bool], judge: Sequence[bool]) -> float:
    if not human or len(human) != len(judge):
        raise ValueError("Cohen's kappa requires equal non-empty label sequences")
    observed = sum(left == right for left, right in zip(human, judge, strict=True)) / len(human)
    human_positive = sum(human) / len(human)
    judge_positive = sum(judge) / len(judge)
    expected = human_positive * judge_positive + (1 - human_positive) * (1 - judge_positive)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def load_calibration_labels(path: Path) -> tuple[CalibrationLabel, ...]:
    labels: list[CalibrationLabel] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                labels.append(CalibrationLabel.model_validate_json(line))
            except (ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid calibration label at {path}:{line_number}") from error
    if not labels:
        raise ValueError("calibration set cannot be empty")
    ids = [label.id for label in labels]
    if len(ids) != len(set(ids)):
        raise ValueError("calibration label IDs must be unique")
    return tuple(labels)


def compute_calibration_agreement(
    *,
    judge_profile: str,
    labels: Sequence[CalibrationLabel],
    verdicts: Mapping[str, JudgeVerdict],
) -> CalibrationAgreement:
    expected_ids = {label.id for label in labels}
    if set(verdicts) != expected_ids:
        raise ValueError("judge verdicts must cover exactly the calibration labels")
    first = verdicts[labels[0].id]
    for verdict in verdicts.values():
        if (
            verdict.judge_model != first.judge_model
            or verdict.judge_prompt_version != first.judge_prompt_version
        ):
            raise ValueError("calibration verdicts must use one judge model and prompt version")
    return CalibrationAgreement(
        judge_profile=judge_profile,
        judge_model=first.judge_model,
        judge_prompt_version=first.judge_prompt_version,
        sample_count=len(labels),
        faithfulness_kappa=cohens_kappa(
            [label.human_faithful for label in labels],
            [verdicts[label.id].faithfulness >= 0.5 for label in labels],
        ),
        relevance_kappa=cohens_kappa(
            [label.human_relevant for label in labels],
            [verdicts[label.id].relevance >= 0.5 for label in labels],
        ),
    )


def render_calibration_markdown(agreements: Sequence[CalibrationAgreement]) -> str:
    lines = [
        "# Judge calibration",
        "",
        "Human labels are authored and reviewed separately from model verdicts.",
        "",
        "| Profile | Model | Prompt | Pairs | Faithfulness κ | Relevance κ |",
        "|---|---|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.judge_profile} | {item.judge_model} | {item.judge_prompt_version} | "
        f"{item.sample_count} | {item.faithfulness_kappa:.3f} | {item.relevance_kappa:.3f} |"
        for item in agreements
    )
    return "\n".join(lines) + "\n"


async def run_calibration(
    *,
    labels: Sequence[CalibrationLabel],
    renderer: VersionedJudgePromptRenderer,
    judges: Mapping[str, Judge],
) -> tuple[CalibrationAgreement, ...]:
    """Run each configured judge over the same independently authored labels."""
    if not labels:
        raise ValueError("calibration set cannot be empty")
    agreements: list[CalibrationAgreement] = []
    for profile, judge in judges.items():
        verdicts: dict[str, JudgeVerdict] = {}
        for label in labels:
            request = renderer.render_values(
                query=label.query,
                answer=label.answer,
                abstained=label.abstained,
                citations=label.citations,
                contexts=label.contexts,
                trace_id=f"calibration-{label.id}",
            )
            verdicts[label.id] = await judge.judge(request)
        agreements.append(
            compute_calibration_agreement(
                judge_profile=profile,
                labels=labels,
                verdicts=verdicts,
            )
        )
    return tuple(agreements)

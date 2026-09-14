"""Versioned, deterministic rendering for cited-answer prompts."""

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ragops.contracts import GenerationRequest, Passage

PROMPT_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
INVALID_XML_CHARACTER_PATTERN = re.compile(
    "[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def _reject_invalid_xml_characters(value: str, *, field_name: str) -> None:
    if INVALID_XML_CHARACTER_PATTERN.search(value) is not None:
        raise ValueError(f"{field_name} contains a character forbidden by XML 1.0")


@dataclass(frozen=True)
class VersionedAnswerPromptRenderer:
    """Load one reviewed system prompt and safely serialize dynamic inputs."""

    prompt_root: Path = Path("prompts/answer")
    version: str = "answer-v1"
    system_prompt: str = field(init=False)

    def __post_init__(self) -> None:
        if PROMPT_VERSION_PATTERN.fullmatch(self.version) is None:
            raise ValueError(f"invalid answer prompt version: {self.version!r}")
        prompt_path = self.prompt_root / self.version / "system.txt"
        try:
            system_prompt = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValueError(f"answer prompt version not found: {self.version!r}") from error
        if not system_prompt.strip():
            raise ValueError(f"answer system prompt is blank: {prompt_path}")
        object.__setattr__(self, "system_prompt", system_prompt)

    def render(
        self,
        *,
        query: str,
        contexts: Sequence[Passage],
        trace_id: str,
    ) -> GenerationRequest:
        """Render query and passages into an escaped, rank-stable XML document."""

        if not query.strip():
            raise ValueError("answer query cannot be blank")
        if len(query) > 4_096:
            raise ValueError("answer query cannot exceed 4096 characters")
        _reject_invalid_xml_characters(query, field_name="answer query")

        ordered_contexts = tuple(
            sorted(contexts, key=lambda passage: (passage.retrieval_rank, passage.local_id))
        )
        context_ids = [passage.local_id for passage in ordered_contexts]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("answer context local IDs must be unique")
        for passage in ordered_contexts:
            for field_name, value in (
                ("passage local_id", passage.local_id),
                ("passage document_id", passage.document_id),
                ("passage title", passage.title),
                ("passage text", passage.text),
            ):
                _reject_invalid_xml_characters(value, field_name=field_name)

        root = ElementTree.Element("answer_input")
        question = ElementTree.SubElement(root, "question", trust="untrusted")
        question.text = query
        passages = ElementTree.SubElement(root, "passages", trust="untrusted")
        for passage in ordered_contexts:
            passage_element = ElementTree.SubElement(
                passages,
                "passage",
                local_id=passage.local_id,
                document_id=passage.document_id,
                retrieval_rank=str(passage.retrieval_rank),
                retrieval_score=format(passage.retrieval_score, ".17g"),
            )
            title = ElementTree.SubElement(passage_element, "title")
            title.text = passage.title
            text = ElementTree.SubElement(passage_element, "text")
            text.text = passage.text

        return GenerationRequest(
            system_prompt=self.system_prompt,
            user_prompt=ElementTree.tostring(root, encoding="unicode", short_empty_elements=False),
            prompt_version=self.version,
            trace_id=trace_id,
        )

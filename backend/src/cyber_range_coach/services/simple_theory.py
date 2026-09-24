"""Theory written for a 10-12 year old reader (spec.md 11.3 Г).

The format is checked mechanically: short sentences, and every Latin word or
professional term is explained in ``words`` before the learner needs it.
Whether a text is actually clear is decided by the owner on sample lessons.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

MAX_WORDS_PER_SENTENCE = 15
MAX_PICTURE_LINES = 14

_CODE_SPAN = re.compile(r"`[^`]*`")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*")
_WORD = re.compile(r"[\w-]+", re.UNICODE)


class SimpleWord(BaseModel):
    # A comma lost in YAML turns half a meaning into a stray key; reject it.
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1)
    meaning: str = Field(min_length=1)


class SimpleTheory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analogy: str = Field(min_length=1)
    what_it_does: list[str] = Field(min_length=1, max_length=3)
    words: list[SimpleWord] = Field(default_factory=list)
    picture: str = Field(min_length=1)
    check_question: str = Field(min_length=1)
    check_answer: str = Field(min_length=1)


def _prose(theory: SimpleTheory) -> list[str]:
    texts = [theory.analogy, *theory.what_it_does, theory.check_question, theory.check_answer]
    texts += [word.meaning for word in theory.words]
    return texts


def simplicity_errors(theory: SimpleTheory) -> list[str]:
    """Return human-readable reasons why the text is not simple enough."""
    errors: list[str] = []
    explained = {word.term.strip("`").casefold() for word in theory.words}
    for text in _prose(theory):
        if "—" in text:
            errors.append(f"long dash in: {text[:40]}")
        plain = _CODE_SPAN.sub("код", text)
        for sentence in _SENTENCE_END.split(plain.strip()):
            count = len(_WORD.findall(sentence))
            if count > MAX_WORDS_PER_SENTENCE:
                errors.append(f"sentence has {count} words (max {MAX_WORDS_PER_SENTENCE}): {sentence[:50]}")
        for latin in _LATIN_WORD.findall(plain):
            if latin.casefold() not in explained:
                errors.append(f"word {latin!r} is not explained in words")
    if len(theory.picture.splitlines()) > MAX_PICTURE_LINES:
        errors.append(f"picture is longer than {MAX_PICTURE_LINES} lines")
    return errors

from __future__ import annotations

import shlex
from enum import StrEnum

from pydantic import BaseModel, Field


class RecallReason(StrEnum):
    correct = "correct"
    correct_with_help = "correct_with_help"
    wrong_tool = "wrong_tool"
    wrong_flag = "wrong_flag"
    wrong_shell = "wrong_shell"
    insufficient_data = "insufficient_data"


class PermutableAnswer(BaseModel):
    prefix: list[str] = Field(min_length=1)
    groups: list[list[str]] = Field(min_length=2)
    suffix: list[str] = Field(default_factory=list)


class RecallContract(BaseModel):
    shell: str
    expected_tool: str
    accepted_answers: list[str] = Field(min_length=1)
    significant_flags: list[str] = Field(default_factory=list)
    permutable_answers: list[PermutableAnswer] = Field(default_factory=list)
    other_shell_tools: list[str] = Field(default_factory=list)


class RecallGrade(BaseModel):
    reason: RecallReason
    correct: bool
    independent: bool


def _tokens(value: str) -> list[str] | None:
    try:
        return shlex.split(value, posix=True)
    except ValueError:
        return None


def _matches_permutable(tokens: list[str], contract: PermutableAnswer) -> bool:
    if tokens[: len(contract.prefix)] != contract.prefix:
        return False
    if contract.suffix and tokens[-len(contract.suffix) :] != contract.suffix:
        return False
    start = len(contract.prefix)
    stop = len(tokens) - len(contract.suffix) if contract.suffix else len(tokens)
    middle = tokens[start:stop]
    remaining = [tuple(group) for group in contract.groups]
    cursor = 0
    while cursor < len(middle):
        matched_index: int | None = None
        for index, group in enumerate(remaining):
            if tuple(middle[cursor : cursor + len(group)]) == group:
                matched_index = index
                cursor += len(group)
                break
        if matched_index is None:
            return False
        remaining.pop(matched_index)
    return not remaining


def grade_recall(
    answer: str | None,
    answer_shell: str,
    contract: RecallContract,
    revealed_help: list[int],
    *,
    dont_remember: bool = False,
) -> RecallGrade:
    if answer_shell != contract.shell:
        return RecallGrade(
            reason=RecallReason.wrong_shell,
            correct=False,
            independent=False,
        )
    if dont_remember or answer is None or answer == "":
        return RecallGrade(
            reason=RecallReason.insufficient_data,
            correct=False,
            independent=False,
        )
    if answer in contract.accepted_answers:
        reason = RecallReason.correct_with_help if revealed_help else RecallReason.correct
        return RecallGrade(reason=reason, correct=True, independent=not revealed_help)
    answer_tokens = _tokens(answer)
    if answer_tokens is None or not answer_tokens:
        return RecallGrade(
            reason=RecallReason.insufficient_data,
            correct=False,
            independent=False,
        )
    if answer_tokens[0].casefold() in {
        tool.casefold() for tool in contract.other_shell_tools
    }:
        return RecallGrade(
            reason=RecallReason.wrong_shell,
            correct=False,
            independent=False,
        )
    if any(_matches_permutable(answer_tokens, item) for item in contract.permutable_answers):
        reason = RecallReason.correct_with_help if revealed_help else RecallReason.correct
        return RecallGrade(reason=reason, correct=True, independent=not revealed_help)
    accepted_tokens = [_tokens(item) for item in contract.accepted_answers]
    accepted_tools = {item[0] for item in accepted_tokens if item}
    if answer_tokens[0] not in accepted_tools and answer_tokens[0] != contract.expected_tool:
        return RecallGrade(
            reason=RecallReason.wrong_tool,
            correct=False,
            independent=False,
        )
    answer_flags = {item for item in answer_tokens if item.startswith("-")}
    if not set(contract.significant_flags).issubset(answer_flags):
        return RecallGrade(
            reason=RecallReason.wrong_flag,
            correct=False,
            independent=False,
        )
    expected_flags = {
        token
        for tokens in accepted_tokens
        if tokens
        for token in tokens
        if token.startswith("-")
    }
    if answer_flags != expected_flags:
        return RecallGrade(
            reason=RecallReason.wrong_flag,
            correct=False,
            independent=False,
        )
    return RecallGrade(
        reason=RecallReason.insufficient_data,
        correct=False,
        independent=False,
    )


def grade_observation(answer: str, expected_concepts: list[list[str]]) -> bool:
    if not answer.strip():
        return False
    folded = answer.casefold()
    return all(any(option.casefold() in folded for option in options) for options in expected_concepts)

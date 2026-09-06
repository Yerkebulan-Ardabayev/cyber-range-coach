from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Shell = Literal["bash", "cmd"]
VerificationStatus = Literal["verified", "unverified"]
ComparisonMode = Literal["exact", "exact_or_permuted"]


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
    shell: Shell
    expected_tool: str
    accepted_answers: list[str] = Field(min_length=1)
    significant_flags: list[str] = Field(default_factory=list)
    permutable_answers: list[PermutableAnswer] = Field(default_factory=list)
    other_shell_tools: list[str] = Field(default_factory=list)
    comparison_mode: ComparisonMode = "exact"


class RecallGrade(BaseModel):
    reason: RecallReason
    correct: bool
    independent: bool
    verification_status: VerificationStatus = "verified"
    detail: str


def _cmd_tokens(value: str) -> list[str] | None:
    """Split a cmd.exe command line.

    cmd.exe has no backslash escape, so posix splitting would silently eat the
    separators in ``C:\\lab\\file.txt``. A double quote toggles quoted state and
    stays in the token, because quoting is significant when the answer is read.
    """
    tokens: list[str] = []
    current: list[str] = []
    quoted = False
    started = False
    for char in value:
        if char == '"':
            quoted = not quoted
            started = True
            current.append(char)
        elif char.isspace() and not quoted:
            if started:
                tokens.append("".join(current))
                current = []
                started = False
        else:
            started = True
            current.append(char)
    if quoted:
        return None
    if started:
        tokens.append("".join(current))
    return tokens


def _bash_tokens(value: str) -> list[str] | None:
    """Return conservative Bash lexical units without interpreting them.

    Quote characters, backslashes, expansions, glob markers, and operators stay
    in the returned text. This is intentionally not a shell parser. It only
    permits safe comparison of forms the challenge explicitly declared.
    """
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0

    def finish() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    while index < len(value):
        char = value[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            current.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char.isspace():
            finish()
            index += 1
            continue
        if char in {"|", "&", ";", "<", ">"}:
            finish()
            operator = char
            if index + 1 < len(value) and value[index + 1] == char:
                operator += char
                index += 1
            tokens.append(operator)
            index += 1
            continue
        current.append(char)
        index += 1
    if quote or escaped:
        return None
    finish()
    return tokens


def _tokens(value: str, shell: str) -> list[str] | None:
    if shell == "cmd":
        return _cmd_tokens(value)
    return _bash_tokens(value)


def _flag_prefix(shell: str) -> str:
    return "/" if shell == "cmd" else "-"


def _normalize_flag(token: str, shell: str) -> str:
    """Fold the switch letter of a cmd.exe flag, keep its argument as typed.

    cmd.exe switches are case insensitive, so ``/B`` is not a learner error.
    The text after the colon is the search pattern and stays case sensitive,
    because findstr matches its pattern case sensitively by default. Operands
    are left untouched: only tokens that start with the switch prefix are folded.
    """
    if shell != "cmd" or not token.startswith(_flag_prefix(shell)):
        return token
    head, separator, tail = token.partition(":")
    return head.casefold() + separator + tail


def _normalize_tool(token: str, shell: str) -> str:
    return token.casefold() if shell == "cmd" else token


def _significant_present(flag: str, answer_flags: set[str]) -> bool:
    """A switch written as ``/c:`` requires the switch, whatever argument follows."""
    if flag in answer_flags:
        return True
    return flag.endswith(":") and any(item.startswith(flag) for item in answer_flags)


def _normalize_line(tokens: list[str], shell: str) -> list[str]:
    """Normalize a whole command line: tool name first, then every switch."""
    folded = [_normalize_flag(token, shell) for token in tokens]
    if folded:
        folded[0] = _normalize_tool(folded[0], shell)
    return folded


def _matches_permutable(tokens: list[str], contract: PermutableAnswer, shell: str) -> bool:
    """Order independent match. cmd.exe switch case is folded on both sides."""
    tokens = _normalize_line(tokens, shell)
    prefix = _normalize_line(contract.prefix, shell)
    suffix = [_normalize_flag(token, shell) for token in contract.suffix]

    if tokens[: len(prefix)] != prefix:
        return False
    if suffix and tokens[-len(suffix) :] != suffix:
        return False
    start = len(prefix)
    stop = len(tokens) - len(suffix) if suffix else len(tokens)
    middle = tokens[start:stop]
    remaining = [
        tuple(_normalize_flag(token, shell) for token in group) for group in contract.groups
    ]
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
            detail="Ответ введён для другой оболочки.",
        )
    if dont_remember or answer is None or answer == "":
        return RecallGrade(
            reason=RecallReason.insufficient_data,
            correct=False,
            independent=False,
            detail="Ответ не указан. Попытка сохранена как обычное повторение.",
        )
    if answer in contract.accepted_answers:
        reason = RecallReason.correct_with_help if revealed_help else RecallReason.correct
        return RecallGrade(
            reason=reason,
            correct=True,
            independent=not revealed_help,
            detail="Команда совпала с явно допустимой формой.",
        )
    shell = contract.shell
    answer_tokens = _tokens(answer, shell)
    if answer_tokens is None or not answer_tokens:
        return RecallGrade(
            reason=RecallReason.insufficient_data,
            correct=False,
            independent=False,
            detail="Строка содержит незавершённые кавычки или экранирование.",
        )
    if answer_tokens[0].casefold() in {tool.casefold() for tool in contract.other_shell_tools}:
        return RecallGrade(
            reason=RecallReason.wrong_shell,
            correct=False,
            independent=False,
            detail="Инструмент относится к другой оболочке.",
        )
    if contract.comparison_mode == "exact_or_permuted" and any(
        _matches_permutable(answer_tokens, item, shell) for item in contract.permutable_answers
    ):
        reason = RecallReason.correct_with_help if revealed_help else RecallReason.correct
        return RecallGrade(
            reason=reason,
            correct=True,
            independent=not revealed_help,
            detail="Команда совпала с явно разрешённой перестановкой групп.",
        )
    accepted_tokens = [_tokens(item, shell) for item in contract.accepted_answers]
    normalized_answer = _normalize_line(answer_tokens, shell)
    if any(
        tokens is not None and _normalize_line(tokens, shell) == normalized_answer
        for tokens in accepted_tokens
    ):
        reason = RecallReason.correct_with_help if revealed_help else RecallReason.correct
        return RecallGrade(
            reason=reason,
            correct=True,
            independent=not revealed_help,
            detail="Команда совпала с явно допустимой лексической формой.",
        )
    accepted_tools = {_normalize_tool(item[0], shell) for item in accepted_tokens if item}
    answer_tool = _normalize_tool(answer_tokens[0], shell)
    if answer_tool not in accepted_tools and answer_tool != _normalize_tool(
        contract.expected_tool, shell
    ):
        return RecallGrade(
            reason=RecallReason.wrong_tool,
            correct=False,
            independent=False,
            detail="Первое слово не совпадает с инструментом задания.",
        )
    prefix = _flag_prefix(shell)
    answer_flags = {
        _normalize_flag(item, shell) for item in answer_tokens if item.startswith(prefix)
    }
    significant = {_normalize_flag(item, shell) for item in contract.significant_flags}
    if not all(_significant_present(item, answer_flags) for item in significant):
        return RecallGrade(
            reason=RecallReason.wrong_flag,
            correct=False,
            independent=False,
            detail="Отсутствует обязательный флаг задания.",
        )
    expected_flags = {
        _normalize_flag(token, shell)
        for tokens in accepted_tokens
        if tokens
        for token in tokens
        if token.startswith(prefix)
    }
    if answer_flags != expected_flags:
        return RecallGrade(
            reason=RecallReason.wrong_flag,
            correct=False,
            independent=False,
            detail="Набор значимых флагов отличается от контракта задания.",
        )
    return RecallGrade(
        reason=RecallReason.insufficient_data,
        correct=False,
        independent=False,
        verification_status="unverified",
        detail="Этот вариант пока не поддерживается автоматической проверкой.",
    )


def grade_observation(answer: str, expected_concepts: list[list[str]]) -> bool:
    if not answer.strip():
        return False
    folded = answer.casefold()
    return all(
        any(option.casefold() in folded for option in options) for options in expected_concepts
    )

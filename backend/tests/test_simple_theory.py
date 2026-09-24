from __future__ import annotations

from cyber_range_coach.services.simple_theory import SimpleTheory, simplicity_errors


def _theory(**changes: object) -> SimpleTheory:
    base: dict[str, object] = {
        "analogy": "Команда `pwd` отвечает, в какой комнате ты стоишь.",
        "what_it_does": ["Команда печатает адрес папки."],
        "words": [{"term": "pwd", "meaning": "Покажи рабочую папку."}],
        "picture": "/home/student",
        "check_question": "С какого знака начинается адрес?",
        "check_answer": "С косой черты.",
    }
    base.update(changes)
    return SimpleTheory.model_validate(base)


def test_simple_text_passes() -> None:
    assert simplicity_errors(_theory()) == []


def test_long_sentence_is_rejected() -> None:
    long_sentence = " ".join(["слово"] * 16) + "."
    errors = simplicity_errors(_theory(what_it_does=[long_sentence]))
    assert any("16 words" in error for error in errors)


def test_unexplained_latin_word_is_rejected_outside_code() -> None:
    errors = simplicity_errors(_theory(check_answer="Это делает shell."))
    assert any("'shell'" in error for error in errors)
    assert simplicity_errors(_theory(check_answer="Это делает `shell`.")) == []


def test_long_dash_is_rejected() -> None:
    errors = simplicity_errors(_theory(analogy="Папка — это комната."))
    assert any("long dash" in error for error in errors)


def test_course_pilot_lessons_are_simple(client) -> None:
    lessons = client.app.state.curriculum.ordered_lessons()
    with_theory = [lesson for lesson in lessons if lesson.simple_theory is not None]
    assert len(with_theory) >= 5
    for lesson in with_theory:
        assert lesson.simple_theory is not None
        assert simplicity_errors(lesson.simple_theory) == [], lesson.id

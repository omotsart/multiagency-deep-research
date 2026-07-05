"""Детерминированная склейка брифа: тема + уточняющие Q&A → единый бриф.

Бриф — единый источник намерения для всего пайплайна (см. CLAUDE.md, Зона 1).
Функция чистая: без вызовов LLM, без обращения к окружению, без побочных эффектов.
Одинаковый вход → одинаковый выход. Это делает её пригодной для юнит-тестов контракта.
"""

from collections.abc import Sequence


def build_brief(topic: str, questions: Sequence[str], answers: Sequence[str]) -> str:
    """Склеить тему и пары вопрос/ответ в единый текстовый бриф.

    Args:
        topic: исходная тема исследования от пользователя.
        questions: уточняющие вопросы (от clarifier).
        answers: ответы пользователя, по одному на каждый вопрос (по позиции).

    Returns:
        Единая строка-бриф с темой и пронумерованными парами Q&A.

    Raises:
        ValueError: если тема пустая или число вопросов и ответов не совпадает.
    """
    topic = topic.strip()
    if not topic:
        raise ValueError("topic must be a non-empty string")

    if len(questions) != len(answers):
        raise ValueError(
            f"questions and answers must be the same length: "
            f"{len(questions)} != {len(answers)}"
        )

    lines = [f"Research topic: {topic}"]

    if questions:
        lines.append("")
        lines.append("Clarifying Q&A:")
        for i, (question, answer) in enumerate(zip(questions, answers), start=1):
            question = question.strip()
            answer = answer.strip() or "(no answer provided)"
            lines.append(f"{i}. Q: {question}")
            lines.append(f"   A: {answer}")

    return "\n".join(lines)

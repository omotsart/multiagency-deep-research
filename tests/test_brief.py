"""Юнит-тесты детерминированной склейки брифа (Gate 1).

Тестируем контракт функции build_brief, а не текст/качество вопросов.
Никаких вызовов LLM/OpenAI.
"""

import pytest

from brief import build_brief


def test_topic_appears_in_brief():
    brief = build_brief("Impact of AI on jobs", [], [])
    assert "Research topic: Impact of AI on jobs" in brief


def test_questions_and_answers_are_paired_in_order():
    questions = ["Which industry?", "What timeframe?", "Which region?"]
    answers = ["Healthcare", "Next 5 years", "Europe"]
    brief = build_brief("AI adoption", questions, answers)

    for i, (q, a) in enumerate(zip(questions, answers), start=1):
        assert f"{i}. Q: {q}" in brief
        assert f"   A: {a}" in brief


def test_topic_and_answers_are_stripped():
    brief = build_brief("  spaced topic  ", ["  q1  "], ["  a1  "])
    assert "Research topic: spaced topic" in brief
    assert "1. Q: q1" in brief
    assert "   A: a1" in brief


def test_empty_answer_gets_placeholder():
    brief = build_brief("topic", ["q1"], ["   "])
    assert "(no answer provided)" in brief


def test_no_questions_yields_topic_only():
    brief = build_brief("just a topic", [], [])
    assert brief == "Research topic: just a topic"


def test_deterministic_same_input_same_output():
    args = ("topic", ["q1", "q2"], ["a1", "a2"])
    assert build_brief(*args) == build_brief(*args)


def test_empty_topic_raises():
    with pytest.raises(ValueError):
        build_brief("   ", [], [])


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        build_brief("topic", ["q1", "q2"], ["only one answer"])

"""Юнит-тесты Pydantic-схемы вопросов clarifier (Gate 1).

Проверяем контракт схемы: ровно NUM_QUESTIONS вопросов. Не проверяем
качество/«умность» вопросов (RULES §4) и не вызываем LLM/OpenAI.
"""

import pytest
from pydantic import ValidationError

from clarifier_agent import ClarifyingQuestions, NUM_QUESTIONS


def test_num_questions_is_three():
    assert NUM_QUESTIONS == 3


def test_exactly_three_questions_is_valid():
    model = ClarifyingQuestions(questions=["q1", "q2", "q3"])
    assert len(model.questions) == NUM_QUESTIONS


def test_too_few_questions_rejected():
    with pytest.raises(ValidationError):
        ClarifyingQuestions(questions=["q1", "q2"])


def test_too_many_questions_rejected():
    with pytest.raises(ValidationError):
        ClarifyingQuestions(questions=["q1", "q2", "q3", "q4"])

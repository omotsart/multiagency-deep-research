"""Юнит-тесты Pydantic-схемы плана поисков планировщика (под-gate 2a).

Проверяем контракт схемы WebSearchPlan / WebSearchItem: обязательность полей
reason/query, что searches — список из элементов схемы. Не проверяем
качество/«умность» плана (RULES §4) и не вызываем LLM/OpenAI.
"""

import pytest
from pydantic import ValidationError

from planner_agent import WebSearchItem, WebSearchPlan


def test_valid_plan_with_items_builds():
    plan = WebSearchPlan(
        searches=[
            WebSearchItem(reason="охватить контекст", query="topic overview 2026"),
            WebSearchItem(reason="свежие данные", query="topic latest statistics"),
        ]
    )
    assert isinstance(plan.searches, list)
    assert len(plan.searches) == 2
    assert all(isinstance(item, WebSearchItem) for item in plan.searches)


def test_empty_searches_list_is_valid_schema():
    # Схема допускает пустой список — «умность»/минимум плана не наша забота (RULES §4).
    plan = WebSearchPlan(searches=[])
    assert plan.searches == []


def test_item_requires_query():
    with pytest.raises(ValidationError):
        WebSearchItem(reason="есть причина, но нет запроса")


def test_item_requires_reason():
    with pytest.raises(ValidationError):
        WebSearchItem(query="есть запрос, но нет причины")


def test_plan_requires_searches_field():
    with pytest.raises(ValidationError):
        WebSearchPlan()


def test_searches_must_be_list_not_scalar():
    with pytest.raises(ValidationError):
        WebSearchPlan(searches=WebSearchItem(reason="r", query="q"))

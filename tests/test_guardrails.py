"""Юнит-тесты предохранителей автономности (под-gate 2d, D-03).

Тестируем детерминированную обвязку (RULES §4): счётчик бюджета поисков,
контролируемый отказ поискового инструмента при исчерпании, граничные случаи,
наличие константы MAX_TURNS. Runner.run замокан — сети/LLM нет (D-06).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import search_agent
from guardrails import (
    DEFAULT_SEARCH_BUDGET,
    MAX_TURNS,
    ResearchContext,
)
from planner_agent import WebSearchItem, WebSearchPlan


def _plan(n: int) -> WebSearchPlan:
    return WebSearchPlan(
        searches=[WebSearchItem(reason=f"r{i}", query=f"q{i}") for i in range(n)]
    )


def _fake_run():
    async def fake_run(agent, input, *args, **kwargs):
        term = input.split("Search term: ", 1)[1].split("\n", 1)[0]
        return SimpleNamespace(final_output=f"summary for {term}")

    return fake_run


# --- ResearchContext: счётчик и остаток ---------------------------------------

def test_default_budget_and_zero_used():
    ctx = ResearchContext()
    assert ctx.search_budget == DEFAULT_SEARCH_BUDGET
    assert ctx.searches_used == 0
    assert ctx.searches_remaining == DEFAULT_SEARCH_BUDGET
    assert not ctx.is_exhausted


def test_spend_increments_counter_and_reduces_remaining():
    ctx = ResearchContext(search_budget=5)
    ctx.spend(2)
    assert ctx.searches_used == 2
    assert ctx.searches_remaining == 3
    ctx.spend(1)
    assert ctx.searches_used == 3
    assert ctx.searches_remaining == 2


def test_remaining_never_negative_and_exhausted_flag():
    ctx = ResearchContext(search_budget=2)
    ctx.spend(2)
    assert ctx.searches_remaining == 0
    assert ctx.is_exhausted


def test_spend_negative_raises():
    ctx = ResearchContext(search_budget=5)
    with pytest.raises(ValueError):
        ctx.spend(-1)


# --- Поисковый инструмент под бюджетом ----------------------------------------

@pytest.mark.asyncio
async def test_searches_run_and_debit_budget_below_limit():
    ctx = ResearchContext(search_budget=5)
    with patch.object(search_agent.Runner, "run", side_effect=_fake_run()) as mock_run:
        outcome = await search_agent.run_searches_with_budget(ctx, _plan(3))

    assert not outcome.refused
    assert len(outcome.summaries) == 3
    assert mock_run.call_count == 3          # поиск реально выполнялся
    assert ctx.searches_used == 3            # счётчик списан по числу попыток
    assert ctx.searches_remaining == 2


@pytest.mark.asyncio
async def test_tool_refuses_when_budget_exhausted():
    ctx = ResearchContext(search_budget=2)
    ctx.spend(2)  # бюджет исчерпан
    with patch.object(search_agent.Runner, "run", side_effect=_fake_run()) as mock_run:
        outcome = await search_agent.run_searches_with_budget(ctx, _plan(3))

    assert outcome.refused
    assert outcome.summaries == []
    assert "SEARCH_BUDGET_EXHAUSTED" in outcome.message
    mock_run.assert_not_called()             # поиск НЕ выполнялся
    assert ctx.searches_used == 2            # счётчик не тронут отказом


@pytest.mark.asyncio
async def test_boundary_exactly_at_limit_then_next_call_refused():
    # Ровно на лимите: первый вызов расходует остаток целиком, второй — отказ.
    ctx = ResearchContext(search_budget=3)
    with patch.object(search_agent.Runner, "run", side_effect=_fake_run()) as mock_run:
        first = await search_agent.run_searches_with_budget(ctx, _plan(3))
        assert not first.refused
        assert len(first.summaries) == 3
        assert ctx.is_exhausted
        assert mock_run.call_count == 3

        second = await search_agent.run_searches_with_budget(ctx, _plan(1))

    assert second.refused
    assert mock_run.call_count == 3          # второй вызов не добавил поисков


@pytest.mark.asyncio
async def test_batch_larger_than_remaining_is_capped():
    ctx = ResearchContext(search_budget=5)
    ctx.spend(3)  # остаток 2
    with patch.object(search_agent.Runner, "run", side_effect=_fake_run()) as mock_run:
        outcome = await search_agent.run_searches_with_budget(ctx, _plan(4))

    assert not outcome.refused
    assert len(outcome.summaries) == 2       # выполнено только по остатку
    assert mock_run.call_count == 2
    assert ctx.searches_used == 5
    assert ctx.is_exhausted
    assert "SEARCH_BUDGET_PARTIAL" in outcome.message


@pytest.mark.asyncio
async def test_failed_search_still_consumes_budget():
    # Упавший поиск тоже тратит попытку: счётчик по числу запрошенных, не успешных.
    ctx = ResearchContext(search_budget=5)

    async def fake_run(agent, input, *args, **kwargs):
        term = input.split("Search term: ", 1)[1].split("\n", 1)[0]
        if term == "q1":
            raise RuntimeError("boom")
        return SimpleNamespace(final_output=f"summary for {term}")

    with patch.object(search_agent.Runner, "run", side_effect=fake_run):
        outcome = await search_agent.run_searches_with_budget(ctx, _plan(3))

    assert len(outcome.summaries) == 2       # одна сводка потеряна
    assert ctx.searches_used == 3            # но бюджет списан за все 3 попытки


# --- max_turns (подключается на Gate 3) ---------------------------------------

def test_max_turns_constant_is_positive_int():
    # Потолок ходов задаётся в Runner.run(manager, ..., max_turns=MAX_TURNS) на
    # Gate 3; здесь проверяем, что готовая константа существует и осмысленна.
    assert isinstance(MAX_TURNS, int)
    assert MAX_TURNS > 0

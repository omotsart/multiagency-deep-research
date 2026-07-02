"""Юнит-тесты обёртки параллельного поиска (под-gate 2b).

Проверяем оркестрацию, не «умность» поиска (RULES §4): N поисков → N сводок;
устойчивость (упавший поиск не рушит пачку); сбор корректен. Runner.run
замокан — реальную сеть/LLM не трогаем (D-06).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import search_agent
from planner_agent import WebSearchItem, WebSearchPlan


def _plan(*queries: str) -> WebSearchPlan:
    return WebSearchPlan(
        searches=[WebSearchItem(reason=f"reason {q}", query=q) for q in queries]
    )


@pytest.mark.asyncio
async def test_n_searches_yield_n_summaries():
    plan = _plan("q1", "q2", "q3")

    # Мок Runner.run: сводка = "summary for <search term>", вытащенная из input.
    async def fake_run(agent, input, *args, **kwargs):
        term = input.split("Search term: ", 1)[1].split("\n", 1)[0]
        return SimpleNamespace(final_output=f"summary for {term}")

    with patch.object(search_agent.Runner, "run", side_effect=fake_run):
        results = await search_agent.perform_parallel_searches(plan)

    assert len(results) == 3
    # as_completed не гарантирует порядок → сверяем как множество (сбор корректен).
    assert set(results) == {"summary for q1", "summary for q2", "summary for q3"}


@pytest.mark.asyncio
async def test_one_failing_search_does_not_break_the_batch():
    plan = _plan("ok1", "boom", "ok2")

    async def fake_run(agent, input, *args, **kwargs):
        term = input.split("Search term: ", 1)[1].split("\n", 1)[0]
        if term == "boom":
            raise RuntimeError("search backend exploded")
        return SimpleNamespace(final_output=f"summary for {term}")

    with patch.object(search_agent.Runner, "run", side_effect=fake_run):
        results = await search_agent.perform_parallel_searches(plan)

    # Пачка не упала: вернулись N-1 сводок, упавший поиск пропущен.
    assert len(results) == 2
    assert set(results) == {"summary for ok1", "summary for ok2"}


@pytest.mark.asyncio
async def test_empty_plan_yields_empty_list():
    with patch.object(search_agent.Runner, "run", new=AsyncMock()) as mock_run:
        results = await search_agent.perform_parallel_searches(_plan())

    assert results == []
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_runner_called_once_per_search_item():
    plan = _plan("a", "b", "c", "d")

    async def fake_run(agent, input, *args, **kwargs):
        return SimpleNamespace(final_output="ok")

    with patch.object(search_agent.Runner, "run", side_effect=fake_run) as mock_run:
        results = await search_agent.perform_parallel_searches(plan)

    assert len(results) == 4
    assert mock_run.call_count == 4

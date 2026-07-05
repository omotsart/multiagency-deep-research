"""Юнит-тесты обёртки параллельного поиска (под-gate 2b).

Проверяем оркестрацию, не «умность» поиска (RULES §4): N поисков → N сводок;
устойчивость (упавший поиск не рушит пачку); сбор корректен. Runner.run
замокан общим слоем (_mocks.search_run) — реальную сеть/LLM не трогаем (D-06).
"""

from unittest.mock import AsyncMock, patch

import pytest

import search_agent
from planner_agent import WebSearchPlan
from _mocks import make_plan, search_run


@pytest.mark.asyncio
async def test_n_searches_yield_n_summaries():
    plan = make_plan("q1", "q2", "q3")

    with patch.object(search_agent.Runner, "run", side_effect=search_run()):
        results = await search_agent.perform_parallel_searches(plan)

    assert len(results) == 3
    # as_completed не гарантирует порядок → сверяем как множество (сбор корректен).
    assert set(results) == {"summary for q1", "summary for q2", "summary for q3"}


@pytest.mark.asyncio
async def test_one_failing_search_does_not_break_the_batch():
    plan = make_plan("ok1", "boom", "ok2")

    with patch.object(search_agent.Runner, "run", side_effect=search_run(fail_on=["boom"])):
        results = await search_agent.perform_parallel_searches(plan)

    # Пачка не упала: вернулись N-1 сводок, упавший поиск пропущен.
    assert len(results) == 2
    assert set(results) == {"summary for ok1", "summary for ok2"}


@pytest.mark.asyncio
async def test_empty_plan_yields_empty_list():
    with patch.object(search_agent.Runner, "run", new=AsyncMock()) as mock_run:
        results = await search_agent.perform_parallel_searches(WebSearchPlan(searches=[]))

    assert results == []
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_runner_called_once_per_search_item():
    plan = make_plan("a", "b", "c", "d")

    with patch.object(search_agent.Runner, "run", side_effect=search_run()) as mock_run:
        results = await search_agent.perform_parallel_searches(plan)

    assert len(results) == 4
    assert mock_run.call_count == 4

"""Юнит-тест соблюдения бюджета менеджером через рантайм (под-gate 3b, D-03).

Критерий Gate 3 дословно: «менеджер уважает бюджет поисков (не превышает лимит)».

Бюджет физически энфорсит КОД (run_searches_with_budget + ResearchContext), а не
LLM. Поэтому тест детерминированный и не проверяет решений менеджера (сколько
волн, какие запросы — недетерминированны, RULES §4). Проверяется ИНВАРИАНТ:
какой бы жадной ни была стратегия менеджера, фактически выполнено не больше
бюджета.

Механика: заменяем модель менеджера сценарием «рвусь за лимит» — прогоняем волну
за волной, суммарно запрашивая больше DEFAULT_SEARCH_BUDGET. Сценарий дёргает тот
же предохранитель-ядро (run_searches_with_budget), который оборачивает боевой
инструмент run_parallel_searches (search_agent.py: outcome = await
run_searches_with_budget(wrapper.context, plan)), и делит ОДИН ResearchContext,
созданный внутри run_research. Так тест заодно доказывает, что предохранители
реально подключены к рантайму (context + max_turns), а не лежат мёртвым кодом.

Реального извлечения выводов .as_tool() тут нет → DEFERRED #4 не задевается
(он про оживление E2E на 3c). Мок LLM, без ключа (D-06).
"""

from types import SimpleNamespace

import pytest

import search_agent
from guardrails import DEFAULT_SEARCH_BUDGET, MAX_TURNS, ResearchContext
from writer_agent import ReportData
from _mocks import make_plan, make_report, term_from_input


def _result(output):
    """Мини-двойник RunResult: .final_output + .final_output_as(...)."""
    return SimpleNamespace(final_output=output, final_output_as=lambda _cls: output)


@pytest.mark.asyncio
async def test_run_research_respects_search_budget(monkeypatch):
    from agents import Runner
    from run_research import run_research

    WAVE = 4
    # Гарантированный перебор: сумма запрошенных поисков заведомо больше бюджета.
    N_WAVES = DEFAULT_SEARCH_BUDGET // WAVE + 3
    captured: dict = {}

    async def scripted_run(agent, input, *args, **kwargs):
        name = getattr(agent, "name", "")

        # Менеджера подменяем сценарием: он жадно гоняет волны поиска через тот же
        # общий ResearchContext, что создал run_research, и рвётся за лимит.
        if name == "ManagerAgent":
            captured["context"] = kwargs.get("context")
            captured["max_turns"] = kwargs.get("max_turns")
            ctx = kwargs["context"]
            requested = 0
            executed = 0
            for w in range(N_WAVES):
                plan = make_plan(*[f"w{w}_{i}" for i in range(WAVE)])
                requested += WAVE
                outcome = await search_agent.run_searches_with_budget(ctx, plan)
                executed += len(outcome.summaries)
            captured["requested"] = requested
            captured["executed"] = executed
            return _result(make_report())

        # Одиночные поиски внутри run_searches_with_budget → канонические сводки.
        if name == "Search agent":
            return _result(f"summary for {term_from_input(input)}")

        raise AssertionError(f"неожиданный агент в тесте бюджета: {name!r}")

    monkeypatch.setattr(Runner, "run", scripted_run)

    report = await run_research("бриф: тест соблюдения бюджета")

    # run_research собрал результат-контракт (структуру, не содержание).
    assert isinstance(report, ReportData)

    # Предохранители реально подключены к рантайму.
    ctx = captured["context"]
    assert isinstance(ctx, ResearchContext)
    assert captured["max_turns"] == MAX_TURNS

    # Сценарий действительно пытался превысить лимит...
    assert captured["requested"] > DEFAULT_SEARCH_BUDGET

    # ...но инвариант держится: выполнено не больше бюджета.
    assert ctx.searches_used <= ctx.search_budget
    assert ctx.searches_used == DEFAULT_SEARCH_BUDGET
    assert captured["executed"] <= DEFAULT_SEARCH_BUDGET
    assert ctx.is_exhausted

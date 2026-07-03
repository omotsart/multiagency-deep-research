"""Юнит-тест подъёма ResearchContext в run_research (под-шаг 5-pre-b, D-13.1).

Критерий 5-pre-b: run_research принимает необязательный `context` и, если он
передан, использует ИМЕННО его — бюджет/счётчик поисков списываются в переданный
контекст, а не в свежесозданный. Это техническая основа per-loop (D-13.1): будущая
петля-генератор (5-pre-c) передаст ОДИН ResearchContext на весь запрос, чтобы
бюджет был общим на все доработки, а счётчик поисков поднимался наружу для UI.

Сам per-loop здесь ещё НЕ включается (петля не тронута) — проверяется только
контракт сигнатуры ядра. Мок LLM, без ключа (D-06). Обратная совместимость
(вызов без аргумента → свежий контекст) держится существующими тестами без правок.
"""

from types import SimpleNamespace

import pytest

import search_agent
from guardrails import DEFAULT_SEARCH_BUDGET, ResearchContext
from writer_agent import ReportData
from _mocks import make_plan, make_report, term_from_input


def _result(output):
    """Мини-двойник RunResult: .final_output + .final_output_as(...)."""
    return SimpleNamespace(final_output=output, final_output_as=lambda _cls: output)


@pytest.mark.asyncio
async def test_run_research_uses_passed_context(monkeypatch):
    """Переданный context используется прогоном: поиски списываются в НЕГО."""
    from agents import Runner
    from run_research import run_research

    WAVE = 3
    passed_ctx = ResearchContext()
    captured: dict = {}

    async def scripted_run(agent, input, *args, **kwargs):
        name = getattr(agent, "name", "")

        if name == "ManagerAgent":
            captured["context"] = kwargs.get("context")
            ctx = kwargs["context"]
            plan = make_plan(*[f"q{i}" for i in range(WAVE)])
            await search_agent.run_searches_with_budget(ctx, plan)
            return _result(make_report())

        if name == "Search agent":
            return _result(f"summary for {term_from_input(input)}")

        raise AssertionError(f"неожиданный агент в тесте контекста: {name!r}")

    monkeypatch.setattr(Runner, "run", scripted_run)

    report = await run_research("бриф: тест подъёма контекста", context=passed_ctx)

    # Контракт трубы держится.
    assert isinstance(report, ReportData)

    # Прогон получил ИМЕННО переданный объект (тот же по identity, не свежий).
    assert captured["context"] is passed_ctx

    # Счётчик списан в переданный контекст, а не в свежесозданный.
    assert passed_ctx.searches_used == WAVE
    assert passed_ctx.searches_remaining == DEFAULT_SEARCH_BUDGET - WAVE

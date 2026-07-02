"""Скелет E2E happy-path: бриф → план → поиски → отчёт (под-gate 2e, D-06).

Контракт СБОРКИ трубы на моках, не качество текста (RULES §4). Оживает на Gate 3,
держится зелёным до конца; красный E2E = работа стоп, чиним контракт (RULES §4).

xfail(strict=True): связующего звена (manager_agent) ещё нет — тест ожидаемо
падает на импорте менеджера. Когда на Gate 3 труба соберётся и тест начнёт
проходить, strict=True превратит xpass в падение — это сигнал СНЯТЬ маркер,
а не переписать тест. Скелет намеренно написан под настоящий рантайм (CLAUDE.md:
Runner.run(manager, brief, context=ResearchContext(), max_turns=MAX_TURNS)).
"""

import pytest

from brief import build_brief
from guardrails import MAX_TURNS, ResearchContext
from writer_agent import ReportData


@pytest.mark.asyncio
@pytest.mark.xfail(reason="оркестратор (manager_agent) появится на Gate 3", strict=True)
async def test_e2e_happy_path_brief_to_report(mock_agent_runner):
    # 1. Бриф (Зона 1, детерминированная склейка — уже готова на Gate 1).
    brief = build_brief(
        topic="Влияние ИИ на рынок труда",
        questions=["Какой регион?", "Какой горизонт?", "Для кого отчёт?"],
        answers=["ЕС", "5 лет", "для инвесторов"],
    )

    # 2. Канонические выходы агентов (проверяем сборку, не содержание).
    from _mocks import make_plan, make_report

    mock_agent_runner.configure(
        plan=make_plan("q1", "q2", "q3"),
        report=make_report(),
    )

    # 3. Связующее звено появится на Gate 3 → сейчас ImportError → xfail.
    from agents import Runner
    from manager_agent import manager_agent  # noqa: E402  (создаётся на Gate 3)

    # 4. Прогон трубы через предохранители (D-03): бюджет + потолок ходов.
    result = await Runner.run(
        manager_agent,
        brief,
        context=ResearchContext(),
        max_turns=MAX_TURNS,
    )
    report = result.final_output_as(ReportData)

    # 5. Контракт результата — структура ReportData, не качество текста.
    assert isinstance(report, ReportData)
    assert report.short_summary
    assert report.markdown_report
    assert isinstance(report.follow_up_questions, list)

    # 6. Труба реально прошла план → поиск → отчёт (сборка, а не заглушка).
    assert mock_agent_runner.ran("PlannerAgent")
    assert mock_agent_runner.ran("Search agent")
    assert mock_agent_runner.ran("WriterAgent")

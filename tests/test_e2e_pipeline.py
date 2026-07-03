"""E2E happy-path: бриф → менеджер (план→поиск→писатель) → evaluator-петля → отчёт.

Контракт СБОРКИ трубы на моках, не качество текста (RULES §4, D-06). Оживлён на
Gate 3 (труба через настоящий Runner + сценарная модель менеджера), расширен на
Gate 4 (4c): труба идёт через Зону 3 (evaluator-петля, D-02) поверх Зоны 2.
Мигрирован на 5-pre-d под контракт-генератор D-13: петля теперь `async`-генератор
`ProgressEvent` (D-13.2), а не `-> ReportData`. Держится зелёным до конца; красный
E2E = работа стоп, чиним контракт (RULES §4).

Два способа потребления петли — оба под E2E (реальные потребители D-13):
  * happy-path — через ДРЕНЕР `run_loop_to_report` (каноническая свёртка потока к
    отчёту; та же поверхность, что зовёт finalizer/UI). Проверяем, что труба реально
    прошла план → поиск → писатель → оценщик и вернула структурный ReportData.
  * revision-path — ИТЕРАЦИЕЙ потока напрямую (как будет делать UI): проверяем
    инвариант терминала (ровно один `final` с непустым отчётом), наблюдаемость
    итераций (события `evaluation` со score/feedback, D-13.2) и multi-round сборку
    (менеджер/оценщик по два прогона; доработка идёт через ТОТ ЖЕ per-loop ctx).

Сценарий happy-path: оценщик возвращает проходную оценку (score >= 7) на первой
итерации, петля завершается без доработок и отдаёт лучший ReportData.

Второй сценарий (с доработкой): первая оценка ниже порога (5) → петля гонит
доработку (_revision_brief → повторный run_research) → вторая оценка берёт порог
(8) → выход. Так проверяется multi-round путь сценарной модели менеджера (свежий
_step=0 на каждый диспатч), собранный по-настоящему, а не только рассуждением.
"""

import pytest

from brief import build_brief
from writer_agent import ReportData


@pytest.mark.asyncio
async def test_e2e_happy_path_brief_to_report(mock_agent_runner):
    # 1. Бриф (Зона 1, детерминированная склейка — уже готова на Gate 1).
    brief = build_brief(
        topic="Влияние ИИ на рынок труда",
        questions=["Какой регион?", "Какой горизонт?", "Для кого отчёт?"],
        answers=["ЕС", "5 лет", "для инвесторов"],
    )

    # 2. Канонические выходы агентов + проходная оценка (петля завершится на первой
    #    итерации без доработок). Проверяем сборку, не содержание.
    from _mocks import make_plan, make_report, make_evaluation

    mock_agent_runner.configure(
        plan=make_plan("q1", "q2", "q3"),
        report=make_report(),
        evaluation=make_evaluation(score=8),  # >= 7 → happy-path без доработок
    )

    # 3. Труба целиком через ДРЕНЕР петли (D-13): бриф → менеджер (план→поиск→писатель)
    #    → evaluator-петля (Зона 3, D-02) → терминал `final` → лучший ReportData.
    #    Дренер выбран для happy-path как каноническая свёртка потока к отчёту — та
    #    же поверхность, что зовут finalizer/UI; E2E проверяет реальный контракт
    #    потребления, а не тест-локальную итерацию. Предохранители подключены внутри
    #    run_research, который петля зовёт на каждый прогон.
    from evaluator_loop import run_loop_to_report

    report = await run_loop_to_report(brief)

    # 4. Контракт результата — структура лучшего ReportData, не качество текста.
    assert isinstance(report, ReportData)
    assert report.short_summary
    assert report.markdown_report
    assert isinstance(report.follow_up_questions, list)

    # 5. Труба реально прошла план → поиск → писатель → оценщик (сборка, а не заглушка).
    assert mock_agent_runner.ran("PlannerAgent")
    assert mock_agent_runner.ran("Search agent")
    assert mock_agent_runner.ran("WriterAgent")
    assert mock_agent_runner.ran("EvaluatorAgent")


@pytest.mark.asyncio
async def test_e2e_revision_path_fail_then_pass(mock_agent_runner, monkeypatch):
    """E2E с доработкой: непроходная оценка (5) → доработка → проходная (8) → выход.

    Гоняет multi-round путь: петля не берёт порог на первой оценке, зовёт
    _revision_brief → повторный run_research (менеджер собирается ЗАНОВО через
    мок-слой, свежий _step=0 сценарной модели), затем вторая оценка берёт порог.
    Труба потребляется ИТЕРАЦИЕЙ потока напрямую (как UI): проверяем инвариант
    терминала (ровно один `final` с непустым отчётом), наблюдаемость итераций
    (события `evaluation` со score/feedback, D-13.2) и что менеджер/оценщик
    отработали ПО ДВА раза (доработка через ТОТ ЖЕ per-loop ctx). Сборка, не
    качество (D-06); содержание feedback НЕ проверяем (RULES §4).
    """
    from agents import Runner
    from _mocks import make_plan, make_report, make_evaluation

    # 1. Бриф (Зона 1) — как в happy-path.
    brief = build_brief(
        topic="Влияние ИИ на рынок труда",
        questions=["Какой регион?", "Какой горизонт?", "Для кого отчёт?"],
        answers=["ЕС", "5 лет", "для инвесторов"],
    )
    mock_agent_runner.configure(plan=make_plan("q1", "q2", "q3"), report=make_report())

    # 2. Последовательность оценок 5 → 8 без новой инфраструктуры мок-слоя: тонкая
    #    тест-локальная обёртка над готовым диспетчером подставляет score по счётчику
    #    вызовов оценщика в существующее поле evaluation, затем делегирует в тот же
    #    dispatch (он и запишет вызов в .calls, и вернёт канон). Порог не зашит в мок —
    #    его берёт петля в коде (D-02).
    base_dispatch = mock_agent_runner.dispatch
    scores = iter([5, 8])

    async def dispatch_with_scored_eval(starting_agent=None, input=None, *args, **kwargs):
        if getattr(starting_agent, "name", "") == "EvaluatorAgent":
            mock_agent_runner.evaluation = make_evaluation(score=next(scores))
        return await base_dispatch(starting_agent, input, *args, **kwargs)

    monkeypatch.setattr(Runner, "run", dispatch_with_scored_eval)

    # 3. Труба целиком через evaluator-петлю (Зона 3, D-02) — итерируем поток событий.
    from evaluator_loop import research_with_evaluation

    events = [event async for event in research_with_evaluation(brief)]

    # 4. Инвариант терминала (D-13.2): ровно один терминал, и это `final` с НЕПУСТЫМ
    #    отчётом (после доработки петля вышла по порогу).
    terminals = [e for e in events if e.stage in ("final", "failed")]
    assert len(terminals) == 1
    assert terminals[0].stage == "final"
    assert isinstance(terminals[0].report, ReportData)
    assert terminals[0].report.markdown_report

    # 5. Итерация наблюдаема (D-13.2): >= 1 событие `evaluation` со score/feedback
    #    (содержание feedback НЕ проверяем — недетерминированно, RULES §4).
    evaluations = [e for e in events if e.stage == "evaluation"]
    assert len(evaluations) >= 1
    assert "score" in evaluations[0].payload
    assert "feedback" in evaluations[0].payload

    # 6. Multi-round собрался реально: менеджер и оценщик — по два прогона
    #    (initial + одна доработка), повторный run_research действительно прошёл через
    #    ТОТ ЖЕ per-loop ctx (D-13.1).
    assert mock_agent_runner.ran("EvaluatorAgent")
    assert mock_agent_runner.calls.count("ManagerAgent") == 2    # повторный run_research
    assert mock_agent_runner.calls.count("EvaluatorAgent") == 2  # оценка до и после доработки

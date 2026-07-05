"""Юнит-тесты Evaluator-Optimizer петли (под-шаг 5-pre-c, D-02 + D-13).

Петля — детерминированный `while` в КОДЕ (не у менеджера), гарантия лимита держится
кодом, не LLM. С 5-pre-c петля — генератор `ProgressEvent` (D-13.2): тесты ИТЕРИРУЮТ
поток, собирают события и проверяют терминал/стадии. СТАРЫЕ свойства петли (порог,
лимит, лучшая-по-score, тай-брейк) переживают переход на генератор и проверяются ТЕ
ЖЕ:
  * выход по порогу (score >= 7 на первой итерации → без доработок);
  * выход по лимиту (порог не взят, rounds упёрся в MAX_ROUNDS);
  * выбор лучшей версии (в `final` — максимум по score, не последний прогон);
  * тай-брейк равных score → ранняя версия (оператор `>`, не `>=`).
Плюс новый контракт D-13:
  * И-2 терминал: поток ВСЕГДА кончается ровно одним терминалом; happy → `final` с
    непустым report; падение без оценённой версии → `failed` без report (И-4);
  * наблюдаемость каждой итерации — теперь событие `evaluation` (было `on_iteration`);
  * дренер `run_loop_to_report`: happy → ReportData, failed-поток → исключение (не None).

Мок LLM через подмену `Runner.run` (менеджер + оценщик), без реальных вызовов и
ключа (D-06, RULES §4). «Умность» оценок не тестируется — недетерминированна.
"""

from types import SimpleNamespace

import pytest

from evaluator_agent import EvaluationFeedback
from writer_agent import ReportData
from _mocks import make_report


def _result(output):
    """Мини-двойник RunResult: .final_output + .final_output_as(...)."""
    return SimpleNamespace(final_output=output, final_output_as=lambda _cls: output)


def _ev(score, feedback="fb", missing=None):
    """EvaluationFeedback со scored-порогом. passed — совет LLM (петля решает кодом)."""
    return EvaluationFeedback(
        score=score,
        passed=score >= 7,
        feedback=feedback,
        missing_topics=missing or [],
    )


def _make_dispatcher(evaluations):
    """Патч Runner.run: менеджер отдаёт нумерованный отчёт, оценщик — по скрипту.

    evaluations — список EvaluationFeedback, раздаётся по порядку вызовов оценщика.
    Отчёты нумеруются по вызову менеджера ("report 0", "report 1", ...), чтобы
    тесты могли отличить, какая версия ушла наружу.
    """
    state = SimpleNamespace(manager_calls=0, evaluator_calls=0, reports=[])

    async def run(agent, input=None, *args, **kwargs):
        name = getattr(agent, "name", "")
        if name == "ManagerAgent":
            idx = state.manager_calls
            state.manager_calls += 1
            report = make_report(markdown_report=f"report {idx}")
            state.reports.append(report)
            return _result(report)
        if name == "EvaluatorAgent":
            ev = evaluations[state.evaluator_calls]
            state.evaluator_calls += 1
            return _result(ev)
        raise AssertionError(f"неожиданный агент в тесте петли: {name!r}")

    return run, state


async def _collect(brief="бриф"):
    """Прогнать генератор петли и собрать все события в список."""
    from evaluator_loop import research_with_evaluation

    return [event async for event in research_with_evaluation(brief)]


def _terminal(events):
    """Единственный терминал потока (И-2): ровно один `final`|`failed`, он последний."""
    terminals = [e for e in events if e.stage in ("final", "failed")]
    assert len(terminals) == 1, f"ожидался ровно один терминал, получено: {[e.stage for e in terminals]}"
    assert events[-1] is terminals[0], "терминал обязан быть последним событием"
    return terminals[0]


def _scores(events):
    """score каждой итерации оценки — наблюдаемость (было on_iteration, стало событие)."""
    return [e.payload["score"] for e in events if e.stage == "evaluation"]


@pytest.mark.asyncio
async def test_exits_when_threshold_met_on_first_iteration(monkeypatch):
    """Порог взят на первой оценке (score 8 >= 7) → ни одной доработки."""
    from agents import Runner

    run, state = _make_dispatcher([_ev(8, feedback="strong draft")])
    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()

    # Порог сразу → менеджер и оценщик отработали ровно по разу, доработок нет.
    assert state.manager_calls == 1
    assert state.evaluator_calls == 1

    # И-2: ровно один терминал `final` с НЕПУСТЫМ отчётом (report 0).
    terminal = _terminal(events)
    assert terminal.stage == "final"
    assert isinstance(terminal.report, ReportData)
    assert terminal.report.markdown_report == "report 0"

    # Каждая итерация наблюдаема событием `evaluation` (задел под UI).
    assert _scores(events) == [8]
    assert events[0].stage == "research_started"
    # Промежуточные события report НЕ несут.
    assert all(e.report is None for e in events if e.stage != "final")


@pytest.mark.asyncio
async def test_exits_when_rounds_hit_max_without_passing(monkeypatch):
    """Порог не взят ни разу → петля выходит по лимиту (initial + MAX_ROUNDS)."""
    from agents import Runner
    from evaluator_loop import MAX_ROUNDS

    # Все оценки ниже порога 7 — граница лимита, а не порога.
    run, state = _make_dispatcher([_ev(4), _ev(5), _ev(6)])
    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()

    # Инвариант лимита: первый прогон + не больше MAX_ROUNDS доработок. Не зациклилась.
    assert state.manager_calls == 1 + MAX_ROUNDS
    assert state.evaluator_calls == 1 + MAX_ROUNDS
    assert len(_scores(events)) == 1 + MAX_ROUNDS

    # И-2: терминал — ровно один `final` с непустым отчётом (graceful exit по лимиту).
    terminal = _terminal(events)
    assert terminal.stage == "final"
    assert isinstance(terminal.report, ReportData)


@pytest.mark.asyncio
async def test_returns_best_scoring_version_on_graceful_exit(monkeypatch):
    """Graceful exit: в `final` лучшая по score версия, НЕ последняя."""
    from agents import Runner

    # score по раундам: 6 (лучший, report 0), 3 (report 1), 5 (report 2).
    # Порог 7 не взят → лимит исчерпан; наружу должен уйти report 0 (максимум 6).
    run, state = _make_dispatcher([_ev(6), _ev(3), _ev(5)])
    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()
    terminal = _terminal(events)

    # Лучшая по score (report 0, score 6), а не последний прогон (report 2, score 5).
    assert terminal.stage == "final"
    assert terminal.report.markdown_report == "report 0"
    assert terminal.payload["score"] == 6
    assert state.manager_calls == 3  # первый прогон + 2 доработки


@pytest.mark.asyncio
async def test_returns_earliest_version_on_score_tie(monkeypatch):
    """Тай-брейк: при равном максимальном score в `final` идёт ранняя версия.

    Фиксирует контракт строгого `>` в петле (ничья НЕ вытесняет раннюю). score по
    раундам: 6 (report 0), 6 (report 1 — равен максимуму), 4 (report 2). Порог 7 не
    взят → лимит исчерпан; report 1 равен report 0 по score, но должен уйти report 0.
    """
    from agents import Runner

    run, state = _make_dispatcher([_ev(6), _ev(6), _ev(4)])
    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()
    terminal = _terminal(events)

    # Ранняя из равных (report 0), а не более поздняя с тем же score (report 1).
    assert terminal.stage == "final"
    assert terminal.report.markdown_report == "report 0"
    assert state.manager_calls == 3  # первый прогон + 2 доработки


@pytest.mark.asyncio
async def test_failed_terminal_when_run_crashes_with_no_evaluated_version(monkeypatch):
    """И-4: падение прогона без единой оценённой версии → терминал `failed` без report.

    Первый же прогон ядра бросает исключение (нет ни одной оценки) → поток обязан
    завершиться ровно одним `failed` (report=None, сообщение в payload), НЕ `final`.
    """
    from agents import Runner

    async def run(agent, input=None, *args, **kwargs):
        name = getattr(agent, "name", "")
        if name == "ManagerAgent":
            raise RuntimeError("boom: max turns exceeded")
        raise AssertionError(f"оценщик не должен вызываться при падении первого прогона: {name!r}")

    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()

    # И-2/И-4: ровно один терминал, и это `failed` без отчёта.
    terminal = _terminal(events)
    assert terminal.stage == "failed"
    assert terminal.report is None
    assert "boom" in terminal.payload["message"]
    # Взаимоисключение final/failed: ни одного `final` в потоке.
    assert not any(e.stage == "final" for e in events)


@pytest.mark.asyncio
async def test_graceful_final_when_crash_after_an_evaluated_version(monkeypatch):
    """И-4/D-13.2 путь (б): сбой ПОСЛЕ первой оценки → graceful `final`, НЕ `failed`.

    Первый прогон + оценка проходят (best_report уже есть, score 4); второй прогон
    (доработка, порог не взят) бросает исключение. Поток обязан завершиться ровно
    одним `final` с НЕПУСТЫМ отчётом (лучшая по score = первая версия) и маркером
    payload["graceful"] is True. `failed`-события в потоке НЕТ (взаимоисключение).
    """
    from agents import Runner

    state = SimpleNamespace(manager_calls=0, evaluator_calls=0)

    async def run(agent, input=None, *args, **kwargs):
        name = getattr(agent, "name", "")
        if name == "ManagerAgent":
            idx = state.manager_calls
            state.manager_calls += 1
            if idx == 1:                       # второй прогон (доработка) падает.
                raise RuntimeError("boom: max turns exceeded on revision")
            return _result(make_report(markdown_report=f"report {idx}"))
        if name == "EvaluatorAgent":
            state.evaluator_calls += 1
            return _result(_ev(4))             # ниже порога → уйдёт в доработку.
        raise AssertionError(f"неожиданный агент: {name!r}")

    monkeypatch.setattr(Runner, "run", run)

    events = await _collect()

    # Ровно один терминал, и это `final` (graceful), а НЕ `failed`.
    terminal = _terminal(events)
    assert terminal.stage == "final"
    assert isinstance(terminal.report, ReportData)
    assert terminal.report.markdown_report == "report 0"   # лучшая по score = первая.
    assert terminal.payload["graceful"] is True
    # Взаимоисключение: ни одного `failed` в потоке.
    assert not any(e.stage == "failed" for e in events)
    # Сбой случился на доработке — первая версия успела оцениться.
    assert state.manager_calls == 2
    assert state.evaluator_calls == 1


@pytest.mark.asyncio
async def test_drainer_returns_report_on_happy_stream(monkeypatch):
    """Дренер: happy-поток (`final`) → ReportData."""
    from agents import Runner
    from evaluator_loop import run_loop_to_report

    run, state = _make_dispatcher([_ev(8)])
    monkeypatch.setattr(Runner, "run", run)

    report = await run_loop_to_report("бриф")

    assert isinstance(report, ReportData)
    assert report.markdown_report == "report 0"


@pytest.mark.asyncio
async def test_drainer_raises_on_failed_stream(monkeypatch):
    """Дренер: failed-поток → исключение с сообщением из payload (НЕ None, D-13.3)."""
    from agents import Runner
    from evaluator_loop import run_loop_to_report

    async def run(agent, input=None, *args, **kwargs):
        if getattr(agent, "name", "") == "ManagerAgent":
            raise RuntimeError("boom: api error")
        raise AssertionError("оценщик не должен вызываться")

    monkeypatch.setattr(Runner, "run", run)

    with pytest.raises(RuntimeError, match="boom"):
        await run_loop_to_report("бриф")

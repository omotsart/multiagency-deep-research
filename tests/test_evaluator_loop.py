"""Юнит-тесты Evaluator-Optimizer петли (под-gate 4b, D-02).

Петля — детерминированный `while` в КОДЕ (не у менеджера), гарантия лимита держится
кодом, не LLM. Три сценария дословно из критериев Gate 4:
  * выход по порогу (score >= 7 на первой итерации → без доработок);
  * выход по лимиту (порог не взят, rounds упёрся в MAX_ROUNDS);
  * выбор лучшей версии (graceful exit отдаёт максимум по score, не последний прогон).

Мок LLM через подмену `Runner.run` (менеджер + оценщик), без реальных вызовов и
ключа (D-06, RULES §4). «Умность» самих оценок не тестируется — недетерминированна;
проверяется управляющая механика петли.
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


@pytest.mark.asyncio
async def test_exits_when_threshold_met_on_first_iteration(monkeypatch):
    """Порог взят на первой оценке (score 8 >= 7) → ни одной доработки."""
    from agents import Runner
    from evaluator_loop import research_with_evaluation

    run, state = _make_dispatcher([_ev(8, feedback="strong draft")])
    monkeypatch.setattr(Runner, "run", run)

    emitted = []
    report = await research_with_evaluation(
        "бриф", on_iteration=lambda s, f: emitted.append((s, f))
    )

    assert isinstance(report, ReportData)
    # Порог сразу → менеджер и оценщик отработали ровно по разу, доработок нет.
    assert state.manager_calls == 1
    assert state.evaluator_calls == 1
    assert report.markdown_report == "report 0"
    # Каждая итерация эмитит наружу score и feedback (задел под UI).
    assert emitted == [(8, "strong draft")]


@pytest.mark.asyncio
async def test_exits_when_rounds_hit_max_without_passing(monkeypatch):
    """Порог не взят ни разу → петля выходит по лимиту (initial + MAX_ROUNDS)."""
    from agents import Runner
    from evaluator_loop import research_with_evaluation, MAX_ROUNDS

    # Все оценки ниже порога 7 — граница лимита, а не порога.
    run, state = _make_dispatcher([_ev(4), _ev(5), _ev(6)])
    monkeypatch.setattr(Runner, "run", run)

    emitted = []
    report = await research_with_evaluation(
        "бриф", on_iteration=lambda s, f: emitted.append(s)
    )

    # Инвариант лимита: первый прогон + не больше MAX_ROUNDS доработок. Не зациклилась.
    assert state.manager_calls == 1 + MAX_ROUNDS
    assert state.evaluator_calls == 1 + MAX_ROUNDS
    assert len(emitted) == 1 + MAX_ROUNDS
    assert isinstance(report, ReportData)


@pytest.mark.asyncio
async def test_returns_best_scoring_version_on_graceful_exit(monkeypatch):
    """Graceful exit: наружу лучшая по score версия, НЕ последняя."""
    from agents import Runner
    from evaluator_loop import research_with_evaluation

    # score по раундам: 6 (лучший, report 0), 3 (report 1), 5 (report 2).
    # Порог 7 не взят → лимит исчерпан; наружу должен уйти report 0 (максимум 6).
    run, state = _make_dispatcher([_ev(6), _ev(3), _ev(5)])
    monkeypatch.setattr(Runner, "run", run)

    report = await research_with_evaluation("бриф")

    # Лучшая по score (report 0, score 6), а не последний прогон (report 2, score 5).
    assert report.markdown_report == "report 0"
    assert state.manager_calls == 3  # первый прогон + 2 доработки


@pytest.mark.asyncio
async def test_returns_earliest_version_on_score_tie(monkeypatch):
    """Тай-брейк: при равном максимальном score наружу идёт ранняя версия.

    Фиксирует контракт строгого `>` в петле (ничья НЕ вытесняет раннюю). score по
    раундам: 6 (report 0), 6 (report 1 — равен максимуму), 4 (report 2). Порог 7 не
    взят → лимит исчерпан; report 1 равен report 0 по score, но должен уйти report 0.
    """
    from agents import Runner
    from evaluator_loop import research_with_evaluation

    run, state = _make_dispatcher([_ev(6), _ev(6), _ev(4)])
    monkeypatch.setattr(Runner, "run", run)

    report = await research_with_evaluation("бриф")

    # Ранняя из равных (report 0), а не более поздняя с тем же score (report 1).
    assert report.markdown_report == "report 0"
    assert state.manager_calls == 3  # первый прогон + 2 доработки

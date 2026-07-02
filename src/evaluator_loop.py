"""Evaluator-Optimizer петля — Зона 3, контроль качества (Gate 4, под-шаг 4b).

Петля — детерминированный `while` в ПИТОНЕ (D-02), НЕ инструмент автономного
менеджера. Гарантия лимита итераций держится КОДОМ, а не решением LLM: менеджер
мог бы «забыть» счётчик, код — нет.

Цикл:
  1. Получить отчёт от Зоны 2 (`run_research(brief)` — менеджер владеет процессом).
  2. Оценить отчёт против брифа через `evaluator_agent` (→ EvaluationFeedback).
  3. Пока порог не взят и не исчерпан лимит доработок — скормить feedback и
     missing_topics обратно в доработку (пере-прогон Зоны 2 с обогащённым брифом).
  4. Graceful exit: наружу идёт ЛУЧШАЯ по score версия, не обязательно последняя.

Пороговое решение — в коде (D-02): `passed = score >= SCORE_THRESHOLD`. Поле
`EvaluationFeedback.passed` от оценщика остаётся советом (для UI/прозрачности), но
управляющий инвариант петли — код-порог по score, а не самооценка LLM. Так критерий
Gate 4 «порог score >= 7 (не 10)» энфорсится детерминированно.

Границы 4b (СПЕЦИАЛЬНО не здесь): расширение E2E через оценщик — 4c; финальный
handoff на finalizer после петли (D-09/D-12) — 4d, решение владельца; подключение
к UI — Gate 5. Здесь только петля и её юнит-тесты.
"""

from typing import Callable, Optional

from agents import Runner

from run_research import run_research
from evaluator_agent import evaluator_agent, EvaluationFeedback
from writer_agent import ReportData

# Порог качества и потолок доработок — критерии Gate 4, живут в коде (D-02).
SCORE_THRESHOLD = 7          # score >= 7 считается «достаточно хорошо» (шкала до 10).
MAX_ROUNDS = 2               # не больше двух доработок сверх первого прогона.

# Колбэк прогресса: петля эмитит наружу score и feedback КАЖДОЙ итерации (задел под
# UI, Gate 5). Необязателен — без него петля работает как чистая функция.
ProgressCallback = Callable[[int, str], None]


def _evaluation_input(brief: str, report: ReportData) -> str:
    """Вход оценщика: исходный бриф + готовый отчёт, плоским текстом."""
    return (
        "Original research brief:\n"
        f"{brief}\n\n"
        "Finished report to evaluate:\n"
        f"{report.markdown_report}"
    )


def _revision_brief(brief: str, evaluation: EvaluationFeedback) -> str:
    """Обогащённый бриф для доработки: исходный бриф + фидбэк + пробелы оценщика.

    feedback и missing_topics — руководство к доработке (см. evaluator_agent.py):
    скармливаем их обратно в Зону 2, чтобы следующий прогон целил в пробелы.
    """
    gaps = "\n".join(f"- {t}" for t in evaluation.missing_topics) or "- (none specified)"
    return (
        f"{brief}\n\n"
        "--- REVISION REQUEST ---\n"
        "A previous draft of the report was reviewed and judged not yet good "
        "enough. Produce an improved report that addresses this editorial "
        "feedback while still fully answering the original brief above.\n\n"
        f"Editorial feedback:\n{evaluation.feedback}\n\n"
        f"Topics or angles that were missing or too thin:\n{gaps}\n"
    )


async def _evaluate(brief: str, report: ReportData) -> EvaluationFeedback:
    """Один прогон оценщика над отчётом (Зона 3, единичное суждение)."""
    result = await Runner.run(evaluator_agent, _evaluation_input(brief, report))
    return result.final_output_as(EvaluationFeedback)


def _emit(on_iteration: Optional[ProgressCallback], evaluation: EvaluationFeedback) -> None:
    """Отдать наружу score и feedback текущей итерации (задел под UI)."""
    if on_iteration is not None:
        on_iteration(evaluation.score, evaluation.feedback)


async def research_with_evaluation(
    brief: str,
    on_iteration: Optional[ProgressCallback] = None,
) -> ReportData:
    """Исследовать бриф с контролем качества и вернуть ЛУЧШИЙ по score отчёт.

    Зона 2 (менеджер) готовит отчёт; Зона 3 (эта петля) оценивает и, пока порог не
    взят и лимит доработок не исчерпан, гоняет доработки. Возвращается лучшая по
    score версия (graceful exit — не обязательно последняя).

    on_iteration(score, feedback) — необязательный колбэк, вызывается на каждой
    оценке (задел под UI, Gate 5).
    """
    report = await run_research(brief)
    evaluation = await _evaluate(brief, report)
    _emit(on_iteration, evaluation)

    # Лучшая версия по score — кандидат на выдачу с самого начала (graceful exit).
    best_report, best_score = report, evaluation.score
    passed = evaluation.score >= SCORE_THRESHOLD

    rounds = 0
    while not passed and rounds < MAX_ROUNDS:
        rounds += 1
        report = await run_research(_revision_brief(brief, evaluation))
        evaluation = await _evaluate(brief, report)
        _emit(on_iteration, evaluation)

        # Строго лучше — тогда обновляем; ничьи оставляют раннюю (стабильный выбор).
        if evaluation.score > best_score:
            best_report, best_score = report, evaluation.score
        passed = evaluation.score >= SCORE_THRESHOLD

    return best_report

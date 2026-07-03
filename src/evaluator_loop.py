"""Evaluator-Optimizer петля — Зона 3, контроль качества.

Петля — детерминированный `while` в ПИТОНЕ (D-02), НЕ инструмент автономного
менеджера. Гарантия лимита итераций держится КОДОМ, а не решением LLM: менеджер
мог бы «забыть» счётчик, код — нет.

С под-шага 5-pre-c петля отдаёт прогресс наружу КАНАЛОМ-ГЕНЕРАТОРОМ (D-13.2), а не
колбэком: `research_with_evaluation` — чистый `async` генератор `ProgressEvent`.
Живой стриминг нужен UI (Gate 5, «накопительный лог + счётчики»), а Gradio стримит
именно через генераторы. Прежний `on_iteration`-колбэк удалён — его роль берёт поток
событий.

Контракт потока (D-13):
  * стадии: `research_started` → `draft_ready` → `evaluation`
    (→ `revision_started` → `draft_ready` → `evaluation`)* → терминал;
  * ПРОМЕЖУТОЧНЫЕ события `report` НЕ несут (`report=None`);
  * терминал ВСЕГДА ровно один и взаимоисключающий (D-13.2/D-13.3):
      - `final` — несёт НЕПУСТОЙ `report: ReportData` (не None; за это цепляется
        E2E `isinstance`);
      - `failed` — `report=None`, человекочитаемое сообщение в `payload["message"]`.

Бюджет — per-loop (D-13.1): ОДИН `ResearchContext` создаётся на весь запрос и
передаётся в КАЖДЫЙ `run_research(..., context=ctx)` — и в первый прогон, и в каждую
доработку. Бюджет поисков честно живёт на весь запрос (предохранитель D-03 не врёт),
а `ctx.searches_used` доступен в `payload` событий — задел под счётчик поисков в UI.

Пороговое решение — в коде (D-02): `passed = score >= SCORE_THRESHOLD`. Поле
`EvaluationFeedback.passed` от оценщика остаётся советом (для UI/прозрачности), но
управляющий инвариант петли — код-порог по score, а не самооценка LLM. Так критерий
«порог score >= 7 (не 10)» энфорсится детерминированно.

Дренер `run_loop_to_report` (5-pre-c) живёт ЗДЕСЬ же, рядом с генератором и его
контрактом стадий: он — каноническая свёртка ЭТОГО потока к отчёту (знает про
терминалы `final`/`failed`), а не логика петли и не забота потребителя. Держать
знание «как достать report из потока» в ОДНОЙ явной точке (её зовут finalizer, E2E,
UI), а не размазывать по потребителям. Отдельный модуль был бы слоем без
необходимости (RULES §6) ради одной функции над локальным контрактом событий.

Границы (СПЕЦИАЛЬНО не здесь): E2E под поток — 5-pre-d; вёрстка экранов — Gate 5.
"""

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from agents import Runner

from run_research import run_research
from evaluator_agent import evaluator_agent, EvaluationFeedback
from guardrails import ResearchContext
from writer_agent import ReportData

# Порог качества и потолок доработок — критерии Gate 4, живут в коде (D-02).
SCORE_THRESHOLD = 7          # score >= 7 считается «достаточно хорошо» (шкала до 10).
MAX_ROUNDS = 2               # не больше двух доработок сверх первого прогона.


@dataclass(frozen=True)
class ProgressEvent:
    """Событие прогресса петли, идущее наружу потоком (D-13.2).

    stage — стадия конвейера: `research_started` / `draft_ready` / `evaluation` /
      `revision_started` / `final` / `failed`.
    payload — произвольные данные стадии (round, score, feedback, searches_used, …)
      для лога и счётчиков UI.
    report — НЕПУСТОЙ ReportData ТОЛЬКО у терминала `final`; на всех остальных
      событиях (включая `failed`) — None. Инвариант: `report is not None` ⇔
      `stage == "final"`.
    """

    stage: str
    payload: dict
    report: Optional[ReportData] = None


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


def _evaluation_event(
    round_n: int, evaluation: EvaluationFeedback, ctx: ResearchContext
) -> ProgressEvent:
    """Событие оценки текущей итерации (наблюдаемость каждой итерации, задел под UI)."""
    return ProgressEvent(
        stage="evaluation",
        payload={
            "round": round_n,
            "score": evaluation.score,
            "feedback": evaluation.feedback,
            "missing_topics": list(evaluation.missing_topics),
            "searches_used": ctx.searches_used,
        },
    )


async def research_with_evaluation(brief: str) -> AsyncIterator[ProgressEvent]:
    """Исследовать бриф с контролем качества, отдавая прогресс потоком событий.

    Зона 2 (менеджер) готовит отчёт; Зона 3 (эта петля) оценивает и, пока порог не
    взят и лимит доработок не исчерпан, гоняет доработки. Наружу идёт поток
    `ProgressEvent` (D-13.2), ВСЕГДА завершающийся ровно одним терминалом:
      * `final` с ЛУЧШИМ по score отчётом (graceful exit — не обязательно последним);
      * `failed`, если прогон упал и ни одной оценённой версии ещё нет (D-13.3).

    Бюджет поисков — per-loop (D-13.1): ОДИН `ResearchContext` на весь запрос,
    передаётся в каждый `run_research(..., context=ctx)` (и первый, и доработки).
    """
    ctx = ResearchContext()          # ОДИН контекст на весь запрос (per-loop, D-13.1).
    best_report: Optional[ReportData] = None   # лучшая по score версия (graceful exit).
    best_score: Optional[int] = None

    try:
        yield ProgressEvent("research_started", {"round": 0})
        report = await run_research(brief, context=ctx)          # первый прогон — тот же ctx.
        yield ProgressEvent("draft_ready", {"round": 0, "searches_used": ctx.searches_used})

        evaluation = await _evaluate(brief, report)
        yield _evaluation_event(0, evaluation, ctx)
        best_report, best_score = report, evaluation.score
        passed = evaluation.score >= SCORE_THRESHOLD

        rounds = 0
        while not passed and rounds < MAX_ROUNDS:
            rounds += 1
            yield ProgressEvent("revision_started", {"round": rounds})
            # Доработка получает ТОТ ЖЕ ctx (per-loop, D-13.1) — не свежий.
            report = await run_research(_revision_brief(brief, evaluation), context=ctx)
            yield ProgressEvent(
                "draft_ready", {"round": rounds, "searches_used": ctx.searches_used}
            )

            evaluation = await _evaluate(brief, report)
            yield _evaluation_event(rounds, evaluation, ctx)

            # Строго лучше — обновляем; ничьи оставляют раннюю (стабильный выбор, тай-брейк `>`).
            if evaluation.score > best_score:
                best_report, best_score = report, evaluation.score
            passed = evaluation.score >= SCORE_THRESHOLD
    except Exception as exc:  # noqa: BLE001 — падение прогона (MaxTurnsExceeded/сеть/API), D-13.3.
        if best_report is not None:
            # Есть оценённая версия → graceful exit ЛУЧШЕЙ по score (та же ветка, что лимит).
            yield ProgressEvent(
                "final",
                {"score": best_score, "searches_used": ctx.searches_used, "graceful": True},
                best_report,
            )
        else:
            # Ни одной оценённой версии → альтернативный терминал `failed` (report=None).
            yield ProgressEvent(
                "failed",
                {"message": f"Research run failed before any report was produced: {exc}"},
            )
        return

    # Нормальный терминал: ровно один `final` с непустым отчётом (best-by-score).
    yield ProgressEvent(
        "final", {"score": best_score, "searches_used": ctx.searches_used}, best_report
    )


async def run_loop_to_report(brief: str) -> ReportData:
    """Каноническая свёртка потока петли к готовому отчёту (дренер, 5-pre-c).

    Гоняет `research_with_evaluation` до терминала:
      * `final` → возвращает НЕПУСТОЙ `report` (ReportData);
      * `failed` → поднимает исключение с сообщением из `payload` (НЕ возвращает None,
        D-13.3 на границе дренера — потребитель получает либо отчёт, либо внятную ошибку).

    Единственная точка, знающая «как достать report из потока»: её зовут finalizer
    (стык D-09), E2E (5-pre-d) и UI (Gate 5) — знание не размазано по потребителям.
    """
    async for event in research_with_evaluation(brief):
        if event.stage == "final":
            # Флаг payload["graceful"] игнорируется НАМЕРЕННО (D-13.2, уточнение
            # семантики терминалов): любой `final` = успех, годный report есть report.
            # Различение нормального/graceful-финала — забота потребителя, читающего
            # поток напрямую (UI), а не дренера.
            return event.report
        if event.stage == "failed":
            raise RuntimeError(event.payload.get("message", "research run failed"))
    # Контракт гарантирует ровно один терминал; сюда попасть нельзя — защита от тихого None.
    raise RuntimeError("evaluator loop ended without a terminal event")

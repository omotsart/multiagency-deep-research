"""Приёмочный провокатор терминалов (D-14.3) — ВНЕ живого UI.

Даёт офлайн-поток `ProgressEvent`, доводящий до каждого из трёх терминалов D-13
(`final` чистый / graceful-`final` / `failed`) БЕЗ ключа OpenAI и без реального
прогона — чтобы владелец мог проверить все три плашки экрана 3 руками на ручной
приёмке 5b.

ГРАНИЦА D-14.3: это приёмочная обвязка, а НЕ элемент интерфейса. `app.py`
импортирует этот модуль ЛЕНИВО и только когда задан env `MAD_FORCE_TERMINAL`
(`final` | `graceful` | `limit` | `failed`) — в нормальном прогоне модуль не
подключается, никаких «кнопок уронить прогон» в UI нет. Формы событий и payload-ключи —
ровно как у настоящей петли (`evaluator_loop.research_with_evaluation`), чтобы
UI-подписка прогонялась тем же кодом.

Четыре режима покрывают четыре плашки терминала (правило плашки уточнено на 5b,
D-14.2 — читается в UI по `score`+`graceful`):
  * `final`    → чистый `final`, score >= порога        → ЗЕЛЁНАЯ «Завершено»;
  * `limit`    → чистый `final`, score < порога (лимит) → ЖЁЛТАЯ «порог не взят»;
  * `graceful` → `final` c graceful=True (сбой-с-версией)→ ЖЁЛТАЯ «после сбоя»;
  * `failed`   → `failed`, отчёта нет                   → КРАСНАЯ.
"""

import asyncio

from evaluator_loop import ProgressEvent
from writer_agent import ReportData

_PACE = 0.5  # пауза между событиями — чтобы лента ощущалась живой на приёмке.


def _demo_report(version: int) -> ReportData:
    """Демо-ReportData для терминала (структура-контракт, не содержание)."""
    return ReportData(
        short_summary=f"Демонстрационный отчёт (версия {version}) для приёмки экрана 3.",
        markdown_report=(
            f"# Демонстрационный отчёт · версия {version}\n\n"
            "Это офлайн-заглушка провокатора терминалов (D-14.3), а не результат "
            "настоящего прогона. Тело отчёта появляется на терминале `final` "
            "(D-13.2: `report` есть только у `final`).\n\n"
            "## Раздел 1\nСодержимое для проверки вёрстки правой колонки.\n\n"
            "## Раздел 2\nЕщё абзац, чтобы проверить прокрутку и перенос."
        ),
        follow_up_questions=["Что исследовать дальше — пример 1?", "Пример 2?"],
    )


async def scripted_stream(mode: str):
    """Офлайн-поток событий, доводящий до заданного терминала (`mode`)."""
    yield ProgressEvent("research_started", {"round": 0})
    await asyncio.sleep(_PACE)

    if mode == "failed":
        # Падение ДО первой оценки → терминал `failed` (report=None, D-13.3).
        yield ProgressEvent(
            "failed",
            {"message": "Демо-сбой: прогон упал до первой оценки (например, MaxTurnsExceeded)."},
        )
        return

    yield ProgressEvent("draft_ready", {"round": 0, "searches_used": 3})
    await asyncio.sleep(_PACE)

    if mode == "final":
        # Порог взят на первой оценке → чистый `final` (без graceful) → ЗЕЛЁНАЯ.
        yield ProgressEvent(
            "evaluation",
            {"round": 0, "score": 8, "feedback": "Отчёт покрывает бриф; править нечего.",
             "missing_topics": [], "searches_used": 3},
        )
        await asyncio.sleep(_PACE)
        yield ProgressEvent("final", {"score": 8, "searches_used": 3}, _demo_report(1))
        return

    if mode == "limit":
        # Все оценки ниже порога → доработки исчерпали лимит (MAX_ROUNDS) → чистый
        # `final` со score < порога, БЕЗ graceful. Плашка обязана быть ЖЁЛТОЙ
        # (порог не взят), а не зелёной — проверка уточнения D-14.2 в UI.
        yield ProgressEvent(
            "evaluation",
            {"round": 0, "score": 5, "feedback": "Тонко по разделу X.",
             "missing_topics": ["раздел X"], "searches_used": 3},
        )
        await asyncio.sleep(_PACE)
        for r in (1, 2):  # MAX_ROUNDS доработок, порог так и не взят.
            yield ProgressEvent("revision_started", {"round": r})
            await asyncio.sleep(_PACE)
            yield ProgressEvent("draft_ready", {"round": r, "searches_used": 3 + 3 * r})
            await asyncio.sleep(_PACE)
            yield ProgressEvent(
                "evaluation",
                {"round": r, "score": 6, "feedback": "Лучше, но всё ещё ниже порога.",
                 "missing_topics": ["раздел X"], "searches_used": 3 + 3 * r},
            )
            await asyncio.sleep(_PACE)
        # Лучшая по score = 6 (< порога 7), чистый final без graceful.
        yield ProgressEvent("final", {"score": 6, "searches_used": 9}, _demo_report(1))
        return

    if mode == "graceful":
        # Ниже порога → доработка → сбой на доработке ПОСЛЕ первой оценки →
        # graceful `final` лучшей по score (payload["graceful"]=True, D-13.3).
        yield ProgressEvent(
            "evaluation",
            {"round": 0, "score": 5, "feedback": "Не хватает данных по разделу X.",
             "missing_topics": ["раздел X"], "searches_used": 3},
        )
        await asyncio.sleep(_PACE)
        yield ProgressEvent("revision_started", {"round": 1})
        await asyncio.sleep(_PACE)
        yield ProgressEvent(
            "final",
            {"score": 5, "searches_used": 6, "graceful": True},
            _demo_report(1),
        )
        return

    raise ValueError(
        f"неизвестный режим провокатора: {mode!r} (ожидалось final|limit|graceful|failed)"
    )

"""Точка входа автономного ядра — запуск менеджера с предохранителями (3b, D-03).

Тонкая обёртка над Runner.run: подключает к рантайму то, что на 3a осталось
неподключённым — бюджет поисков (ResearchContext) и потолок ходов (MAX_TURNS).
Без этого предохранители 2d — мёртвый код: бюджет не читается, max_turns не
действует. Это ЕДИНСТВЕННАЯ ответственность модуля — голый запуск ядра.

НЕ здесь (границы Gate 3): evaluator-петля (Gate 4), финальный handoff на
finalizer (D-09, шаг 3d), UI (Gate 5). Только рантайм-вызов менеджера.

Нюанс бюджета (пункт внимания к 3b) закрыт фиксацией дефолта: ResearchContext()
всегда берёт DEFAULT_SEARCH_BUDGET — ту же константу, из которой промпт менеджера
(manager_agent.py) собирает текст про бюджет через f-string. Значит обещанный
менеджеру бюджет и реально действующий лимит идут от ОДНОЙ константы и не
расходятся. Настраиваемый бюджет здесь НЕ вводится: это сменило бы контракт точки
входа и выносится владельцу (ПРЕДЛОЖЕНО), а не берётся по умолчанию.

Подъём контекста (5-pre-b, основа per-loop D-13.1): необязательный параметр
`context` позволяет вызывающему передать ОДИН ResearchContext на весь запрос
(будущая петля-генератор 5-pre-c: общий бюджет на все доработки + счётчик поисков
наружу для UI). Дефолт не меняется — без аргумента создаётся свежий ResearchContext,
как раньше (полная обратная совместимость). Сам per-loop здесь ещё НЕ включается —
только открывается возможность в сигнатуре ядра; петля на 5-pre-b не тронута.
"""

from agents import Runner

from manager_agent import manager_agent
from guardrails import MAX_TURNS, ResearchContext
from writer_agent import ReportData


async def run_research(
    brief: str, context: ResearchContext | None = None
) -> ReportData:
    """Запустить автономное исследование по брифу и вернуть готовый отчёт.

    brief — плоская строка (D-10): тема + склеенные уточнения из Зоны 1.
    context — необязательный ResearchContext (5-pre-b): если передан, прогон
    использует ИМЕННО его (бюджет и счётчик поисков — общие с вызывающим, основа
    per-loop D-13.1 и подъёма счётчика в UI); если None — создаётся свежий
    ResearchContext(), как раньше (обратная совместимость: вызов без аргумента не
    меняет поведения).

    Менеджер (Зона 2, agents-as-tools) сам решает число и направление поисков в
    пределах предохранителей:
      * бюджет поисков — ResearchContext (DEFAULT_SEARCH_BUDGET по умолчанию);
        поисковый инструмент отказывает/капается при исчерпании (сигналы
        SEARCH_BUDGET_EXHAUSTED / SEARCH_BUDGET_PARTIAL);
      * max_turns=MAX_TURNS — потолок ходов агента.
    Возвращает ReportData (short_summary, markdown_report, follow_up_questions).
    """
    ctx = context if context is not None else ResearchContext()
    result = await Runner.run(
        manager_agent,
        brief,
        context=ctx,
        max_turns=MAX_TURNS,
    )
    return result.final_output_as(ReportData)

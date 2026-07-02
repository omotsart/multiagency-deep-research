import asyncio
from dataclasses import dataclass, field

from agents import (
    Agent,
    WebSearchTool,
    ModelSettings,
    Runner,
    RunContextWrapper,
    function_tool,
)

from planner_agent import WebSearchItem, WebSearchPlan
from guardrails import ResearchContext

INSTRUCTIONS = (
    "You are a research assistant. Given a search term, you search the web for that term and "
    "produce a concise summary of the results. The summary must 2-3 paragraphs and less than 300 "
    "words. Capture the main points. Write succintly, no need to have complete sentences or good "
    "grammar. This will be consumed by someone synthesizing a report, so its vital you capture the "
    "essence and ignore any fluff. Do not include any additional commentary other than the summary itself."
)

search_agent = Agent(
    name="Search agent",
    instructions=INSTRUCTIONS,
    tools=[WebSearchTool(search_context_size="low")],
    model="gpt-4o-mini",
    model_settings=ModelSettings(tool_choice="required"),
)


# --- Параллельный поиск как инструмент менеджера (под-gate 2b) -----------------
#
# Выбор @function_tool, НЕ search_agent.as_tool():
#   .as_tool() отдал бы менеджеру ОДИН поиск, и параллельность/устойчивость
#   пришлось бы возлагать на LLM (ненадёжно, и потерялась бы проверенная механика
#   из research_manager.py). «Запусти N поисков параллельно» — это оркестрация НАД
#   агентом, а не сам агент. Поэтому это функция-инструмент, которая внутри гоняет
#   Runner.run(search_agent, ...) по каждому пункту плана параллельно.
# Границы D-01 соблюдены: поиск по-прежнему вызывается через Runner; менеджер
# владеет процессом (agents-as-tools), handoffs нет.
# Логика (asyncio.as_completed + try/except → None) перенесена из оригинального
# research_manager.perform_searches/search без изменений поведения.


async def _run_single_search(item: WebSearchItem) -> str | None:
    """Один поиск. Падение → None, чтобы упавший поиск не рушил всю пачку."""
    input = f"Search term: {item.query}\nReason for searching: {item.reason}"
    try:
        result = await Runner.run(search_agent, input)
        return str(result.final_output)
    except Exception:
        return None


async def perform_parallel_searches(plan: WebSearchPlan) -> list[str]:
    """Запусти все поиски плана параллельно и собери сводки.

    Сохранена оригинальная механика: параллельность через asyncio.as_completed,
    устойчивость — упавший поиск возвращает None и пропускается, остальные
    доезжают. Порядок результатов — по завершению (свойство as_completed), не по
    порядку плана.
    """
    tasks = [asyncio.create_task(_run_single_search(item)) for item in plan.searches]
    results: list[str] = []
    for task in asyncio.as_completed(tasks):
        result = await task
        if result is not None:
            results.append(result)
    return results


# --- Предохранитель: бюджет поисков (под-gate 2d, D-03) ------------------------
#
# Бюджет живёт в ResearchContext и передаётся менеджеру через RunContextWrapper
# (на Gate 3 — Runner.run(manager, ..., context=ResearchContext())). Поисковый
# инструмент читает остаток и списывает израсходованное. Отказ при исчерпании —
# КОНТРОЛИРУЕМЫЙ: не исключение (не роняет пайплайн), а внятный сигнал, который
# менеджер видит как результат инструмента и может учесть.
#
# Бюджет считается по ОТДЕЛЬНЫМ поискам (см. guardrails.py). Пачка больше остатка
# → выполняем столько, сколько влезает, лишнее отбрасываем с пометкой.


@dataclass
class SearchOutcome:
    """Результат поискового инструмента с учётом бюджета.

    `refused=True` и пустой `summaries` — бюджет был исчерпан ДО вызова, поиск не
    выполнялся. `message` — человекочитаемый сигнал для менеджера (в т.ч. когда
    часть пачки отброшена по бюджету).
    """

    summaries: list[str] = field(default_factory=list)
    refused: bool = False
    message: str = ""


async def run_searches_with_budget(
    ctx: ResearchContext, plan: WebSearchPlan
) -> SearchOutcome:
    """Выполнить поиски плана в рамках бюджета `ctx` и списать израсходованное.

    Чистая (без RunContextWrapper) — ядро предохранителя, удобно тестировать.
    - остаток 0 → контролируемый отказ, поиск НЕ выполняется, счётчик не меняется;
    - пачка больше остатка → выполняется первые `remaining`, лишнее отброшено;
    - списываем по числу ПОПЫТОК (упавший поиск тоже потратил бюджет).
    """
    requested = len(plan.searches)

    if ctx.is_exhausted:
        return SearchOutcome(
            refused=True,
            message=(
                f"SEARCH_BUDGET_EXHAUSTED: бюджет поисков исчерпан "
                f"(лимит {ctx.search_budget}, использовано {ctx.searches_used}). "
                "Новые поиски не выполнены — работай с уже собранными результатами."
            ),
        )

    remaining = ctx.searches_remaining
    allowed_items = plan.searches[:remaining]
    dropped = requested - len(allowed_items)

    # Списываем по числу попыток сразу — даже если часть поисков упадёт внутри.
    ctx.spend(len(allowed_items))
    summaries = await perform_parallel_searches(WebSearchPlan(searches=allowed_items))

    if dropped > 0:
        message = (
            f"SEARCH_BUDGET_PARTIAL: выполнено {len(allowed_items)} из {requested} "
            f"запросов; {dropped} отброшено из-за лимита "
            f"(лимит {ctx.search_budget}, использовано {ctx.searches_used})."
        )
    else:
        message = ""
    return SearchOutcome(summaries=summaries, refused=False, message=message)


@function_tool
async def run_parallel_searches(
    wrapper: RunContextWrapper[ResearchContext], plan: WebSearchPlan
) -> str:
    """Run web searches from a research plan in parallel, within the run's search
    budget, and return their summaries. Input: a WebSearchPlan (list of searches).
    Returns concise text summaries — one per successful search; failed searches
    are skipped so the batch never fails as a whole. If the search budget is
    exhausted, no searches are run and a clear budget message is returned instead.
    """
    outcome = await run_searches_with_budget(wrapper.context, plan)
    if outcome.refused:
        return outcome.message
    body = "\n\n".join(outcome.summaries) if outcome.summaries else "(no results)"
    return f"{outcome.message}\n\n{body}".strip() if outcome.message else body
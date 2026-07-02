import asyncio

from agents import Agent, WebSearchTool, ModelSettings, Runner, function_tool

from planner_agent import WebSearchItem, WebSearchPlan

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


@function_tool
async def run_parallel_searches(plan: WebSearchPlan) -> list[str]:
    """Run all web searches from a research plan in parallel and return their
    summaries. Input: a WebSearchPlan (list of searches). Returns a list of
    concise text summaries — one per search that succeeded; failed searches are
    skipped, so the batch never fails as a whole.
    """
    return await perform_parallel_searches(plan)
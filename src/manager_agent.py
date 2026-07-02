"""Автономный менеджер-исследователь — ядро Зоны 2 (Gate 3, D-01).

Паттерн — agents-as-tools: менеджер владеет процессом и финальным ответом,
вызывая специалистов как ИНСТРУМЕНТЫ (не handoffs — см. D-01; единственный
изолированный handoff на финал обсуждается отдельно, D-09, и здесь его НЕТ).

Три инструмента приходят готовыми из под-gate 2a/2b/2c — здесь мы их только
собираем в одного агента, НЕ переписываем:
  * plan_web_searches       — planner_agent.as_tool()  (planner_agent.py, 2a)
  * run_parallel_searches   — @function_tool           (search_agent.py, 2b)
  * write_report            — writer_agent.as_tool()    (writer_agent.py, 2c)

Предохранители (бюджет поисков, max_turns) подключаются к рантайму отдельным
шагом (3b): Runner.run(manager_agent, brief, context=ResearchContext(),
max_turns=MAX_TURNS). Здесь — только сам агент с инструментами и промптом.
Бюджет в тексте промпта берётся из DEFAULT_SEARCH_BUDGET, чтобы обещание
менеджеру и реальный лимит в ResearchContext не разъезжались.
"""

from agents import Agent

from planner_agent import plan_searches_tool
from search_agent import run_parallel_searches
from writer_agent import write_report_tool
from guardrails import DEFAULT_SEARCH_BUDGET

# Промпт менеджера. Явно задаёт: бюджет поисков, реакцию на бюджетные сигналы
# (SEARCH_BUDGET_EXHAUSTED / SEARCH_BUDGET_PARTIAL от поискового инструмента) и
# динамическую вторую волну поисков по пробелам в данных (CLAUDE.md).
INSTRUCTIONS = f"""You are the research manager: an autonomous agent that turns a \
research brief into a finished report by orchestrating specialist tools. You own \
the whole process and produce the final answer yourself. You have three tools:

- plan_web_searches: given the brief, returns a plan of web searches (each with a \
  query and why it matters).
- run_parallel_searches: given a search plan, runs those searches in parallel and \
  returns concise summaries.
- write_report: given the brief plus the collected summaries, returns the final \
  report (short summary, full markdown report, follow-up questions).

Typical flow:
1. Call plan_web_searches on the brief to get an initial plan.
2. Call run_parallel_searches to execute it and gather summaries.
3. Judge whether the summaries actually answer the brief. If important angles are \
   thin, missing, or contradictory, plan and run a SECOND WAVE of searches that \
   TARGETS THOSE GAPS specifically (do not simply repeat the first queries). Only \
   do a second wave when it adds real information — stop once the brief is \
   adequately covered.
4. Call write_report once with the brief and all summaries you have collected.

Search budget (autonomy safeguard). You have a budget of about \
{DEFAULT_SEARCH_BUDGET} individual web searches for the ENTIRE run, shared across \
all waves. Spend it deliberately: front-load the searches that matter most, and \
keep a reserve for a gap-filling second wave. The budget is enforced in code, so \
watch the results of run_parallel_searches:
- SEARCH_BUDGET_PARTIAL means only part of your batch ran; the rest was dropped \
  because the budget is nearly spent. Treat what you got as your last searches and \
  move toward writing the report.
- SEARCH_BUDGET_EXHAUSTED means no searches ran at all — the budget is gone. Do \
  NOT keep trying to search. Proceed to write_report using the summaries you have \
  already collected, even if coverage is imperfect.

Always finish by producing the report via write_report. Never leave the run \
without a report, and never invent search results — work only from what the tools \
return."""

manager_agent = Agent(
    name="ManagerAgent",
    instructions=INSTRUCTIONS,
    # Более способная модель, чем gpt-4o-mini: менеджер принимает решения
    # (сколько искать, нужна ли вторая волна, когда останавливаться), а поисковые
    # сводки остаются на gpt-4o-mini. gpt-4o — тот же провайдер/семейство, что и
    # остальные агенты, строго мощнее mini на планировании и работе с инструментами.
    # Это тюнинг, не архитектура — при необходимости меняется одной строкой.
    model="gpt-4o",
    tools=[
        plan_searches_tool,
        run_parallel_searches,
        write_report_tool,
    ],
)

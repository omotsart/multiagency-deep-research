from pydantic import BaseModel, Field
from agents import Agent

HOW_MANY_SEARCHES = 3

INSTRUCTIONS = f"You are a helpful research assistant. Given a query, come up with a set of web searches \
to perform to best answer the query. Output {HOW_MANY_SEARCHES} terms to query for."


class WebSearchItem(BaseModel):
    reason: str = Field(description="Your reasoning for why this search is important to the query.")
    query: str = Field(description="The search term to use for the web search.")


class WebSearchPlan(BaseModel):
    searches: list[WebSearchItem] = Field(description="A list of web searches to perform to best answer the query.")
    
planner_agent = Agent(
    name="PlannerAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=WebSearchPlan,
)

# Обёртка планировщика как инструмент менеджера (Зона 2, agents-as-tools — D-01).
# Сам агент выше не меняется: те же инструкции, схема, модель. Здесь только
# делаем его вызываемым менеджером. tool_description увидит менеджер на Gate 3
# при выборе инструмента — оно должно ясно говорить, что делает инструмент.
plan_searches_tool = planner_agent.as_tool(
    tool_name="plan_web_searches",
    tool_description=(
        "Plan a set of web searches for the research brief. Input: the research "
        "brief (topic + clarifications) as plain text. Returns a WebSearchPlan — "
        "a list of searches, each with a query and the reason it matters."
    ),
)
from pydantic import BaseModel, Field
from agents import Agent

INSTRUCTIONS = (
    "You are a senior researcher tasked with writing a cohesive report for a research query. "
    "You will be provided with the original query, and some initial research done by a research assistant.\n"
    "You should first come up with an outline for the report that describes the structure and "
    "flow of the report. Then, generate the report and return that as your final output.\n"
    "The final output should be in markdown format, and it should be lengthy and detailed. Aim "
    "for 5-10 pages of content, at least 1000 words."
)


class ReportData(BaseModel):
    short_summary: str = Field(description="A short 2-3 sentence summary of the findings.")

    markdown_report: str = Field(description="The final report")

    follow_up_questions: list[str] = Field(description="Suggested topics to research further")


writer_agent = Agent(
    name="WriterAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=ReportData,
)

# Обёртка писателя как инструмент менеджера (Зона 2, agents-as-tools — D-01).
# Один синтез-вызов, параллелить нечего → .as_tool(), как в 2a (не function_tool).
# Сам агент выше не меняется: те же инструкции, схема ReportData, модель.
# tool_description увидит менеджер на Gate 3 при выборе инструмента.
write_report_tool = writer_agent.as_tool(
    tool_name="write_report",
    tool_description=(
        "Synthesize the final research report. Input: the research brief plus the "
        "collected search summaries, as plain text. Returns a ReportData — a short "
        "summary, the full markdown report, and suggested follow-up questions."
    ),
)
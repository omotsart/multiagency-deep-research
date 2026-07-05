from pydantic import BaseModel, Field
from agents import Agent

# Ровно столько уточняющих вопросов задаёт clarifier (Зона 1 — человек в цикле).
NUM_QUESTIONS = 3

INSTRUCTIONS = (
    "You are a research clarifier. Given a user's research topic, ask exactly "
    f"{NUM_QUESTIONS} short clarifying questions that will most sharpen the scope "
    "of the research (audience, depth, angle, timeframe, constraints, etc.). "
    "Ask only questions — do not attempt to answer them or start the research."
)


class ClarifyingQuestions(BaseModel):
    """Структурированный вывод clarifier: ровно NUM_QUESTIONS вопросов."""

    questions: list[str] = Field(
        min_length=NUM_QUESTIONS,
        max_length=NUM_QUESTIONS,
        description=f"Exactly {NUM_QUESTIONS} clarifying questions about the topic.",
    )


clarifier_agent = Agent(
    name="ClarifierAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=ClarifyingQuestions,
)

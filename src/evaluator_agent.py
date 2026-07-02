"""Оценщик отчёта — вход Зоны 3 (контроль качества, Gate 4, под-шаг 4a).

Оценщик — ЧИСТАЯ функция суждения: получает готовый отчёт и исходный бриф,
возвращает структурированную оценку (score / passed / feedback / missing_topics).
Он НЕ управляет доработкой и НЕ знает про пороги и лимиты итераций.

Петля Evaluator-Optimizer (порог score >= 7, MAX_ROUNDS = 2, graceful exit,
выбор лучшей версии) живёт отдельным детерминированным `while` в КОДЕ — под-шаг
4b, — а НЕ у менеджера-агента и НЕ в этом промпте (D-02: гарантия лимита держится
кодом, агент может «забыть» счётчик). Поэтому здесь только сам агент со схемой и
промптом; никакой петлевой логики.

Поля feedback и missing_topics — руководство к доработке: их потребит петля на 4b,
передавая менеджеру для следующей итерации. Порог `passed` оценщик выставляет как
своё суждение о готовности, но РЕШЕНИЕ продолжать/остановиться принимает код петли.
"""

from pydantic import BaseModel, Field
from agents import Agent


class EvaluationFeedback(BaseModel):
    score: int = Field(
        description=(
            "Overall quality of the report on a 0-10 scale, where 10 is a "
            "flawless, publication-ready report and 0 is unusable. The revision "
            "loop treats score >= 7 as good enough to stop (the threshold lives "
            "in code, not in your judgement — just rate honestly)."
        )
    )
    passed: bool = Field(
        description=(
            "True if the report already answers the brief well enough to ship "
            "as-is; False if it still needs another revision pass."
        )
    )
    feedback: str = Field(
        description=(
            "Concrete, actionable guidance on what to improve. This is consumed "
            "by the revision loop and handed back to the manager, so be specific "
            "and constructive rather than vague."
        )
    )
    missing_topics: list[str] = Field(
        description=(
            "Specific gaps: topics, angles, or questions from the brief that the "
            "report failed to cover or covered too thinly. Empty if none. The "
            "loop uses these to target the next wave of research."
        )
    )


INSTRUCTIONS = (
    "You are a demanding but fair research editor. You are given the original "
    "research brief (topic plus the user's clarifications) and a finished report "
    "that was written to answer it. Your job is to evaluate how well the report "
    "satisfies the brief and to return a structured evaluation.\n\n"
    "Judge the report on: coverage of what the brief actually asked for, factual "
    "coherence and internal consistency, depth and specificity (not padding), and "
    "clear structure. Reward reports that directly answer the brief; penalise ones "
    "that drift off-topic, stay superficial, or leave important angles unaddressed.\n\n"
    "Return: a score from 0 to 10, a passed flag (is it good enough to ship "
    "as-is?), written feedback, and a list of missing_topics. The feedback and "
    "missing_topics are guidance for a revision step: they will be handed back to "
    "the report writer to improve the next draft, so make them concrete and "
    "actionable — name what to add, fix, or deepen, and which gaps to fill. If the "
    "report is already strong, say so and leave missing_topics empty.\n\n"
    "Evaluate only. Do not rewrite the report, and do not decide how many "
    "revisions to run — that is handled outside of you."
)


evaluator_agent = Agent(
    name="EvaluatorAgent",
    instructions=INSTRUCTIONS,
    # Более способная модель, как у менеджера (не gpt-4o-mini): оценка отчёта против
    # брифа — содержательное суждение (полнота, связность, пробелы), а не простая
    # сводка. По CLAUDE.md сильная модель идёт тем, кто принимает решения; mini —
    # для поисковых сводок. Тот же провайдер/семейство, что у остальных агентов.
    # Это тюнинг, не архитектура — при необходимости меняется одной строкой.
    model="gpt-4o",
    output_type=EvaluationFeedback,
)

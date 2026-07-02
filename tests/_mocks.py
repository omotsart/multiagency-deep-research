"""Переиспользуемый мок-слой для LLM-вызовов агентов (под-gate 2e, D-06).

Инфраструктура для E2E-тестов Gate 3+: подмена `Runner.run` каноническими
выходами агентов, без реальных вызовов OpenAI и без ключа. E2E-контракт
проверяет СБОРКУ трубы, а не качество текста (RULES §4, D-06).

Содержимое:
  * строители канонических выходов (`make_plan`, `make_report`);
  * `search_run(...)` — async side_effect для одиночного поиска (используется
    юнит-тестами поиска/предохранителей);
  * `MockAgentRunner` — диспетчер `Runner.run` для всей трубы (план→поиск→отчёт),
    раздаёт канон по имени агента и записывает вызовы; неизвестный агент
    (например, будущий менеджер на Gate 3) пробрасывается к настоящему Runner.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace

from planner_agent import WebSearchItem, WebSearchPlan
from writer_agent import ReportData


# ── Строители канонических выходов ────────────────────────────────────────────

def make_plan(*queries: str) -> WebSearchPlan:
    """WebSearchPlan из перечисленных запросов (по умолчанию три)."""
    if not queries:
        queries = ("q1", "q2", "q3")
    return WebSearchPlan(
        searches=[WebSearchItem(reason=f"reason {q}", query=q) for q in queries]
    )


def make_report(
    short_summary: str = "Краткий итог находок.",
    markdown_report: str = "# Отчёт\n\nТело отчёта.",
    follow_up_questions: list[str] | None = None,
) -> ReportData:
    """Канонический ReportData (структура-контракт, не содержание)."""
    return ReportData(
        short_summary=short_summary,
        markdown_report=markdown_report,
        follow_up_questions=follow_up_questions
        if follow_up_questions is not None
        else ["Что исследовать дальше?"],
    )


def term_from_input(input: str) -> str:
    """Вытащить поисковый запрос из input, который собирает _run_single_search."""
    if "Search term: " in input:
        return input.split("Search term: ", 1)[1].split("\n", 1)[0]
    return input


def _result(output):
    """Мини-двойник RunResult: даёт .final_output и .final_output_as(...)."""
    return SimpleNamespace(final_output=output, final_output_as=lambda _cls: output)


def search_run(fail_on=()):
    """async side_effect для Runner.run(search_agent, ...).

    Возвращает 'summary for <term>'; бросает RuntimeError для term из fail_on
    (проверка устойчивости: упавший поиск не должен рушить пачку).
    """
    fail = set(fail_on)

    async def _run(agent, input, *args, **kwargs):
        term = term_from_input(input)
        if term in fail:
            raise RuntimeError(f"search failed: {term}")
        return _result(f"summary for {term}")

    return _run


# ── Диспетчер Runner.run для всей трубы (E2E, Gate 3+) ─────────────────────────

@dataclass
class MockAgentRunner:
    """Мок-слой `Runner.run` для E2E: канон по имени агента + запись вызовов.

    Раздаёт: PlannerAgent → WebSearchPlan, Search agent → 'summary for <term>',
    WriterAgent → ReportData. Неизвестный агент (менеджер на Gate 3, который
    гоняется собственной сценарной моделью) пробрасывается к настоящему Runner.
    """

    plan: WebSearchPlan | None = None
    report: ReportData | None = None
    search_fail_on: set = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    _original: object = None

    def configure(self, *, plan=None, report=None, search_fail_on=()):
        if plan is not None:
            self.plan = plan
        if report is not None:
            self.report = report
        self.search_fail_on = set(search_fail_on)
        return self

    async def dispatch(self, agent, input, *args, **kwargs):
        name = getattr(agent, "name", "")
        self.calls.append(name)
        if name == "PlannerAgent":
            return _result(self.plan if self.plan is not None else make_plan())
        if name == "Search agent":
            term = term_from_input(input)
            if term in self.search_fail_on:
                raise RuntimeError(f"search failed: {term}")
            return _result(f"summary for {term}")
        if name == "WriterAgent":
            return _result(self.report if self.report is not None else make_report())
        # Неизвестный агент (напр. менеджер) — к настоящему Runner (Gate 3).
        return await self._original(agent, input, *args, **kwargs)

    def ran(self, agent_name: str) -> bool:
        return agent_name in self.calls

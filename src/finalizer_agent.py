"""Финализатор — единственный handoff проекта: финальное оформление (D-09, шаг 4d).

Роль (D-09). После утверждения отчёта evaluator-петлёй (4b, лучшая по score версия)
финальная выдача оформляется ОТДЕЛЬНЫМ агентом, к которому переходят одним
изолированным handoff. Финализатор — ЧИСТАЯ косметика: заголовок, аннотация
(short_summary наверху), тело (markdown_report как есть), блок «что исследовать
дальше» из follow_up_questions, строка-дисклеймер. Содержание НЕ переписывается, НЕ
переоценивается, НЕ дозапрашивается. Финализатор НЕ участвует ни в поиске, ни в
оценке — только оформление, после него в пайплайне ничего.

Стык петля→handoff — вариант A (агент-шлюз), ПРИНЯТ владельцем.
Настоящий SDK-handoff инициируется ходом LLM агента ВНУТРИ Runner.run (agents/
handoffs.py: on_invoke_handoff зовёт модель, возвращает целевого агента). Петля (4b)
— это код и уже вернула ReportData к моменту оформления, поэтому «настоящий handoff
строго ПОСЛЕ петли» требует агента-инициатора в этой точке. Инициатор — тонкий
finalizer_gateway c handoffs=[handoff(finalizer_agent)]: research_and_finalize()
после выхода из петли делает единственный прогон шлюза, тот транслирует управление
на финализатор настоящим handoff (не .as_tool — единственное отступление от D-01,
заведено D-09). Готовый ReportData доходит до финализатора через историю диалога
(вход шлюза). Стык — ОДНА точка, ВНЕ цикла; петля про финализатор не знает
(evaluator_loop.py не тронут), лимит её итераций handoff не затрагивает (D-02).

Оформление производит САМ LLM-финализатор (получательство handoff = ход модели):
содержание идёт через модель. Детерминированная граница «косметика в коде»
рассмотрена и ОТКЛОНЕНА владельцем — несовместима с механикой handoff (см. уточнение
к D-09 в DECISIONS.md). Целостность содержания через transfer юнит-тестом
непокрываема (RULES §4) — проверяется ручной приёмкой на живом прогоне (Gate 5/6).
Юнит-тестами покрыты только механика и порядок стыка (handoff настоящий; строго
после петли; лимит итераций цел).
"""

from pydantic import BaseModel, Field
from agents import Agent, Runner, handoff

from evaluator_loop import run_loop_to_report


class FinalReport(BaseModel):
    title: str = Field(description="Short title shown at the top of the final report.")
    presentation_markdown: str = Field(
        description=(
            "The full final presentation in markdown: title, the short summary as an "
            "annotation at the top, the report body verbatim, a 'what to explore "
            "next' section from the follow-up questions, and a disclaimer line."
        )
    )


INSTRUCTIONS = (
    "You are the finalizer: the last step of the pipeline. You receive a finished, "
    "already-approved research report (a short summary, the full markdown report, and "
    "follow-up questions). Your only job is to assemble the FINAL PRESENTATION for "
    "display:\n"
    "- a concise title at the top;\n"
    "- the short summary as an annotation (blockquote) right under the title;\n"
    "- the full markdown report body reproduced VERBATIM;\n"
    "- the follow-up questions gathered into a readable 'what to explore next' "
    "section at the end;\n"
    "- a one-line disclaimer that the report was generated autonomously.\n\n"
    "This is COSMETIC ONLY. Do NOT rewrite, re-summarize, shorten, re-evaluate, or "
    "add any research or facts. Preserve the report's content exactly as given — you "
    "only arrange and label it."
)

# Единственный handoff проекта — механика D-09, НЕ agents-as-tools (D-01). Модель —
# gpt-4o-mini: оформление косметическое (компоновка готовой структуры), не требует
# сильной модели (CLAUDE.md: mini — для простого; сильная — для решающих). Финализатор
# решений не принимает. output_type=FinalReport — эмитит структурированную выдачу.
finalizer_agent = Agent(
    name="FinalizerAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=FinalReport,
)


# ── Стык петля→handoff (вариант A: агент-шлюз, принят владельцем) ──────────────

GATEWAY_INSTRUCTIONS = (
    "You are a thin gateway. You receive a finished, already-approved research "
    "report. Do not write, summarize, or comment on it. Immediately hand off to the "
    "finalizer agent so it can produce the final presentation. Perform the handoff "
    "as your only action."
)

# Инициатор единственного handoff проекта: тонкий агент, чья единственная работа —
# сделать transfer на финализатор. Это НАСТОЯЩАЯ механика handoff (handoff(...) +
# handoffs=[...]), а не .as_tool — единственное отступление от agents-as-tools
# (D-01), заведённое отдельным решением D-09. Модель gpt-4o-mini: шлюз ничего не
# решает, только запускает передачу.
finalizer_gateway = Agent(
    name="FinalizerGateway",
    instructions=GATEWAY_INSTRUCTIONS,
    model="gpt-4o-mini",
    handoffs=[handoff(finalizer_agent)],
)


async def research_and_finalize(brief: str) -> FinalReport:
    """Полный автономный конвейер после брифа: петля (Зона 3) → handoff → финал.

    Порядок стыка критичен (D-02/D-09):
      1. Зона 3 — evaluator-петля (детерминированный `while`, гарантия лимита в
         КОДЕ). Петля отдаёт прогресс потоком событий (D-13.2); дренер
         `run_loop_to_report` сворачивает поток к ЛУЧШЕМУ по score ReportData
         (терминал `final`) либо поднимает исключение при падении (терминал
         `failed`, D-13.3). Петля про финализатор НЕ знает — evaluator_loop.py её
         не импортирует.
      2. Строго ПОСЛЕ выхода из петли, ВНЕ цикла, ОДНОЙ точкой — единственный
         handoff проекта (D-09): прогон шлюза `finalizer_gateway`, который делает
         transfer на `finalizer_agent`. Готовый ReportData доходит до финализатора
         через историю диалога (сериализованный вход шлюза). Handoff НЕ участвует в
         поиске/оценке и НЕ влияет на счётчик итераций петли — после него в
         пайплайне ничего.

    Возвращает FinalReport (оформленная выдача от финализатора).
    """
    report = await run_loop_to_report(brief)
    result = await Runner.run(finalizer_gateway, report.model_dump_json())
    return result.final_output_as(FinalReport)

"""Переиспользуемый мок-слой для LLM-вызовов агентов (под-gate 2e, оживлён на 3c).

Инфраструктура для E2E-тестов Gate 3+: подмена `Runner.run` каноническими
выходами агентов, без реальных вызовов OpenAI и без ключа. E2E-контракт
проверяет СБОРКУ трубы, а не качество текста (RULES §4, D-06).

Содержимое:
  * строители канонических выходов (`make_plan`, `make_report`);
  * `search_run(...)` — async side_effect для одиночного поиска (используется
    юнит-тестами поиска/предохранителей);
  * `ScenarioManagerModel` — сценарная (фейковая) модель менеджера: скриптует его
    ходы без LLM/ключа (разрешение DEFERRED #4, см. ниже);
  * `MockAgentRunner` — диспетчер `Runner.run` для всей трубы (менеджер→план→
    поиск→писатель), раздаёт канон по имени агента и записывает вызовы; менеджера
    прогоняет НАСТОЯЩИЙ Runner со сценарной моделью, суб-агенты — канон.

Разрешение DEFERRED #4 (двойник RunResult при извлечении вывода `.as_tool()`):
  `.as_tool()`-обёртки (планировщик/писатель) внутри дёргают вывод суб-агента НЕ
  через `final_output`, а через `ItemHelpers.text_message_outputs(result.new_items)`
  (см. Agent.as_tool в SDK). Поэтому двойник RunResult обязан нести `.new_items`
  со настоящим MessageOutputItem, иначе SDK падает на отсутствующем атрибуте.
  `_result(...)` ниже честно эмулирует ровно этот путь: кладёт в `new_items` один
  ассистентский message-элемент с текстом = сериализация выхода суб-агента (той
  же, что реальный агент вернул бы финальным сообщением). Это не заглушка
  результата — SDK-путь извлечения (`text_message_outputs`) исполняется по-настоящему.
"""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from agents import Model, ModelResponse, RunConfig
from agents.items import MessageOutputItem
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from planner_agent import WebSearchItem, WebSearchPlan
from writer_agent import ReportData
from evaluator_agent import EvaluationFeedback


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


def make_evaluation(
    score: int = 8,
    passed: bool = True,
    feedback: str = "Отчёт покрывает бриф; править нечего.",
    missing_topics: list[str] | None = None,
) -> EvaluationFeedback:
    """Канонический EvaluationFeedback (структура-контракт, не суждение).

    Дефолт — проходной (score >= 7, passed): happy-path evaluator-петли завершается
    на первой оценке без доработок (D-06 — проверяем сборку трубы с оценщиком, не
    качество и не сами решения LLM, RULES §4).
    """
    return EvaluationFeedback(
        score=score,
        passed=passed,
        feedback=feedback,
        missing_topics=missing_topics if missing_topics is not None else [],
    )


def term_from_input(input: str) -> str:
    """Вытащить поисковый запрос из input, который собирает _run_single_search."""
    if "Search term: " in input:
        return input.split("Search term: ", 1)[1].split("\n", 1)[0]
    return input


# ── Двойник RunResult (с честным путём извлечения .as_tool() — DEFERRED #4) ────

def _render_output_text(output) -> str:
    """Текст ассистентского сообщения суб-агента, как его вернул бы реальный агент.

    Агент со структурным output_type (WebSearchPlan/ReportData) финальным
    сообщением эмитит JSON схемы — воспроизводим это через model_dump_json.
    """
    if hasattr(output, "model_dump_json"):
        return output.model_dump_json()
    return str(output)


def _message_item(agent, text: str) -> MessageOutputItem:
    """Один ассистентский message-элемент для new_items двойника RunResult."""
    raw = ResponseOutputMessage(
        id="msg_mock",
        content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
        role="assistant",
        status="completed",
        type="message",
    )
    return MessageOutputItem(agent=agent, raw_item=raw)


def _result(output, agent=None):
    """Двойник RunResult: `.final_output`, `.final_output_as(...)` И `.new_items`.

    `.final_output` покрывает прямое потребление (напр. поиск: str(final_output)).
    `.new_items` покрывает извлечение вывода `.as_tool()`-обёрток (планировщик/
    писатель) через `text_message_outputs` — исходная суть DEFERRED #4. Когда
    `agent` передан, кладём настоящий message-элемент с сериализацией выхода, и
    SDK-путь извлечения исполняется честно (не заглушка).
    """
    items = [_message_item(agent, _render_output_text(output))] if agent is not None else []
    return SimpleNamespace(
        final_output=output,
        final_output_as=lambda _cls: output,
        new_items=items,
    )


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


# ── Сценарная модель менеджера (без LLM/ключа — разрешение DEFERRED #4) ────────

def _function_call(name: str, args: dict) -> ResponseFunctionToolCall:
    """Один вызов инструмента в формате Responses API для сценарной модели."""
    return ResponseFunctionToolCall(
        arguments=json.dumps(args),
        call_id=f"call_{name}",
        name=name,
        type="function_call",
    )


class ScenarioManagerModel(Model):
    """Детерминированная модель менеджера для E2E: скриптует его ходы без LLM.

    Заменяет реальную модель менеджера (вживляется через RunConfig(model=...) на
    прогоне менеджера). Эмитит по одному ходу за вызов get_response:
      1) tool-call plan_web_searches   → суб-агент PlannerAgent (канон)
      2) tool-call run_parallel_searches (план с 1 поиском) → Search agent (канон)
      3) tool-call write_report        → суб-агент WriterAgent (канон)
      4) финальное сообщение с ReportData JSON → SDK валидирует в ReportData (B1).
    Аргументы инструментов — минимально валидные; мок-диспетчер отдаёт канон вне
    зависимости от их содержимого, поэтому реальные данные между ходами не
    протаскиваются (тестируется сборка трубы, не решения LLM — RULES §4).
    """

    def __init__(self, report: ReportData):
        self._report = report
        self._step = 0

    async def get_response(self, *args, **kwargs) -> ModelResponse:
        self._step += 1
        if self._step == 1:
            output = [_function_call("plan_web_searches", {"input": "brief"})]
        elif self._step == 2:
            output = [
                _function_call(
                    "run_parallel_searches",
                    {"plan": {"searches": [{"reason": "r", "query": "q"}]}},
                )
            ]
        elif self._step == 3:
            output = [_function_call("write_report", {"input": "brief + summaries"})]
        else:
            # Финал: ассистентское сообщение с ReportData JSON — SDK провалидирует
            # его в ReportData (у менеджера output_type=ReportData, B1).
            raw = ResponseOutputMessage(
                id="msg_final",
                content=[
                    ResponseOutputText(
                        annotations=[],
                        text=self._report.model_dump_json(),
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
            output = [raw]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("ScenarioManagerModel не поддерживает стриминг.")


# ── Диспетчер Runner.run для всей трубы (E2E, Gate 3+) ─────────────────────────

@dataclass
class MockAgentRunner:
    """Мок-слой `Runner.run` для E2E: канон по имени агента + запись вызовов.

    Раздаёт: PlannerAgent → WebSearchPlan, Search agent → 'summary for <term>',
    WriterAgent → ReportData, EvaluatorAgent → EvaluationFeedback (Зона 3, 4c).
    Менеджера (ManagerAgent) прогоняет НАСТОЯЩИЙ Runner со сценарной моделью
    (ScenarioManagerModel) — так менеджер реально дёргает свои инструменты, а
    суб-агенты возвращаются в этот же диспетчер. Оценщик (EvaluatorAgent) зовёт
    evaluator-петля напрямую (не .as_tool()) — отдаём канон по имени, как остальным.

    ScenarioManagerModel создаётся ЗАНОВО на каждый диспатч ManagerAgent (свежий
    _step=0), поэтому несколько прогонов run_research подряд (доработки evaluator-
    петли) каждый проигрывают полный цикл ходов — состояние между прогонами не
    протекает (нюанс переиспользования снят конструкцией, а не заглушкой).

    Сигнатура dispatch принимает `starting_agent`/`input`: прямой запуск (менеджер,
    поиск) зовёт Runner.run позиционно, а `.as_tool()`-обёртки — по kwargs
    (starting_agent=..., input=...); оба варианта должны попадать в диспетчер.
    """

    plan: WebSearchPlan | None = None
    report: ReportData | None = None
    evaluation: EvaluationFeedback | None = None
    search_fail_on: set = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    _original: object = None

    def configure(self, *, plan=None, report=None, evaluation=None, search_fail_on=()):
        if plan is not None:
            self.plan = plan
        if report is not None:
            self.report = report
        if evaluation is not None:
            self.evaluation = evaluation
        self.search_fail_on = set(search_fail_on)
        return self

    async def dispatch(self, starting_agent=None, input=None, *args, **kwargs):
        agent = starting_agent
        name = getattr(agent, "name", "")
        self.calls.append(name)
        if name == "ManagerAgent":
            # Прогоняем настоящий менеджер со сценарной моделью; суб-агенты его
            # инструментов вернутся в этот же диспетчер (Runner.run пропатчен).
            report = self.report if self.report is not None else make_report()
            return await self._original(
                starting_agent,
                input,
                *args,
                run_config=RunConfig(model=ScenarioManagerModel(report)),
                **kwargs,
            )
        if name == "PlannerAgent":
            return _result(self.plan if self.plan is not None else make_plan(), agent)
        if name == "Search agent":
            term = term_from_input(input)
            if term in self.search_fail_on:
                raise RuntimeError(f"search failed: {term}")
            return _result(f"summary for {term}", agent)
        if name == "WriterAgent":
            return _result(self.report if self.report is not None else make_report(), agent)
        if name == "EvaluatorAgent":
            # Зона 3: оценщик зовётся напрямую evaluator-петлёй, потребляется через
            # final_output_as(EvaluationFeedback). Отдаём канон по имени агента.
            return _result(self.evaluation if self.evaluation is not None else make_evaluation(), agent)
        # Иной неизвестный агент — к настоящему Runner (задел).
        return await self._original(starting_agent, input, *args, **kwargs)

    def ran(self, agent_name: str) -> bool:
        return agent_name in self.calls

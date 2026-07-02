"""Юнит-тесты финализатора (под-gate 4d, D-09).

Финализатор — настоящий LLM-агент: оформление идёт через модель (получательство
handoff = ход LLM). Детерминированная косметика в коде ОТКЛОНЕНА владельцем
(несовместима с механикой handoff, см. D-09). Целостность содержания через transfer
юнит-тестом непокрываема (RULES §4) — ручная приёмка на живом прогоне (Gate 5/6).

Здесь тестируем только детерминируемое: схему FinalReport + механику/порядок стыка
петля→handoff (handoff настоящий и структурно доказуемый; срабатывает строго ПОСЛЕ
выхода из петли; лимит итераций петли им не затронут). Мок Runner.run, без ключа.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from finalizer_agent import FinalReport


def test_final_report_schema_valid():
    fr = FinalReport(title="T", presentation_markdown="# T\n\nтело")
    assert fr.title == "T"
    assert fr.presentation_markdown


def test_final_report_requires_presentation():
    with pytest.raises(ValidationError):
        FinalReport(title="T")


# ── Стык петля→handoff (вариант A: агент-шлюз) ────────────────────────────────

def test_gateway_has_real_handoff_to_finalizer():
    """Механика D-09: у шлюза настоящий Handoff на финализатор (не .as_tool)."""
    from agents import Handoff
    from finalizer_agent import finalizer_gateway

    # Ровно один handoff, и это настоящий Handoff-объект, целящий в FinalizerAgent.
    assert len(finalizer_gateway.handoffs) == 1
    h = finalizer_gateway.handoffs[0]
    assert isinstance(h, Handoff)                 # настоящая механика, не инструмент
    assert h.agent_name == "FinalizerAgent"


def _stitch_result(output):
    """Двойник RunResult для стыка: .final_output + .final_output_as(...)."""
    return SimpleNamespace(final_output=output, final_output_as=lambda _cls: output)


@pytest.mark.asyncio
async def test_handoff_happens_strictly_after_loop_and_limit_untouched(monkeypatch):
    """Порядок стыка: handoff — строго ПОСЛЕ выхода из петли; лимит итераций цел.

    Сценарий исчерпания лимита (все оценки ниже порога): петля гоняет initial +
    MAX_ROUNDS доработок, затем research_and_finalize делает ЕДИНСТВЕННЫЙ прогон
    шлюза. Проверяем: FinalizerGateway вызван ровно один раз и ПОСЛЕ всех оценок,
    а число прогонов менеджера/оценщика ровно 1 + MAX_ROUNDS — handoff не добавил и
    не убавил итераций петли (D-02).
    """
    from agents import Runner
    from _mocks import make_report, make_evaluation
    from evaluator_loop import MAX_ROUNDS
    from finalizer_agent import research_and_finalize

    order: list[str] = []
    evals = iter([make_evaluation(score=3), make_evaluation(score=4), make_evaluation(score=5)])
    final = FinalReport(title="T", presentation_markdown="# T\n\nтело")

    async def run(agent, input=None, *args, **kwargs):
        name = getattr(agent, "name", "")
        order.append(name)
        if name == "ManagerAgent":
            return _stitch_result(make_report())
        if name == "EvaluatorAgent":
            return _stitch_result(next(evals))
        if name == "FinalizerGateway":
            return _stitch_result(final)
        raise AssertionError(f"неожиданный агент в тесте стыка: {name!r}")

    monkeypatch.setattr(Runner, "run", run)

    result = await research_and_finalize("бриф")

    # Стык вернул оформленную выдачу финализатора.
    assert isinstance(result, FinalReport)

    # Handoff-шлюз вызван ровно один раз и ПОСЛЕ всех оценок (строго после петли).
    assert order.count("FinalizerGateway") == 1
    assert order[-1] == "FinalizerGateway"
    last_eval = max(i for i, n in enumerate(order) if n == "EvaluatorAgent")
    assert order.index("FinalizerGateway") > last_eval

    # Лимит итераций петли не затронут стыком: ровно initial + MAX_ROUNDS прогонов.
    assert order.count("EvaluatorAgent") == 1 + MAX_ROUNDS
    assert order.count("ManagerAgent") == 1 + MAX_ROUNDS

"""Общие фикстуры тестов (под-gate 2e).

Мок-слой LLM-вызовов вынесен в `_mocks.py`; здесь — фикстура, поднимающая
диспетчер `Runner.run` для E2E-трубы. Реальных вызовов/ключа нет (D-06).
"""

import pytest

from _mocks import MockAgentRunner


@pytest.fixture
def mock_agent_runner(monkeypatch):
    """Подменяет Runner.run диспетчером с каноническими выходами агентов.

    Патч на классе Runner покрывает все `from agents import Runner` (общий объект):
    и прямые вызовы (поиск), и вызовы из tool-обёрток менеджера на Gate 3.
    monkeypatch откатывает подмену после теста автоматически.
    """
    from agents import Runner

    runner = MockAgentRunner()
    runner._original = Runner.run
    monkeypatch.setattr(Runner, "run", runner.dispatch)
    return runner

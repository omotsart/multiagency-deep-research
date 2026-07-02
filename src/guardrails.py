"""Предохранители автономности (D-03).

Здесь — детерминированная механика лимитов, которую автономный менеджер
подхватит на Gate 3. Сам менеджер тут НЕ создаётся (это Gate 3).

Два предохранителя:
  * `ResearchContext` — бюджет поисков, передаётся в `Runner.run(..., context=...)`;
    поисковый инструмент читает/списывает его через `RunContextWrapper`.
  * `MAX_TURNS` — потолок ходов агента, передаётся в `Runner.run(..., max_turns=...)`.

Семантика бюджета: считаем ОТДЕЛЬНЫЕ поиски (каждый веб-поиск = один вызов
search_agent = реальная стоимость). Пачка из N параллельных поисков списывает N.
Списываем по числу попыток (упавший поиск тоже потратил попытку).
"""

from dataclasses import dataclass

# --- Значения по умолчанию (тюнинг, не архитектура; Gate 3 может переопределить) ---
# Потолок отдельных поисков на весь прогон. С запасом на вторую волну
# (планировщик по умолчанию даёт HOW_MANY_SEARCHES=3 на волну).
DEFAULT_SEARCH_BUDGET = 12

# Потолок ходов автономного менеджера. Подключается в Runner.run(manager, ...) на
# Gate 3 — здесь менеджера ещё нет, поэтому пока это готовая константа.
MAX_TURNS = 15


@dataclass
class ResearchContext:
    """Контекст автономного прогона — носитель бюджета поисков (предохранитель).

    Передаётся на Gate 3 как `Runner.run(manager, ..., context=ResearchContext())`.
    Инструмент поиска получает его через `RunContextWrapper[ResearchContext]`,
    проверяет остаток и списывает израсходованное. В LLM контекст НЕ уходит.
    """

    search_budget: int = DEFAULT_SEARCH_BUDGET
    searches_used: int = 0

    @property
    def searches_remaining(self) -> int:
        """Сколько поисков ещё можно выполнить (не опускается ниже 0)."""
        return max(0, self.search_budget - self.searches_used)

    @property
    def is_exhausted(self) -> bool:
        return self.searches_remaining <= 0

    def spend(self, n: int) -> None:
        """Списать n израсходованных поисков (по числу попыток)."""
        if n < 0:
            raise ValueError("Нельзя списать отрицательное число поисков.")
        self.searches_used += n

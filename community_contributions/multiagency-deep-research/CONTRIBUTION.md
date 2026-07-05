# MultiAgency DeepResearch — community contribution

Автономный агент-исследователь на **OpenAI Agents SDK** + **Gradio**, развивающий
учебный пример `deep_research` в настоящую мультиагентную систему с автономией и
контролем качества.

## Что нового по сравнению с базовым `deep_research`
- **Прелюдия (человек в цикле):** `clarifier_agent` задаёт 3 уточняющих вопроса →
  склейка `тема + Q&A → brief` как единый источник намерения.
- **Автономное ядро (agents-as-tools):** `manager_agent` сам решает число и
  направление поисков, включая динамическую вторую волну по пробелам в данных.
- **Контроль качества (Evaluator–Optimizer):** `evaluator_agent` + детерминированная
  петля в коде дорабатывает отчёт до порога либо до лимита итераций.
- **Один изолированный handoff** на финальном оформлении (`finalizer_agent`) —
  демонстрация обоих паттернов оркестрации.
- **Живой UI из трёх экранов** с накопительным логом, счётчиками и терминальными
  плашками; деплой на Hugging Face Spaces.

## Ссылки
- **Живой Space:** https://huggingface.co/spaces/ovm26rus/multiagency-deep-research
- **Канонический репозиторий:** https://github.com/omotsart/multiagency-deep-research

## Запуск и тесты
См. `README.md` в этой папке. Тесты — на моках LLM, без реальных вызовов и без ключа
(`pip install -r requirements.txt -r requirements-dev.txt` → `python -m pytest`).

## Примечание
Это самодостаточный снимок проекта (полная копия исходников, тестов, deploy-артефактов
и документов процесса). Деплой на Spaces идёт через `sdk: docker` (см. `docs/DECISIONS.md`,
D-16) — чтобы HF не впрыскивал `gradio[mcp]`, конфликтующий с `openai-agents`.

"""
MultiAgency DeepResearch — точка входа приложения (D-11: display-имя бренда).

Требование Hugging Face Spaces: точка входа называется app.py и лежит в корне
(Gate 6). Это оболочка бренда; внутренние имена агентов/модулей в src/ не трогаются
(D-11). Легаси-пример `src/deep_research.py` (учебная база) остаётся нетронутым — мы
эволюционируем к трёхэкранному флоу здесь.

Под-шаг 5a (Gate 5): КАРКАС трёх экранов + навигация. Только структура и
переключение видимости через `gr.State` + `visible`. БЕЗ подписки на поток петли
(5b) и БЕЗ провокатора терминалов (5c). Кнопка «Исследовать» на 5a лишь переключает
на экран 3 с плейсхолдером — петля НЕ подключена.

Контракт вида — D-14 (экран 3), Подход А — D-04 (ровно 3 статичных текстбокса, без
`@gr.render`), email-галочка — D-05 (демо, без реальной отправки, адреса не
хардкодятся).
"""

import gradio as gr
from dotenv import load_dotenv

load_dotenv(override=True)

APP_TITLE = "MultiAgency DeepResearch"

# CSS только через свои классы (безопасно — критерий Gate 5). Минимум на 5a:
# приглушённые резюме-строки свёрнутых экранов (D-14.4) и рамка плейсхолдеров.
CUSTOM_CSS = """
.mad-summary { opacity: 0.85; font-size: 0.95em; border-left: 3px solid var(--primary-500);
               padding-left: 0.75em; }
.mad-placeholder { opacity: 0.6; font-style: italic; border: 1px dashed var(--border-color-primary);
                   border-radius: 8px; padding: 1em; text-align: center; }
"""


# ── Навигация: чистые обработчики переходов (структура, без данных петли) ──────

def _go_to_clarify(topic: str):
    """Экран 1 → 2. Тема сворачивается в резюме-строку (контекст на экране 2)."""
    recap = f"**Тема:** {topic.strip()}" if topic.strip() else "**Тема:** _(не указана)_"
    return (
        gr.update(visible=False),   # screen_topic
        gr.update(visible=True),    # screen_clarify
        2,                          # screen_state
        recap,                      # topic_recap_2
    )


def _go_to_run(topic: str, q1: str, q2: str, q3: str, email: bool):
    """Экран 2 → 3. Экраны 1–2 сворачиваются в резюме-строки (D-14.4, без «Изменить»)."""
    answers = [a.strip() for a in (q1, q2, q3)]
    summary = "\n\n".join(
        [
            f"**Тема:** {topic.strip() or '—'}",
            "**Уточнения:** " + " · ".join(a or "—" for a in answers),
            "**Email-копия:** " + ("да (демо)" if email else "нет"),
        ]
    )
    return (
        gr.update(visible=False),   # screen_clarify
        gr.update(visible=True),    # screen_run
        3,                          # screen_state
        summary,                    # run_summary
    )


def _reset():
    """Сброс к экрану 1 (навигация). Терминал-привязанный сброс D-14.2 — на 5b."""
    return (
        gr.update(visible=True),    # screen_topic
        gr.update(visible=False),   # screen_clarify
        gr.update(visible=False),   # screen_run
        1,                          # screen_state
    )


def build_ui() -> gr.Blocks:
    """Собрать трёхэкранный каркас Gate 5 (5a: структура + навигация)."""
    with gr.Blocks(
        theme=gr.themes.Default(primary_hue="sky"),
        title=APP_TITLE,
        css=CUSTOM_CSS,
    ) as ui:
        gr.Markdown(f"# {APP_TITLE}")

        # Текущий экран (1/2/3) — навигация через gr.State + visible (критерий Gate 5).
        screen_state = gr.State(1)

        # ── Экран 1 — тема ───────────────────────────────────────────────────
        with gr.Column(visible=True) as screen_topic:
            gr.Markdown("### Шаг 1 — тема исследования")
            topic_input = gr.Textbox(
                label="Что исследуем?",
                placeholder="Например: влияние ИИ на рынок труда в ЕС на горизонте 5 лет",
                lines=2,
            )
            start_btn = gr.Button("Начать", variant="primary")

        # ── Экран 2 — уточнения (Подход А: РОВНО 3 статичных текстбокса, D-04) ─
        with gr.Column(visible=False) as screen_clarify:
            topic_recap_2 = gr.Markdown(elem_classes="mad-summary")
            gr.Markdown("### Шаг 2 — уточнения")
            gr.Markdown(
                "_Ответьте на три уточняющих вопроса — они войдут в бриф. "
                "(Текст вопросов подставит clarifier на следующем под-шаге.)_"
            )
            q1 = gr.Textbox(label="Уточняющий вопрос 1")
            q2 = gr.Textbox(label="Уточняющий вопрос 2")
            q3 = gr.Textbox(label="Уточняющий вопрос 3")
            email_check = gr.Checkbox(
                label="Прислать копию отчёта на email (демо — реальная отправка не выполняется)",
                value=False,
            )
            research_btn = gr.Button("Исследовать", variant="primary")

        # ── Экран 3 — прогон (5a: ПУСТОЙ каркас; живое наполнение — 5b) ───────
        with gr.Column(visible=False) as screen_run:
            run_summary = gr.Markdown(elem_classes="mad-summary")
            gr.Markdown("### Шаг 3 — исследование")
            # Двухколоночная раскладка заложена структурно (D-14): слева телеметрия
            # (scale=1), справа отчёт (scale=2). Данные подключит 5b.
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("**Телеметрия**")
                    gr.Markdown(
                        "здесь пойдёт прогон — лог, счётчики, версия N/M (5b)",
                        elem_classes="mad-placeholder",
                    )
                with gr.Column(scale=2):
                    gr.Markdown("**Отчёт**")
                    gr.Markdown(
                        "здесь появится отчёт и плашка терминала (5b)",
                        elem_classes="mad-placeholder",
                    )
            new_research_btn = gr.Button("Новое исследование")

        # ── Переключение экранов (gr.State + visible) ────────────────────────
        start_btn.click(
            _go_to_clarify,
            inputs=topic_input,
            outputs=[screen_topic, screen_clarify, screen_state, topic_recap_2],
        )
        research_btn.click(
            _go_to_run,
            inputs=[topic_input, q1, q2, q3, email_check],
            outputs=[screen_clarify, screen_run, screen_state, run_summary],
        )
        new_research_btn.click(
            _reset,
            inputs=None,
            outputs=[screen_topic, screen_clarify, screen_run, screen_state],
        )

    return ui


if __name__ == "__main__":
    build_ui().launch(inbrowser=True)

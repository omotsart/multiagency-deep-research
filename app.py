"""
Deep Research — точка входа приложения.

Требование Hugging Face Spaces: точка входа называется app.py и лежит в корне.
Это тонкая оболочка: реальный UI собирается в src/ и импортируется сюда.

На Gate 0 — заглушка, подтверждающая, что запуск проходит без ошибок.
Полноценный интерфейс подключается на Gate 5 (UI).
"""

import gradio as gr
from dotenv import load_dotenv

load_dotenv(override=True)


def build_ui() -> gr.Blocks:
    """Собрать интерфейс. На Gate 5 здесь появится реальный трёхэкранный флоу."""
    with gr.Blocks(title="Deep Research") as ui:
        gr.Markdown("# Deep Research")
        gr.Markdown("Каркас проекта (Gate 0). Интерфейс появится на Gate 5.")
    return ui


if __name__ == "__main__":
    build_ui().launch()
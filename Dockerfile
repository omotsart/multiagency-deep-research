# MultiAgency DeepResearch — deploy на Hugging Face Spaces (sdk: docker, см. D-16).
# Docker вместо sdk:gradio, чтобы HF НЕ впрыскивал gradio[oauth,mcp] (тянет mcp==1.10.1,
# конфликт с openai-agents==0.4.2 -> mcp>=1.11.0). Здесь ставим голый gradio без extras —
# mcp тянет только openai-agents. Оба жёстких пина целы, версии не менялись.

# База = локальная версия Python, на которой держатся 54 passed (python 3.12.7).
FROM python:3.12.7-slim

# HF Spaces исполняет контейнер как non-root uid 1000 — заводим пользователя.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    # Gradio читает адрес/порт из окружения — app.py НЕ трогаем (D-14/D-11: код заморожен).
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR /home/user/app

# Сначала requirements (кэш слоя), затем код. Голый requirements.txt — без extras.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# app_port в README-хедере = 7860 = GRADIO_SERVER_PORT.
EXPOSE 7860

# Точка входа — app.py в корне (критерий Gate 6).
CMD ["python", "app.py"]

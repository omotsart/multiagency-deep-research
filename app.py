"""
MultiAgency DeepResearch — точка входа приложения (D-11: display-имя бренда).

Требование Hugging Face Spaces: точка входа называется app.py и лежит в корне
(Gate 6). Это оболочка бренда; внутренние имена агентов/модулей в src/ не трогаются
(D-11). Легаси-пример `src/deep_research.py` (учебная база) остаётся нетронутым.

Под-шаг 5b (Gate 5): экран 3 ОЖИВАЕТ над потоком `ProgressEvent` (D-13.2):
подписка на `research_with_evaluation(brief)`, накопительный лог + счётчики + карточки
оценщика + бейдж черновика + три плашки терминала (D-14.2). Провокатор терминалов
(D-14.3) — офлайн, через env `MAD_FORCE_TERMINAL`, ВНЕ живого UI.

Вариант A (ПРИНЯТ владельцем): тело отчёта показывается на терминале `final` (там
`report` есть по D-13.2); во время прогона правая колонка — бейдж «Черновик №N ·
дорабатывается» + текущий feedback оценщика. Живой per-iteration черновик тела —
DEFERRED #10 (требует правки инварианта D-13.2, вне 5b).

Контракты: вид — D-14; Подход А — D-04 (ровно 3 статичных текстбокса, без
`@gr.render`); email-галочка — D-05 (демо, без отправки, адрес не хардкодится).
"""

import os
import re
import sys
import tempfile
import time

# app.py в корне; исходники — в src/. Добавляем src на путь для импорта петли
# (pytest использует pythonpath=src; при `python app.py` из корня — вот этот мост).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import gradio as gr
from dotenv import load_dotenv

from brief import build_brief
from evaluator_loop import research_with_evaluation, MAX_ROUNDS, SCORE_THRESHOLD
from guardrails import DEFAULT_SEARCH_BUDGET

load_dotenv(override=True)

APP_TITLE = "MultiAgency DeepResearch"

# Тексты трёх статичных вопросов (Подход А, D-04). В реальном флоу их подставит
# clarifier; на 5b — фиксированные, идут и как label'ы, и как questions в бриф.
QUESTION_LABELS = (
    "Какой охват/регион интересует?",
    "Какой горизонт или временные рамки?",
    "Для кого отчёт и какой глубины?",
)

M_VERSIONS = MAX_ROUNDS + 1  # всего версий-черновиков возможно (D-14.1: M = MAX_ROUNDS+1).

# Режим темы (светлый/тёмный) — переключаемый, НЕ захардкожен. По умолчанию `light`:
# тема sky (D-04) светлая, но система может рендерить тёмной (prefers-color-scheme).
# `MAD_THEME=light|dark|system`. Форсим через ОФИЦИАЛЬНЫЙ механизм Gradio — query-param
# `__theme` (серверного "force light" в Gradio нет; query-param работает одинаково
# локально и на Spaces — стабильно к Gate 6). JS проставляет режим на загрузке, ТОЛЬКО
# если он не задан в URL явно → владелец переопределяет через `?__theme=dark`, а по
# умолчанию видит светлую как в макете. `system` — не форсим (уважаем ОС).
THEME_MODE = os.environ.get("MAD_THEME", "light").strip().lower()
# Значение радио «по умолчанию» до синхронизации с URL на загрузке (см. _sync_theme_js).
RADIO_THEME_DEFAULT = THEME_MODE if THEME_MODE in ("light", "dark") else "light"


def _force_theme_js(mode: str):
    """JS-хук на загрузку: проставить `?__theme=mode`, если режим не задан в URL."""
    if mode not in ("light", "dark"):
        return None
    return (
        "() => { const u = new URL(window.location.href);"
        "  if (!u.searchParams.has('__theme')) {"
        f"    u.searchParams.set('__theme', '{mode}');"
        "    window.location.replace(u.toString()); } }"
    )


# JS для синхронизации радио с ФАКТИЧЕСКОЙ темой из URL на каждой загрузке: вернуть
# `?__theme` (или дефолт). Без этого радио на сервере всегда садится в дефолт (light),
# а экран — по URL → рассинхрон «радио light, экран dark». Приоритет: URL > дефолт.
_SYNC_THEME_JS = (
    "() => (new URLSearchParams(window.location.search).get('__theme')) "
    f"|| '{RADIO_THEME_DEFAULT}'"
)

# JS клика по радио: проставить `?__theme=<выбор>` и перезагрузить (штатный механизм
# Gradio, стабилен к Spaces/Gate 6). Навешивается на .input (ТОЛЬКО пользовательский
# клик) — иначе программная синхронизация из .load зациклила бы перезагрузку.
_SWITCH_THEME_JS = (
    "(m) => { const u = new URL(window.location.href);"
    "  u.searchParams.set('__theme', m);"
    "  window.location.replace(u.toString()); }"
)

# CSS только через свои классы (D-04 — минимум, страховка от «перекошенного» UI).
CUSTOM_CSS = """
.mad-summary { opacity: 0.85; font-size: 0.95em; border-left: 3px solid var(--primary-500);
               padding-left: 0.75em; }
.mad-placeholder { opacity: 0.6; font-style: italic; border: 1px dashed var(--border-color-primary);
                   border-radius: 8px; padding: 1em; text-align: center; }
.mad-counters { font-size: 1.05em; }
.mad-badge { font-weight: 600; opacity: 0.9; }
.mad-term { padding: 0.8em 1em; border-radius: 8px; font-weight: 600; }
.mad-term.ok   { background: rgba(16,185,129,0.12);  border-left: 4px solid #10b981; }
.mad-term.warn { background: rgba(245,158,11,0.14);  border-left: 4px solid #f59e0b; }
.mad-term.fail { background: rgba(239,68,68,0.12);   border-left: 4px solid #ef4444; }
.mad-log textarea { font-family: ui-monospace, monospace; font-size: 0.85em; }

/* CTA-кнопки (все): терракот Anthropic clay, единый стиль, по центру, ширина под
   текст. ПОЧЕМУ прошлый заход не сработал: в Gradio 5 elem_classes у gr.Button
   вешается на САМ <button>, поэтому селектор `.mad-cta button` целил вложенный
   button (которого нет) → фон не применялся, тема (var(--button-*-background-fill))
   побеждала. Здесь целим сам элемент кнопки (`.mad-cta`/`button.mad-cta`), поднимаем
   специфичность префиксом `.gradio-container` (бьём тематические `.primary` и пр.),
   гасим фон-градиент/тень темы и ставим !important. Терракот (кирпичный, красноватый)
   намеренно отличается от амбера жёлтой плашки .mad-term.warn (их D-14.2 не трогаем). */
.mad-cta-row { justify-content: center !important; gap: 0.8rem !important; }
.gradio-container .mad-cta,
.gradio-container button.mad-cta,
.gradio-container .mad-cta button {
    background: #C15F3C !important;
    background-image: none !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: none !important;
    font-weight: 600 !important;
    flex: 0 0 auto !important;
    width: fit-content !important;
    min-width: 9rem !important;
    min-height: 2.5rem !important;
    padding: 0.5rem 1.6rem !important;
}
.gradio-container .mad-cta:hover,
.gradio-container button.mad-cta:hover,
.gradio-container .mad-cta button:hover { background: #9E4227 !important; }

/* Переключатель темы — убрать фон-панель/рамку блока gr.Radio (висел в серой плашке). */
.mad-theme { background: transparent !important; border: none !important;
             box-shadow: none !important; max-width: 14rem; }
/* Точка активного радио темы — терракот как кнопки (было голубое sky primary). Целим
   сам <input type=radio>: его дот рисует браузерный accent-color (Gradio ставит его в
   primary-hue). Специфичность .gradio-container + !important бьют тему. Неактивные —
   нейтральные (нативный дефолт). :checked-фолбэк на случай кастомной отрисовки дота. */
.gradio-container .mad-theme input[type="radio"] { accent-color: #C15F3C !important; }
.gradio-container .mad-theme input[type="radio"]:checked {
    background-color: #C15F3C !important; border-color: #C15F3C !important;
    box-shadow: 0 0 0 3px #C15F3C inset !important;
}
"""


# ── Навигация экранов (каркас 5a — принят, не меняем логику переходов) ─────────

def _go_to_clarify(topic: str):
    """Экран 1 → 2. Тема сворачивается в резюме-строку."""
    recap = f"**Тема:** {topic.strip()}" if topic.strip() else "**Тема:** _(не указана)_"
    return (
        gr.update(visible=False),   # screen_topic
        gr.update(visible=True),    # screen_clarify
        2,                          # screen_state
        recap,                      # topic_recap_2
    )


def _go_to_run(topic: str, q1: str, q2: str, q3: str, email: bool):
    """Экран 2 → 3. Экраны 1–2 сворачиваются в резюме-строки (D-14.4, без «Изменить»).

    Здесь же СТАРТУЕТ таймер экрана 3: фиксирует старт, фазу «running» и включает
    `gr.Timer`. Таймер — ЕДИНСТВЕННЫЙ источник обновлений ячейки времени (см. `_tick`);
    поток петли её НЕ трогает (разведение источников — против гонки).
    """
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
        time.monotonic(),           # run_start (State)
        "running",                  # run_phase (State)
        gr.update(active=True),     # run_timer — включить тик
    )


def _reset():
    """Сброс к экрану 1 (навигация). Доступен на ЛЮБОМ терминале (D-14.2) — кнопка
    видна на экране 3 всегда, включая failed/graceful. Живую область экрана 3 не
    чистим (скрыта, перезапишется первым событием нового прогона), но ПОЛЯ ВВОДА
    очищаем — новый прогон с чистого листа: тема, 3 вопроса, галка email → дефолт.
    Таймер гасим: фаза «idle» + выключаем `gr.Timer` (следующий прогон включит заново)."""
    return (
        gr.update(visible=True),    # screen_topic
        gr.update(visible=False),   # screen_clarify
        gr.update(visible=False),   # screen_run
        1,                          # screen_state
        "idle",                     # run_phase (State)
        gr.update(active=False),    # run_timer — выключить тик
        gr.update(value=""),        # topic_input
        gr.update(value=""),        # q1
        gr.update(value=""),        # q2
        gr.update(value=""),        # q3
        gr.update(value=False),     # email_check
    )


# ── Подписка на поток петли (сердце 5b) ───────────────────────────────────────

def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _report_filename(topic: str) -> str:
    """Имя .md-файла из темы, санитизированное под файловую систему."""
    slug = re.sub(r"[^\w\- ]+", "", topic, flags=re.UNICODE).strip()
    slug = re.sub(r"\s+", "_", slug)[:60]
    return f"{slug or 'report'}.md"


def _write_report_md(topic: str, markdown_report: str) -> str:
    """Записать отчёт во временный .md-файл и вернуть путь (для gr.DownloadButton)."""
    path = os.path.join(tempfile.gettempdir(), _report_filename(topic))
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown_report)
    return path


def _tick(run_start: float, run_end: float, run_phase: str):
    """Тик `gr.Timer` (раз в секунду) — ЕДИНСТВЕННЫЙ писатель ячейки времени.

    Разведение источников (против гонки): таймер трогает ТОЛЬКО `timer_md` (и
    выключает себя на терминале), поток петли — все остальные компоненты. Они не
    пишут в одни и те же ячейки.
      * running → «⏳ Идёт исследование · M:SS» (тикает вживую, даже пока поток ждёт
        ядро и не эмитит событий);
      * done    → «✓ Завершено · M:SS» по замороженному времени терминала и
        выключение таймера (`active=False`) — дальше не тикает;
      * idle    → ничего не трогаем.
    """
    if run_phase == "running":
        return gr.update(value=f"⏳ Идёт исследование · {_mmss(time.monotonic() - run_start)}"), gr.update()
    if run_phase == "done":
        return gr.update(value=f"✓ Завершено · {_mmss(run_end - run_start)}"), gr.update(active=False)
    return gr.update(), gr.update()


def _event_source(brief: str):
    """Источник событий: настоящая петля ИЛИ офлайн-провокатор (D-14.3, вне UI).

    Провокатор подключается ЛЕНИВО и только по env `MAD_FORCE_TERMINAL` — это
    приёмочная обвязка, не элемент интерфейса. В нормальном прогоне идёт петля.
    """
    force = os.environ.get("MAD_FORCE_TERMINAL")
    if force:
        from acceptance_provocateur import scripted_stream
        return scripted_stream(force.strip().lower())
    return research_with_evaluation(brief)


async def _run_stream(topic: str, q1: str, q2: str, q3: str, email: bool):
    """Async-генератор: подписка на поток ProgressEvent, обновление экрана 3 кортежем.

    Требует `.queue()` (включён в build_ui). За каждый yield обновляет счётчики, лог,
    карточки оценщика, бейдж/тело черновика и плашки терминала. Тело отчёта — только
    на `final` (вариант A / D-13.2: `report` есть лишь у `final`).
    """
    brief = build_brief(topic, questions=list(QUESTION_LABELS), answers=[q1, q2, q3])

    log_lines: list[str] = []
    eval_cards: list[str] = []
    searches_used = 0
    version_n = 1          # текущая версия в работе (round + 1).
    score = None

    # Тексты плашек терминала заполняются в терминальных ветках; snapshot их читает.
    # Правило плашки (D-14.2, уточнено по итогу 5b — только в UI, петля не тронута):
    #   зелёная  ⇔ final И score >= SCORE_THRESHOLD          (порог взят);
    #   жёлтая   ⇔ final И (graceful ИЛИ score < THRESHOLD)  (годный отчёт, порог не взят);
    #   красная  ⇔ failed                                    (отчёта нет).
    _ok_text = ""
    _warn_text = ""
    _failed_text = ""
    _download_path = None   # путь к .md — заполняется на final (есть отчёт), D-13.2.

    def snapshot(*, badge: str, report_md: str, term: str | None):
        """Обновления живых компонентов экрана 3 (БЕЗ ячейки времени — её ведёт _tick)."""
        score_txt = f"{score}/7" if score is not None else "—/7"
        return (
            gr.update(value=f"**Версия** {version_n}/{M_VERSIONS}"),       # versions_counter
            gr.update(value=f"**Поисков** {searches_used}/{DEFAULT_SEARCH_BUDGET}"),  # searches_counter
            gr.update(value=f"**Score** {score_txt}"),                     # score_counter
            gr.update(value="\n".join(log_lines)),                         # log_box
            gr.update(value="\n\n---\n\n".join(eval_cards) or "_Оценок пока нет._"),  # eval_md
            gr.update(value=badge, visible=bool(badge)),                   # draft_badge
            gr.update(value=report_md),                                    # report_body
            gr.update(visible=term == "ok", value=_ok_text),               # terminal_ok (зелёная)
            gr.update(visible=term == "warn", value=_warn_text),           # terminal_warn (жёлтая)
            gr.update(visible=term == "failed", value=_failed_text),       # terminal_failed (красная)
            # Скачать .md — только когда есть отчёт (final: ok|warn); на failed нет.
            gr.update(value=_download_path, visible=_download_path is not None),  # download_btn
        )

    def frame(*, running: bool, badge: str, report_md: str, term: str | None):
        """Кадр потока = snapshot + фаза/финальное время для таймера (States).

        Поток НЕ пишет `timer_md` — только фазу и конец прогона в States, из которых
        `_tick` рисует время. На терминале (`running=False`) фаза «done», `run_end`
        замораживает время → таймер один раз рисует итог и выключается.
        """
        phase = "running" if running else "done"
        end = 0.0 if running else time.monotonic()
        return (*snapshot(badge=badge, report_md=report_md, term=term), phase, end)

    # Стартовый кадр: очистить прошлый прогон, скрыть плашки, показать бейдж «готовится».
    log_lines.append("▸ Старт исследования…")
    yield frame(running=True, badge="Черновик №1 · готовится", report_md="", term=None)

    async for ev in _event_source(brief):
        stage, p = ev.stage, ev.payload

        if stage == "research_started":
            continue  # стартовую строку уже показали

        elif stage == "draft_ready":
            version_n = p["round"] + 1
            searches_used = p.get("searches_used", searches_used)
            log_lines.append(f"▸ Черновик версии {version_n} собран · поисков {searches_used}/{DEFAULT_SEARCH_BUDGET}")
            yield frame(running=True, badge=f"Черновик №{version_n} · дорабатывается",
                        report_md="", term=None)

        elif stage == "evaluation":
            version_n = p["round"] + 1
            score = p["score"]
            searches_used = p.get("searches_used", searches_used)
            fb = p.get("feedback", "")
            eval_cards.append(f"**Версия {version_n} · score {score}/7**\n\n{fb}")
            log_lines.append(f"▸ Оценка версии {version_n}: score {score}/7")
            yield frame(running=True, badge=f"Черновик №{version_n} · оценён",
                        report_md="", term=None)

        elif stage == "revision_started":
            version_n = p["round"] + 1
            log_lines.append(f"▸ Доработка №{p['round']} → версия {version_n}…")
            yield frame(running=True, badge=f"Черновик №{version_n} · дорабатывается",
                        report_md="", term=None)

        elif stage == "final":
            searches_used = p.get("searches_used", searches_used)
            if p.get("score") is not None:
                score = p["score"]
            report_md = ev.report.markdown_report if ev.report is not None else ""
            if report_md:   # final несёт отчёт (ok|warn) → готовим .md к скачиванию.
                _download_path = _write_report_md(topic, report_md)
            graceful = bool(p.get("graceful"))
            threshold_met = score is not None and score >= SCORE_THRESHOLD
            score_txt = f"score {score}/7" if score is not None else "score —/7"
            if threshold_met and not graceful:
                # Зелёная: порог взят (D-14.2).
                term = "ok"
                _ok_text = f"✅ **Завершено.** Порог взят — {score_txt}. Отчёт утверждён."
                log_lines.append(f"▸ Готово — порог взят ({score_txt}), отчёт утверждён")
            else:
                # Жёлтая: годный отчёт есть, но порог не взят — по сбою ИЛИ по лимиту.
                term = "warn"
                reason = (
                    "получено после сбоя прогона" if graceful
                    else "порог не взят — выход по лимиту доработок"
                )
                _warn_text = (
                    f"⚠️ **Есть отчёт, но порог не взят.** {reason.capitalize()}; "
                    f"показана лучшая версия ({score_txt})."
                )
                log_lines.append(f"▸ Готово ({reason}) — лучшая версия, {score_txt}")
            yield frame(running=False, badge="", report_md=report_md, term=term)

        elif stage == "failed":
            _failed_text = f"⛔ **Сбой прогона.** {p.get('message', 'Причина не указана.')}"
            log_lines.append("▸ Сбой прогона — отчёт не собран")
            yield frame(running=False, badge="", report_md="", term="failed")


def build_ui() -> gr.Blocks:
    """Собрать трёхэкранный интерфейс Gate 5 (5a каркас + 5b живой экран 3)."""
    with gr.Blocks(
        theme=gr.themes.Default(primary_hue="sky"),
        title=APP_TITLE,
        css=CUSTOM_CSS,
        js=_force_theme_js(THEME_MODE),   # форс светлый/тёмный (переключаемо, D-04 цел)
    ) as ui:
        # Шапка: заголовок + ненавязчивый переключатель темы в углу.
        with gr.Row():
            gr.Markdown(f"# {APP_TITLE}")
            theme_radio = gr.Radio(
                choices=["light", "dark"],
                value=RADIO_THEME_DEFAULT,   # начальное; на загрузке синхронизируется с URL
                label="Тема",
                elem_classes="mad-theme",
                scale=0,
                min_width=160,
            )
        screen_state = gr.State(1)
        # Состояние таймера экрана 3 (для _tick; разведено с потоком петли).
        run_start = gr.State(0.0)
        run_end = gr.State(0.0)
        run_phase = gr.State("idle")

        # ── Экран 1 — тема ───────────────────────────────────────────────────
        with gr.Column(visible=True) as screen_topic:
            gr.Markdown("### Шаг 1 — тема исследования")
            topic_input = gr.Textbox(
                label="Что исследуем?",
                placeholder="Например: влияние ИИ на рынок труда в ЕС на горизонте 5 лет",
                lines=2,
            )
            with gr.Row(elem_classes="mad-cta-row"):
                start_btn = gr.Button("Начать", elem_classes="mad-cta")

        # ── Экран 2 — уточнения (Подход А: РОВНО 3 статичных текстбокса, D-04) ─
        with gr.Column(visible=False) as screen_clarify:
            topic_recap_2 = gr.Markdown(elem_classes="mad-summary")
            gr.Markdown("### Шаг 2 — уточнения")
            gr.Markdown("_Ответьте на три уточняющих вопроса — они войдут в бриф._")
            q1 = gr.Textbox(label=QUESTION_LABELS[0])
            q2 = gr.Textbox(label=QUESTION_LABELS[1])
            q3 = gr.Textbox(label=QUESTION_LABELS[2])
            email_check = gr.Checkbox(
                label="Прислать копию отчёта на email (демо — реальная отправка не выполняется)",
                value=False,
            )
            with gr.Row(elem_classes="mad-cta-row"):
                research_btn = gr.Button("Исследовать", elem_classes="mad-cta")

        # ── Экран 3 — прогон (5b: живой над потоком ProgressEvent) ────────────
        with gr.Column(visible=False) as screen_run:
            run_summary = gr.Markdown(elem_classes="mad-summary")
            gr.Markdown("### Шаг 3 — исследование")
            with gr.Row():
                # Левая колонка — телеметрия (счётчики + лог + карточки оценщика).
                with gr.Column(scale=1):
                    gr.Markdown("**Телеметрия**")
                    with gr.Row(elem_classes="mad-counters"):
                        versions_counter = gr.Markdown(f"**Версия** —/{M_VERSIONS}")
                        searches_counter = gr.Markdown(f"**Поисков** 0/{DEFAULT_SEARCH_BUDGET}")
                        score_counter = gr.Markdown("**Score** —/7")
                    timer_md = gr.Markdown("")
                    log_box = gr.Textbox(
                        label="Лог событий",
                        lines=12,
                        max_lines=12,
                        interactive=False,
                        autoscroll=True,           # лента прилипает к низу (чек-лист 5b)
                        elem_classes="mad-log",
                    )
                    gr.Markdown("**Оценки**")
                    eval_md = gr.Markdown("_Оценок пока нет._")

                # Правая колонка — черновик/отчёт + плашки терминала.
                with gr.Column(scale=2):
                    # Три плашки терминала (D-14.2) — все скрыты, показывается одна.
                    # ok=зелёная (порог взят), warn=жёлтая (порог не взят: лимит/сбой),
                    # fail=красная (отчёта нет).
                    terminal_ok = gr.Markdown(visible=False, elem_classes=["mad-term", "ok"])
                    terminal_warn = gr.Markdown(visible=False, elem_classes=["mad-term", "warn"])
                    terminal_failed = gr.Markdown(visible=False, elem_classes=["mad-term", "fail"])
                    draft_badge = gr.Markdown(visible=False, elem_classes="mad-badge")
                    report_body = gr.Markdown("_Отчёт появится по завершении прогона._")

            # «Скачать» + «Новое исследование» — в один ряд, по центру. «Скачать»
            # видима, когда есть тело отчёта (final любой окраски: зелёная/жёлтая),
            # скрыта на failed (отчёта нет — D-13.2). «Новое» — всегда.
            with gr.Row(elem_classes="mad-cta-row"):
                download_btn = gr.DownloadButton(
                    "Скачать отчёт (.md)", visible=False, elem_classes="mad-cta"
                )
                new_research_btn = gr.Button("Новое исследование", elem_classes="mad-cta")

        # Таймер реального времени — тикает раз в секунду, пишет ТОЛЬКО timer_md
        # (разведён с потоком петли против гонки). Стартует в _go_to_run, гаснет на
        # терминале (_tick при фазе done) или на сбросе.
        run_timer = gr.Timer(1.0, active=False)

        # Живые компоненты потока (порядок = кортеж frame): БЕЗ timer_md (его ведёт
        # таймер), + States фазы/финального времени.
        live_outputs = [
            versions_counter, searches_counter, score_counter,
            log_box, eval_md, draft_badge, report_body,
            terminal_ok, terminal_warn, terminal_failed, download_btn,
            run_phase, run_end,
        ]

        # ── Переключение экранов + запуск потока/таймера ─────────────────────
        start_btn.click(
            _go_to_clarify,
            inputs=topic_input,
            outputs=[screen_topic, screen_clarify, screen_state, topic_recap_2],
        )
        # Сначала переход на экран 3 + старт таймера, затем — подписка на поток (5b).
        research_btn.click(
            _go_to_run,
            inputs=[topic_input, q1, q2, q3, email_check],
            outputs=[screen_clarify, screen_run, screen_state, run_summary,
                     run_start, run_phase, run_timer],
        ).then(
            _run_stream,
            inputs=[topic_input, q1, q2, q3, email_check],
            outputs=live_outputs,
            show_progress="minimal",   # иначе встроенный спиннер накроет живой лог
        )
        # Тик таймера пишет ТОЛЬКО timer_md (+ выключает себя на терминале).
        run_timer.tick(
            _tick,
            inputs=[run_start, run_end, run_phase],
            outputs=[timer_md, run_timer],
        )
        new_research_btn.click(
            _reset,
            inputs=None,
            outputs=[screen_topic, screen_clarify, screen_run, screen_state,
                     run_phase, run_timer,
                     topic_input, q1, q2, q3, email_check],   # очистка полей ввода
        )
        # Переключатель темы. КЛИК (.input — только пользовательский, не программный):
        # проставить `?__theme=<выбор>` и перезагрузить.
        theme_radio.input(None, inputs=theme_radio, outputs=None, js=_SWITCH_THEME_JS)
        # ЗАГРУЗКА: синхронизировать радио с фактической темой из URL (фикс рассинхрона
        # «радио light, экран dark»). Через .input выше программная установка НЕ вызывает
        # повторную перезагрузку (цикла нет).
        ui.load(None, inputs=None, outputs=theme_radio, js=_SYNC_THEME_JS)

    return ui


if __name__ == "__main__":
    # .queue() обязателен для стриминга генераторов (на Spaces по умолчанию;
    # локально включаем явно). inbrowser — локальное удобство; на Spaces не влияет.
    build_ui().queue().launch(inbrowser=True)

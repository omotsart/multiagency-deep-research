"""Юнит-тесты Pydantic-схемы отчёта писателя (под-gate 2c).

Проверяем контракт схемы ReportData: обязательность short_summary /
markdown_report / follow_up_questions, что follow_up_questions — список. Не
проверяем качество/«умность» отчёта (RULES §4) и не вызываем LLM/OpenAI.
"""

import pytest
from pydantic import ValidationError

from writer_agent import ReportData


def test_valid_report_builds():
    report = ReportData(
        short_summary="Кратко о находках.",
        markdown_report="# Отчёт\n\nТело отчёта.",
        follow_up_questions=["Что дальше?", "Какие пробелы?"],
    )
    assert report.short_summary
    assert report.markdown_report.startswith("#")
    assert isinstance(report.follow_up_questions, list)
    assert len(report.follow_up_questions) == 2


def test_empty_follow_up_list_is_valid_schema():
    # Схема допускает пустой список — минимум/качество не наша забота (RULES §4).
    report = ReportData(
        short_summary="s", markdown_report="r", follow_up_questions=[]
    )
    assert report.follow_up_questions == []


def test_requires_short_summary():
    with pytest.raises(ValidationError):
        ReportData(markdown_report="r", follow_up_questions=[])


def test_requires_markdown_report():
    with pytest.raises(ValidationError):
        ReportData(short_summary="s", follow_up_questions=[])


def test_requires_follow_up_questions():
    with pytest.raises(ValidationError):
        ReportData(short_summary="s", markdown_report="r")


def test_follow_up_questions_must_be_list_not_scalar():
    with pytest.raises(ValidationError):
        ReportData(
            short_summary="s", markdown_report="r", follow_up_questions="not a list"
        )

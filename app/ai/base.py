"""Provider-agnostic question shapes + the provider interface.

The interface is deliberately thin — one ``generate`` call. Prompt assembly is
shared (``prompts.py``) and lives outside providers, so every provider receives
the same prompt and differs only in its SDK call. Output is normalized to
``GeneratedQuestion`` so callers never see provider differences.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from ..models import QuestionType


class GeneratedQuestion(BaseModel):
    """One question as returned by a provider (before it's persisted).

    Doubles as the structured-output schema handed to the model, so the shape is
    constrained at the source: exactly 4 options, a 0–3 answer index.
    """

    type: QuestionType = QuestionType.multiple_choice
    stem: str = Field(description="題幹(日文)")
    options: list[str] = Field(min_length=4, max_length=4, description="4 個選項")
    answer_index: int = Field(ge=0, le=3, description="正解索引 0-3")
    explanation: str = Field(description="解說(繁體中文)")


class GeneratedQuiz(BaseModel):
    """Wrapper so the model returns a JSON object with a ``questions`` array."""

    questions: list[GeneratedQuestion]


class QuestionProvider(Protocol):
    """Anything that can turn source text into N5-style questions."""

    def generate(self, source_text: str, n: int) -> list[GeneratedQuestion]: ...

"""Gemini implementation of QuestionProvider (the first/primary provider).

The ``google-genai`` SDK is imported lazily inside ``generate`` so the app (and
the test suite) start fine without it installed — only real generation needs it.
"""

from __future__ import annotations

from ..config import get_settings
from .base import GeneratedQuestion, GeneratedQuiz
from .errors import AIError
from .prompts import build_prompt


class GeminiProvider:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model or settings.ai_model

    def generate(self, source_text: str, n: int) -> list[GeneratedQuestion]:
        if not self.api_key:
            raise AIError("尚未設定 GEMINI_API_KEY。請在 .env 加入金鑰後再出題。")
        try:
            from google import genai
        except ImportError as exc:  # SDK not installed
            raise AIError("尚未安裝 google-genai 套件(uv add google-genai)。") from exc

        client = genai.Client(api_key=self.api_key)
        prompt = build_prompt(source_text, n)
        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": GeneratedQuiz,
                },
            )
        except Exception as exc:  # network / API / quota
            raise AIError(f"AI 產生題目失敗:{exc}") from exc

        quiz = self._parse(resp)
        if not quiz.questions:
            raise AIError("AI 沒有回傳題目,請重試。")
        return quiz.questions[:n]

    @staticmethod
    def _parse(resp) -> GeneratedQuiz:
        """Prefer the SDK's parsed pydantic; fall back to raw-JSON validation."""
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, GeneratedQuiz):
            return parsed
        text = getattr(resp, "text", None)
        if not text:
            raise AIError("AI 回傳格式無法解析。")
        try:
            return GeneratedQuiz.model_validate_json(text)
        except Exception as exc:
            raise AIError(f"AI 回傳格式無法解析:{exc}") from exc

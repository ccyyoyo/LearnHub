"""LLM calls for Phase 3 — transcript → summary / study notes.

Provider seam: only Claude (Anthropic SDK) is wired today. Routes go through
``AIClient`` and ``settings.llm_provider`` selects the backend, so a second
provider (e.g. OpenRouter) slots in here without touching routers or templates.
Output is always Traditional Chinese regardless of the transcript's language.
"""

from __future__ import annotations

from .config import get_settings
from .models import AIKind

_SYSTEM = (
    "你是一位協助學習的助教。使用者會提供一段 YouTube 影片的字幕逐字稿,"
    "請一律用繁體中文輸出,內容要精準、忠於原片,不要捏造字幕裡沒有的資訊。"
)

_PROMPTS: dict[AIKind, str] = {
    AIKind.summary: (
        "請為以下影片字幕寫一段重點摘要:先用 2-3 句話總結整支影片在講什麼,"
        "再用條列列出 3-6 個關鍵重點。\n\n字幕逐字稿:\n{text}"
    ),
    AIKind.notes: (
        "請依以下影片字幕整理成方便複習的重點筆記:用階層式條列(主題 → 要點),"
        "保留重要的名詞、定義與步驟,必要時補上簡短說明。\n\n字幕逐字稿:\n{text}"
    ),
}

# Generation is non-streaming and well under the SDK's HTTP-timeout guard; notes
# for a long video still fit comfortably under this cap.
_MAX_TOKENS = 4000


class AIError(Exception):
    """Raised for any user-facing LLM failure (no key, API/network error, …)."""


class AIClient:
    """Thin wrapper over the configured LLM provider.

    Stateless, so routes can ``Depends(AIClient)`` and tests can swap it out via
    ``app.dependency_overrides`` — the same pattern as ``YouTubeClient``.
    """

    async def generate(self, kind: AIKind, transcript_text: str) -> str:
        settings = get_settings()
        if settings.llm_provider != "claude":
            raise AIError(f"尚未支援的 LLM 供應商:{settings.llm_provider}。")
        if not settings.anthropic_api_key:
            raise AIError("尚未設定 ANTHROPIC_API_KEY。請在 .env 中加入金鑰後再試。")

        prompt = _PROMPTS[kind].format(text=transcript_text)
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            message = await client.messages.create(
                model=settings.llm_model,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM,
                # Summaries/notes are content generation, not reasoning — skip
                # thinking tokens to keep latency and cost down.
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # network / API / SDK errors → friendly message
            raise AIError(f"呼叫 LLM 失敗:{exc}") from exc

        text = "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()
        if not text:
            raise AIError("LLM 沒有回傳內容,請稍後再試。")
        return text

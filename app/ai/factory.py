"""Pick the active provider from settings (``AI_PROVIDER``).

Providers are imported lazily so an unused provider's SDK never needs to be
installed. Add a new provider here once it implements ``QuestionProvider``.
"""

from __future__ import annotations

from ..config import get_settings
from .base import QuestionProvider
from .errors import AIError


def get_provider() -> QuestionProvider:
    name = get_settings().ai_provider.lower()
    if name == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider()
    raise AIError(f"未知的 AI_PROVIDER:{name}")

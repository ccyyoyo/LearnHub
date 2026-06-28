"""Single user-facing error type for the AI layer.

Every provider wraps its SDK/network failures (missing key, rate limit, bad
output) in ``AIError`` so routers only ever catch one thing — mirroring
``YouTubeError`` in ``app/youtube.py``.
"""


class AIError(Exception):
    """Raised for any user-facing quiz-generation failure."""

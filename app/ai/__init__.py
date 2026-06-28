"""AI quiz generation (PRD Phase 3).

A thin, swappable provider layer: callers depend only on the
``QuestionProvider`` interface in ``base``; concrete providers (``gemini`` …)
slot in behind it and are chosen by env via ``factory.get_provider``.
"""

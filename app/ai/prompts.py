"""Shared prompt assembly for quiz generation.

Kept out of the providers so every provider sends an identical prompt — the
only cross-provider difference is the SDK call itself.
"""

from __future__ import annotations

# Cap how much transcript we feed the model: keeps cost bounded and stays well
# inside context limits even for long videos. Transcripts are word-dense so this
# is plenty for question generation.
_MAX_SOURCE_CHARS = 12000


def build_prompt(source_text: str, n: int) -> str:
    """Build the N5 multiple-choice generation prompt from ``source_text``."""
    source = (source_text or "").strip()[:_MAX_SOURCE_CHARS]
    return (
        "你是 JLPT N5 日語出題老師。根據以下教材內容,出"
        f" {n} 題 JLPT N5 程度的單選題。\n\n"
        "要求:\n"
        "- 每題 4 個選項,只有 1 個正確。\n"
        "- 難度貼近 JLPT N5(基礎漢字、語彙、文法)。\n"
        "- 誘答選項(錯誤選項)要合理,不可明顯亂湊。\n"
        "- 題幹用日文。\n"
        "- 解說(explanation)用繁體中文,說明為何正確。\n"
        "- answer_index 是正解在 options 陣列中的索引(0 到 3)。\n"
        "- 只根據教材內容出題,不要捏造教材沒有的資訊。\n\n"
        f"教材內容:\n{source}\n"
    )

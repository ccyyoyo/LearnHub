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
        "你是 JLPT N5 日語出題老師。以下教材只是『出題範圍的參考』,"
        "用來決定要考哪些 N5 文法重點與主題;"
        f"請依此出 {n} 題 JLPT N5 程度的單選題。\n\n"
        "出題方向(考語言能力,不是考記憶教材):\n"
        "- 考的是日文能力:語彙意思、文法(助詞、動詞/形容詞變化、句型)、"
        "漢字読み、正確表記。\n"
        "- 題目用字不限教材出現過的單字。只要是 N5 程度,可自由使用任何 N5 單字"
        "與例句來造題。\n"
        "- 題目要讓『懂 N5 日文的人』就能作答,不需要讀過這份教材。\n\n"
        "嚴禁(這些題目沒有學習意義):\n"
        "- 不要考教材的劇情或內容細節(例:某個人物明天做什麼、誰說了什麼、"
        "對話裡發生什麼)。\n"
        "- 不要考只有讀過教材才知道答案的事實。\n\n"
        "格式要求:\n"
        "- 每題 4 個選項,只有 1 個正確。\n"
        "- 誘答選項(錯誤選項)要是合理的 N5 干擾項(例:相近詞、易混的活用形),"
        "不可明顯亂湊。\n"
        "- 題幹用日文。\n"
        "- 解說(explanation)用繁體中文,說明文法/語彙重點與為何正確。\n"
        "- answer_index 是正解在 options 陣列中的索引(0 到 3)。\n\n"
        f"出題範圍參考:\n{source}\n"
    )

# AI 出題功能 — 設計文件

日期：2026-06-28
分支：`feat/ai-quiz-generation`
階段：PRD Phase 3（AI 輔助）

## 1. 目標

看完影片後，AI 產生 JLPT N5 風格單選題，讓學習者作答、記錄結果、依弱點複習。承接 app 既有「追蹤學習」核心。

## 2. 範圍

### 做
- Provider 抽象層（可換模型），先實作 Gemini 一家。
- 從影片字幕（fallback 筆記 / 標題）產生 N5 單選題。
- 題目與作答紀錄存入既有 `learnhub.db`（新增兩張表）。
- 單片觸發出題；同頁 HTMX 展開作答。
- 主頁題庫統計 + 弱點「練習推薦」。

### 不做（未來）
- 其他題型（是非 / 簡答 / 填空）。
- 主題層綜合出題。
- 完整錯題複習排程。
- 多 provider 並用（介面留好，先只 Gemini）。

## 3. Provider 抽象

```
app/ai/
  base.py        # Question model + QuestionProvider Protocol
  prompts.py     # 共用 prompt 組裝（N5 風格指示）
  gemini.py      # GeminiProvider（主力，先做）
  factory.py     # 依 env 選 provider
  errors.py      # AIError（統一例外）
```

- 介面薄：`generate(source_text: str, n: int) -> list[Question]`。
- 共用 prompt 放 `prompts.py`，三家未來共用；各 provider 只差 SDK 呼叫。
- 各 provider 把 SDK 例外（key 缺、rate limit、壞輸出）包成 `AIError`。
- 延遲匯入 SDK（檔案頂端才 import 自家套件），未裝的不影響啟動。

### 設定（`.env` / config.py）
```
AI_PROVIDER=gemini
AI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
```
沿用 `pydantic-settings`；未設 key 時出題端點回友善錯誤（沿用 import_error.html 模式）。

## 4. 字幕來源（fallback 階梯）

1. 影片字幕 — `youtube-transcript-api`（日文優先）。
2. 無字幕 → 影片筆記 `Item.note_md`（若有）。
3. 無筆記 → 影片標題（弱，AI 用標題猜）。

永不報錯到最後一階；標題一定存在。

> 注意：日文自動字幕雜訊高（無標點、辨識錯）。prompt 需容錯；測試期人工抽查題目品質。

## 5. 題型 / Schema

N5 單選：題幹（日文）+ 4 選項 + 1 正解 + 解說（zh-TW）。

```python
class QuestionType(str, Enum):
    multiple_choice = "multiple_choice"   # 目前唯一；擴充用

# Pydantic（provider 輸出 + structured output schema）
class Question(BaseModel):
    type: QuestionType = QuestionType.multiple_choice
    stem: str
    options: list[str]      # 固定 4 個
    answer_index: int       # 0–3
    explanation: str        # zh-TW
```

## 6. 資料層（同一 learnhub.db，新增兩表）

```python
class Question(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    type: QuestionType = Field(default=QuestionType.multiple_choice)
    stem: str
    options_json: str        # 4 選項以 JSON 儲存
    answer_index: int
    explanation: str
    created_at: datetime = Field(default_factory=utcnow)

class Attempt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    chosen_index: int
    is_correct: bool
    created_at: datetime = Field(default_factory=utcnow)
```

- migration 只新增表，不動既有欄位（安全）。
- 先在測試 DB 驗證 migration，再讓 uvicorn reload 跑到實機 DB。

## 7. 出題流程

單片觸發。兩個入口：

### 入口 A — 影片列「出題」鈕
- 使用者選題數（1–10）。
- 同頁 HTMX 展開題目區。

### 入口 B — 主頁「練習推薦」
- 主題依弱點排序：沒練過優先 → 再錯誤率高→低。
- 點主題 → 自動選該主題「最該練的一片」：沒練過優先 → 再錯誤率高 → 出題。

### 選片定義
- 「沒練過」= 該片底下題目無任何 Attempt（通常也尚無題目）。
- 「錯誤率」= 該片所有題目的 答錯數 / 總作答數。

## 8. 出題組裝規則

| 片狀態 | 題庫 | 組裝 |
|---|---|---|
| 沒練過 | 通常無題 | 全生新題 N |
| 錯誤率高 | 有題、有錯題 | 錯題優先 + 新題補滿至 N |

- 錯題 ≤ N：全收；錯題 > N：取最近錯的 N。
- 已有題重用（省 token / 省錢）；不足才呼叫 AI 生新題。
- 總數 N = 使用者選（1–10）。

## 9. 作答互動（HTMX 同頁）

題幹 + 4 選項（radio / 按鈕）→ 選擇 → POST → 存 Attempt → 回片段顯示對錯 + 解說（zh-TW）→ 下一題。沿用既有 partial 模式（item_row.html 等）。

## 10. 主頁題庫區

```
題庫：120 題 · 作答 340 次 · 正確率 78% · 錯題 26 〉複習
練習推薦：
  Rust       ⚠️ 未練習   〉
  日語 N5    錯誤率 45%  〉
```

```python
@dataclass(frozen=True)
class QuizStats:
    total_questions: int
    total_attempts: int
    correct_rate: int      # %
    wrong_count: int       # 待複習錯題
```

即時從 DB 算，不存冗餘計數器（沿用 services.py 的 Progress / StudyPlan 風格）。
錯題本：先放入口 + 列「最近答錯」；完整複習流程之後做。

## 11. 錯誤處理

- key 缺、rate limit、壞輸出、字幕全失敗 → `AIError` → UI 友善提示。
- 沿用 config.py env 注入與 import_error.html 提示模式。

## 12. 對既有架構的相容

- 資料：SQLModel + 同一 SQLite。
- 服務：純函式聚合放 services（選片、組裝、stats），可單元測試。
- UI：Jinja2 + HTMX partial。
- 設定：pydantic-settings env 注入。

符合 models.py 註記「吸收 Phase 3（AI）不需重構」。

## 13. 實作順序（建議）

1. 資料層：models（Question / Attempt / QuestionType）+ migration。
2. Provider 抽象：base / errors / prompts / gemini / factory。
3. 字幕擷取：youtube transcript + fallback 階梯。
4. 服務層純函式：選片、組裝規則、QuizStats（含單元測試）。
5. Router + HTMX 端點：出題、作答、主頁統計。
6. 模板：題目區 partial、主頁題庫區、練習推薦。
7. 設定與錯誤提示。
8. 端對端手動驗證（先測試 DB）。

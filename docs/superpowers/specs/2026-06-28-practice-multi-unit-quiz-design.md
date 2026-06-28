# 練習推薦頁:多單元勾選出題

**Date:** 2026-06-28
**Status:** Approved (design)

## 問題

現在 `/practice/{subject_id}` 自動只推一支影片(`select_practice_item`),使用者無從選擇。
希望改成:使用者自行勾選要練的單元(影片),每單元標註練習次數與錯誤率,挑完後 AI
依勾選單元出題。

## 決策摘要

- **比例控制:** AI 自動分配(程式端計算,非 LLM)。使用者只勾單元、選總題數。
- **總題數:** 使用者選,範圍 1–10(沿用 `_clamp_n`)。
- **分配權重:** 沒練過優先,再錯誤率高優先(對齊 `select_practice_item`)。
- **清單版面:** 扁平一列,主業內全部影片,依需求排序。
- **保底:** 每勾選單元至少 1 題(可行時)。

## 架構

選定路線 A:新增後端端點集中分配與出題。前端只送勾選的 `item_ids` 與總題數。

### 1. 練習頁 `practice.html`

不再只推一支,改為單元勾選清單:

- 扁平清單,列出主業內全部影片(跨 resource)。
- 每列:checkbox(`name="item_ids"` value=item.id)、標題、`練習 N 次`、
  `錯誤率 X%`;沒練過顯示「未練習」。
- 排序:沒練過優先 → 錯誤率高優先(同 `select_practice_item` 的 key)。
- 全選 / 全不選控制(純前端小 JS,或 checkbox toggle)。
- 總題數選擇(1–10,預設 5,沿用現有 select 樣式)。
- 「開始出題」按鈕 → HTMX `POST /practice/{subject_id}/quiz` → 回填 `#practice-quiz`。
- 沒有任何可練影片時維持現有空狀態文案。

模板資料:`practice()` 路由改傳整份 item 清單 + 每項統計(練習次數、錯誤率、是否
練過),不再只傳單一 `item`。統計用既有 `item_attempt_count` / `item_error_rate`。

### 2. 分配演算法(`services.py`,純函式)

```
allocate_questions(items: list[Item], n: int) -> dict[int, int]
```

回傳 `{item_id: question_count}`,總和 == n。

- **權重:** 沒練過(`item_attempt_count == 0`)權重 = 1.0(最高優先);練過權重 =
  `item_error_rate`(0..1)。
- **全為 0**(都練過且全對)→ 平均分配。
- **比例分配:** 依權重比例分配 n,用最大餘數法處理餘數。
- **保底:**
  - `n >= len(items)`:每單元先各保底 1 題,剩餘 `n - len(items)` 依權重分配。
  - `n < len(items)`:無法每個都給 1;權重最高的 n 個各 1 題,其餘 0。
- 純函式 → 單元測試覆蓋:平均、權重偏向弱項、保底、`n < 單元數`、單一單元。

### 3. 新端點 `POST /practice/{subject_id}/quiz`(`routers/quiz.py`)

- 表單:`item_ids: list[int]`、`n: int`。
- 驗證:subject 存在;item_ids 屬於該 subject;至少勾 1 個(否則回 `import_error`
  partial 提示「請至少勾選一個單元」)。
- `n = _clamp_n(n)`。
- `plan = allocate_questions(items, n)`。
- 逐單元(count > 0):`reuse, to_gen = assemble_quiz_plan(item, count)` → 缺額呼叫
  `provider.generate(source, to_gen)` → 建立 `Question` rows → commit。錯題重用照舊。
- 合併所有單元題目成單一 `questions` 清單 → 渲染既有 `partials/quiz.html`
  (已吃扁平 `questions`,免改)。
- AI 失敗:`AIError` → `_error` partial,同現有 `make_quiz`。

### 4. 既有程式

- `select_practice_item`:保留(可能未來他用);`practice()` 路由不再呼叫它做單推。
- `practice_recommendations`(home 練習推薦清單):不動。
- `make_quiz` / `/items/{id}/quiz`:保留,影片頁單支出題仍用。

## 資料流

```
practice.html (勾選 item_ids + n)
   └─ HTMX POST /practice/{subject_id}/quiz
        ├─ allocate_questions(items, n)  → {item_id: count}
        ├─ per item: assemble_quiz_plan + provider.generate
        └─ render partials/quiz.html (合併題目) → #practice-quiz
```

## 錯誤處理

- 未勾任何單元 → `import_error` partial 提示。
- AI 生成失敗 → `_error` partial(沿用)。
- item_ids 含不屬於該 subject 的 → 忽略或 404(實作時取交集,忽略外來 id)。

## 測試

- `allocate_questions`:平均分配、權重偏弱項、保底 1 題、`n < 單元數`、單一單元、
  全沒練過、全練過全對。
- 端點:勾多單元回合併題目數 == n;未勾回提示;AI 失敗回錯誤 partial;錯題重用。
- 既有 `make_quiz` 測試不受影響。

## 範圍外(YAGNI)

- 使用者手動調比例(本版 AI 自動分配)。
- 跨主業出題。
- 分組顯示(本版扁平)。

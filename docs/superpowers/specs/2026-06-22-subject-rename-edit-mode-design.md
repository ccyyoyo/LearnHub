# 主題改名 + 編輯模式 — 設計

日期:2026-06-22
狀態:已核准設計,待寫實作計畫

## 目標

1. **改主題名稱** — 在主題詳細頁,點標題即可就地改名。
2. **編輯模式** — 主題頁可切換進入編輯模式,提供:
   - 多選影片項目 → 批次改進度(狀態)或批次刪除。
   - 每個資源(播放清單/影片)可整個刪除。

## 非目標(YAGNI)

- 不改資料庫 schema、不加新相依套件。
- 不在首頁主題卡片加改名(改名只在主題頁)。
- 不做改資源標題、不做項目排序、不做項目筆記編輯。
- 不做拖拉、不做前端 JS 狀態(維持伺服器驅動)。

## 實作方式

採伺服器驅動,沿用現有 `?filter=` query param 模式。編輯模式以 `?edit=1`
query param 表示,後端重新渲染含編輯控制項的頁面。純 HTMX + Jinja,無 JS build step。

## 路由變更

`GET /subjects/{id}` 新增 `edit: bool = False` query param,傳入樣板。
`filter` 與 `edit` 兩個 query param 並存,批次操作後都需保留。

## 端點

全部放在 `app/routers/subjects.py`,以 subject 為範圍(正確性 + 安全)。

| 方法 | 路徑 | 行為 |
|---|---|---|
| POST | `/subjects/{id}/rename` | **已存在**。回傳改為 header partial(取代原 redirect),供就地 HTMX 儲存。空白名稱維持舊名。 |
| GET | `/subjects/{id}/rename-form` | 回傳就地改名表單 partial,swap 掉 header。 |
| POST | `/subjects/{id}/items/bulk-status` | 表單 `item_ids[]`、`status`、`filter`、`edit`。把選取項目設為指定狀態,重渲染 resources。 |
| POST | `/subjects/{id}/items/bulk-delete` | 表單 `item_ids[]`、`filter`、`edit`。刪除選取項目,重渲染 resources。 |
| DELETE | `/subjects/{id}/resources/{rid}` | 刪整個資源(items 隨 cascade 刪),重渲染 resources。 |

`item_ids` 一律以「屬於本 subject 的項目」過濾(查詢 join 到 resource.subject_id),
跨主題或不存在的 id 直接忽略。

## 樣板

- `app/templates/subject.html`
  - header 改用新的 `partials/subject_header.html`。
  - 編輯切換連結:`?edit=1` ↔ `?edit=0`,保留現有 `filter`。
  - 當 `edit` 為真:把 resources 包進 `<form id="bulk-form">`,上方放動作列
    (狀態下拉 + 「套用」按鈕 hx-post bulk-status;「刪除」按鈕 hx-post bulk-delete 並加 hx-confirm)。
    動作按鈕用 `hx-include="#bulk-form"` 帶入勾選的 `item_ids`。
- 新增 `partials/subject_header.html` — `<h2>{{ subject.name }}</h2>` + 「改名」觸發鈕(hx-get rename-form)。
- 新增 `partials/rename_form.html` — input(value=現名) + 「儲存」(hx-post rename,target = header)
  + 「取消」(hx-get subject_header 還原)。
- `app/templates/partials/resource.html` — 當 `edit`:顯示「刪除資源」按鈕(hx-delete resource)。
- `app/templates/partials/item_row.html` — 當 `edit`:項目前顯示 checkbox
  `<input type="checkbox" name="item_ids" value="{{ item.id }}">`。
  `edit` 預設 False,故既有 `/items/cycle` 重渲染不受影響。
- `app/templates/partials/resources.html` — 透傳 `edit`、`filter`。

## 資料流(批次操作)

編輯頁勾選項目 → 點「套用」或「刪除」→ HTMX 送出 `#bulk-form`
(`item_ids[]`、`status`、`filter`、`edit`)→ 端點變更資料 → 回傳重渲染的
`partials/resources.html`(保留 edit + filter)→ swap 進 `#resources-container`。
進度條在重渲染時自然重算,不需 OOB 片段。

## 邊界情況

- 空白改名 → 維持舊名(沿用現有行為)。
- `item_ids` 不屬於本 subject → 忽略。
- 沒勾選任何項目 → 不變更,單純重渲染。
- 刪資源 → items 隨 model cascade 一併刪除。
- 批次刪除後若資源變空 → 資源保留(除非另外刪資源)。

## 狀態下拉

三個選項:未開始 / 進行中 / 已完成,對應 `ItemStatus`,沿用 `STATUS_LABELS`。

## 影響範圍

- `app/routers/subjects.py`(rename 回傳改動、edit param、3 個新端點)
- `app/templates/subject.html`
- 新增 `app/templates/partials/subject_header.html`
- 新增 `app/templates/partials/rename_form.html`
- `app/templates/partials/resources.html`
- `app/templates/partials/resource.html`
- `app/templates/partials/item_row.html`
- `app/static/styles.css`(編輯模式樣式:checkbox 版面、動作列、危險按鈕)
- `tests/test_app.py`(新測試)

無 schema 變更、無新相依。

## 測試

- 改名:回傳 header 含新名;空白名稱維持舊名。
- bulk-status:只把選取項目設為指定狀態,未選取的不動。
- bulk-delete:移除選取項目,資源完成度(x/y、%)重算正確。
- 跨主題 `item_ids`:被忽略,不影響別的 subject。
- 刪資源:資源與其 items 一併移除。
- `edit=1`:渲染出 checkbox + 動作列;預設(無 edit)不渲染這些。

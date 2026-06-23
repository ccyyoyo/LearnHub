# LearnHub — 個人學習中樞

把跨主題的學習資源集中到一個入口、記錄進度。**Phase 1（MVP）** 完成核心閉環:

> 貼上 YouTube 播放清單/影片網址 → 系統自動抓取並拆成可追蹤項目 → 逐項打勾、看完成度。

全程在 UI 內完成,不需手動跑腳本或外部自動化服務(整合式匯入)。

## 功能(Phase 1)

- **主題管理** — 新增 / 列出 / 改名 / 刪除主題,並顯示各自的資源數(FR-1)。
- **整合式匯入** — 貼上播放清單或單支影片網址,自動解析、抓 metadata、拆成項目;
  支援分頁、重複匯入自動去重(以 `video_id`)(FR-2)。
- **進度追蹤** — 每個項目三態(未開始 / 進行中 / 已完成)一鍵切換,資源層級顯示
  完成度(x/y、百分比)(FR-3)。
- **瀏覽 / 導覽** — 點項目開新分頁到 YouTube;可依「全部 / 進行中 / 未完成」篩選(FR-4)。

- **AI 輔助(Phase 3)** — 每個項目可一鍵抓字幕並用 LLM 產生**影片摘要**或**重點筆記**;
  字幕與 AI 產出都以 `video_id` 快取,不重抓、不重算。

資料模型已預留 Phase 2(`Item.note_md` 筆記)的空間,擴充時不需重構。

## 技術選型

FastAPI · SQLite + SQLModel · Jinja2 + HTMX(無 JS build step)· httpx · uv · pydantic-settings ·
Anthropic SDK(Claude)· youtube-transcript-api。

## 開始使用

需要 [uv](https://docs.astral.sh/uv/)。

```bash
# 1. 安裝依賴
uv sync

# 2. 設定金鑰
cp .env.example .env
#   YOUTUBE_API_KEY=...   匯入用(Google Cloud Console → 啟用 "YouTube Data API v3")
#   ANTHROPIC_API_KEY=... AI 摘要/筆記用(選填,console.anthropic.com)

# 3. 啟動
uv run uvicorn app.main:app --reload
```

開啟 http://127.0.0.1:8000 ,新增一個主題,貼上 YouTube 清單網址即可匯入。

> 未設定金鑰也能啟動,只是匯入時會提示去 `.env` 補上金鑰。

## 測試

```bash
uv run pytest
```

## 專案結構

```
app/
  main.py          # FastAPI app + 路由註冊、lifespan 建表
  config.py        # pydantic-settings(環境變數注入)
  db.py            # engine / session / init_db
  models.py        # SQLModel domain models(Subject / Resource / Item / Transcript / AIArtifact)
  youtube.py       # YouTube API client + URL 解析(變動只改這裡)
  transcript.py    # 抓字幕(youtube-transcript-api,隔離在此)
  ai.py            # LLM 呼叫(Claude;供應商可切換的接縫)
  services.py      # 進度聚合、狀態切換、AI 產出聚合
  templating.py    # 共用 Jinja2 環境
  routers/         # subjects / imports / items / ai 的 endpoints
  templates/       # Jinja2 .html(含 HTMX 片段)
  static/          # styles.css / htmx.min.js
tests/             # URL 解析 + 匯入/進度的端對端測試
learnhub.db        # SQLite(gitignored)
```

## 路線圖

- **Phase 2 — 筆記**:每個項目可寫 / 渲染 Markdown(`note_md` 欄位已就緒)。
- **Phase 3 — AI 輔助**:已完成「抓字幕 → LLM 做**摘要 / 重點筆記**」(走 Claude,`llm_provider`
  留有切換到 OpenRouter 的接縫)。後續可加**練習題**、把筆記匯入 `note_md`、整個清單批次處理。

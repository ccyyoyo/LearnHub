# 練習推薦頁多單元勾選出題 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 練習頁改為使用者勾選多個單元(影片)出題,每單元標註練習次數與錯誤率,AI 依弱項權重自動把總題數分配到各勾選單元。

**Architecture:** 後端新增純函式 `allocate_questions`(依權重把 n 題分到各單元,保底每單元 1 題)與資料整理函式 `practice_units`(供模板列出單元+統計)。新增端點 `POST /practice/{subject_id}/quiz` 接收勾選的 `item_ids` 與總題數,逐單元沿用既有 `assemble_quiz_plan` + provider 生成,合併題目渲染既有 `partials/quiz.html`。`practice()` 路由與 `practice.html` 改為勾選清單 UI。

**Tech Stack:** FastAPI、SQLModel、Jinja2、HTMX、pytest。

---

## File Structure

- `app/services.py` — 新增 `PracticeUnit` dataclass、`practice_units()`、`practice_weight()`、`allocate_questions()`。純函式,單元測試覆蓋。
- `app/routers/quiz.py` — 新增 `POST /practice/{subject_id}/quiz` 端點;改寫 `practice()` 路由傳單元清單。
- `app/templates/practice.html` — 改為勾選清單 + 總題數 + 開始出題表單。
- `tests/test_quiz.py` — 新增分配/端點測試;更新既有 `test_practice_route_picks_item_and_offers_quiz`。

既有 `partials/quiz.html`(吃扁平 `questions`)、`assemble_quiz_plan`、`item_attempt_count`、`item_error_rate`、`_clamp_n`、`resolve_source_text` 全部重用,不改。

---

## Task 1: `allocate_questions` 純函式

依權重把 `n` 題分配到各單元,保底每單元至少 1 題(可行時)。與 ORM 解耦:吃 `(item_id, weight)` 清單,權重由呼叫端算。

**Files:**
- Modify: `app/services.py`(Quiz 區段末尾,`practice_recommendations` 之後)
- Test: `tests/test_quiz.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_quiz.py` 末尾:

```python
# --- allocate_questions -----------------------------------------------------

from app.services import allocate_questions


def test_allocate_even_when_weights_equal():
    # 3 單元權重相同 → 6 題平均每單元 2 題。
    plan = allocate_questions([(1, 1.0), (2, 1.0), (3, 1.0)], 6)
    assert plan == {1: 2, 2: 2, 3: 2}


def test_allocate_weights_toward_high_error():
    # 高錯誤率單元拿較多題;保底每單元 1 題;總和守恆。
    plan = allocate_questions([(1, 0.8), (2, 0.2)], 10)
    assert sum(plan.values()) == 10
    assert plan[1] > plan[2]
    assert plan[2] >= 1


def test_allocate_min_one_each_when_n_equals_units():
    plan = allocate_questions([(1, 0.9), (2, 0.0), (3, 0.5)], 3)
    assert plan == {1: 1, 2: 1, 3: 1}


def test_allocate_fewer_questions_than_units_picks_top_weighted():
    # n < 單元數 → 無法每個都給;權重最高的 n 個各 1 題,其餘 0。
    plan = allocate_questions([(1, 0.1), (2, 0.9), (3, 0.5), (4, 0.0)], 2)
    assert sum(plan.values()) == 2
    assert plan == {2: 1, 3: 1, 1: 0, 4: 0}


def test_allocate_single_unit_gets_all():
    assert allocate_questions([(7, 0.0)], 5) == {7: 5}


def test_allocate_all_zero_weight_falls_back_to_even():
    plan = allocate_questions([(1, 0.0), (2, 0.0)], 4)
    assert plan == {1: 2, 2: 2}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_quiz.py -k allocate -v`
Expected: FAIL — `ImportError: cannot import name 'allocate_questions'`

- [ ] **Step 3: 實作 `allocate_questions`**

加到 `app/services.py` 末尾(`practice_recommendations` 之後):

```python
def _largest_remainder(weights: list[float], total: int) -> list[int]:
    """Apportion ``total`` whole units across ``weights`` (Hamilton method).

    Floor each ideal share, then hand out the leftover units to the largest
    fractional remainders. Ties broken by list order (earlier wins).
    """
    weight_sum = sum(weights)
    if total <= 0 or weight_sum <= 0:
        return [0] * len(weights)
    ideals = [total * w / weight_sum for w in weights]
    floors = [int(x) for x in ideals]
    leftover = total - sum(floors)
    # Indices ranked by fractional remainder desc, then original order.
    order = sorted(
        range(len(weights)),
        key=lambda i: (ideals[i] - floors[i]),
        reverse=True,
    )
    for i in order[:leftover]:
        floors[i] += 1
    return floors


def allocate_questions(weights: list[tuple[int, float]], n: int) -> dict[int, int]:
    """Split ``n`` questions across units, weighted toward weaker units.

    ``weights`` is ``(item_id, weight)`` in display/need order; higher weight =
    more questions. Guarantees every unit at least 1 question when ``n`` allows;
    when ``n`` < number of units, only the top-``n`` weighted units get a
    question (one each), the rest get 0. Returns ``{item_id: count}`` summing to
    ``n``.
    """
    if not weights or n <= 0:
        return {item_id: 0 for item_id, _ in weights}

    units = len(weights)
    if n < units:
        # Can't give everyone one — rank by weight (then order) and pick top n.
        ranked = sorted(range(units), key=lambda i: (-weights[i][1], i))
        chosen = set(ranked[:n])
        return {weights[i][0]: (1 if i in chosen else 0) for i in range(units)}

    # Everyone gets a guaranteed 1; apportion the rest by weight (even split
    # when all weights are zero).
    remainder = n - units
    raw = [w for _, w in weights]
    apportion_weights = raw if sum(raw) > 0 else [1.0] * units
    extra = _largest_remainder(apportion_weights, remainder)
    return {weights[i][0]: 1 + extra[i] for i in range(units)}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_quiz.py -k allocate -v`
Expected: PASS(6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services.py tests/test_quiz.py
git commit -m "feat: allocate_questions — weighted multi-unit question split"
```

---

## Task 2: `practice_weight` + `practice_units`(模板資料)

供 `practice()` 路由把主業內全部影片整理成勾選清單列(統計 + 排序),並提供每單元權重給端點。

**Files:**
- Modify: `app/services.py`
- Test: `tests/test_quiz.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_quiz.py` 末尾。用既有 fixture 透過 HTTP 匯入後直接讀 ORM 較重,改用輕量單元測試:以 `engine` 建少量資料。先加 import 與測試:

```python
# --- practice_units / practice_weight ---------------------------------------

from app.models import Item, Question as QModel, Resource, Subject
from app.services import practice_units, practice_weight


def _make_subject_with_items(session):
    sub = Subject(name="日語 N5")
    session.add(sub)
    session.commit()
    session.refresh(sub)
    res = Resource(subject_id=sub.id, type="playlist", source_url="u", title="t")
    session.add(res)
    session.commit()
    session.refresh(res)
    items = []
    for pos in range(3):
        it = Item(resource_id=res.id, video_id=f"v{pos}", title=f"T{pos}", position=pos)
        session.add(it)
        items.append(it)
    session.commit()
    for it in items:
        session.refresh(it)
    return sub, items


def _answer(session, item, *, correct: bool):
    q = QModel(
        item_id=item.id,
        stem="?",
        options_json='["a","b","c","d"]',
        answer_index=0,
        explanation="e",
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    session.add(Attempt(question_id=q.id, chosen_index=0 if correct else 1,
                        is_correct=correct))
    session.commit()


def test_practice_weight_never_practiced_is_max(engine):
    with Session(engine) as s:
        _, items = _make_subject_with_items(s)
        assert practice_weight(items[0]) == 1.0  # no attempts → top priority


def test_practice_weight_practiced_uses_error_rate(engine):
    with Session(engine) as s:
        _, items = _make_subject_with_items(s)
        _answer(s, items[0], correct=False)  # 1 wrong of 1 → rate 1.0
        s.refresh(items[0])
        assert practice_weight(items[0]) == 1.0
        _answer(s, items[0], correct=True)  # now 1 wrong of 2 → 0.5
        s.refresh(items[0])
        assert practice_weight(items[0]) == 0.5


def test_practice_units_sorts_never_practiced_first_then_error(engine):
    with Session(engine) as s:
        sub, items = _make_subject_with_items(s)
        _answer(s, items[0], correct=True)   # practiced, 0% error
        _answer(s, items[1], correct=False)  # practiced, 100% error
        # items[2] never practiced
        s.refresh(sub)
        units = practice_units(sub)
        ids = [u.item.id for u in units]
        assert ids[0] == items[2].id            # never-practiced first
        assert ids[1] == items[1].id            # then highest error
        assert ids[2] == items[0].id
        assert units[0].practiced is False
        assert units[1].error_rate == 100
        assert units[0].attempts == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_quiz.py -k "practice_weight or practice_units" -v`
Expected: FAIL — `ImportError: cannot import name 'practice_units'`

- [ ] **Step 3: 實作**

加到 `app/services.py`(`allocate_questions` 之後)。`Item` 已在檔案頂端 import。

```python
def practice_weight(item: Item) -> float:
    """Need score for question allocation: never-practiced ranks highest (1.0),
    otherwise the item's error rate (0..1)."""
    if item_attempt_count(item) == 0:
        return 1.0
    return item_error_rate(item)


@dataclass(frozen=True)
class PracticeUnit:
    """One selectable row on the practice page (a single video + its stats)."""

    item: Item
    attempts: int
    error_rate: int  # %, 0 when never practiced
    practiced: bool


def practice_units(subject: Subject) -> list[PracticeUnit]:
    """Every video under a subject as selectable rows, ordered by need.

    Never-practiced first (coverage), then highest error rate — same ranking as
    ``select_practice_item`` / ``practice_recommendations``.
    """
    rows: list[PracticeUnit] = []
    for item in _subject_items(subject):
        attempts = item_attempt_count(item)
        rows.append(
            PracticeUnit(
                item=item,
                attempts=attempts,
                error_rate=round(item_error_rate(item) * 100),
                practiced=attempts > 0,
            )
        )
    rows.sort(key=lambda r: (r.practiced, -r.error_rate))
    return rows
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_quiz.py -k "practice_weight or practice_units" -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services.py tests/test_quiz.py
git commit -m "feat: practice_units + practice_weight for multi-unit practice page"
```

---

## Task 3: 練習頁端點 `POST /practice/{subject_id}/quiz`

收勾選 `item_ids` 與總題數,分配後逐單元出題,合併渲染。

**Files:**
- Modify: `app/routers/quiz.py`
- Test: `tests/test_quiz.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_quiz.py`(端點測試區)。沿用既有 `client/engine/provider/fetcher` fixture 與 `_imported_subject`/`_item_ids`/`_quiz_question_ids` 輔助:

```python
# --- multi-unit practice quiz endpoint --------------------------------------


def test_practice_quiz_generates_for_selected_units(client, provider, fetcher):
    sid = _imported_subject(client)
    iids = _item_ids(client, sid)
    r = client.post(
        f"/practice/{sid}/quiz",
        data={"item_ids": iids[:2], "n": 6},
    )
    assert r.status_code == 200
    assert len(_quiz_question_ids(r.text)) == 6  # total split across 2 units


def test_practice_quiz_requires_a_selection(client, provider, fetcher):
    sid = _imported_subject(client)
    r = client.post(f"/practice/{sid}/quiz", data={"item_ids": [], "n": 5})
    assert r.status_code == 200
    assert "請至少勾選一個單元" in r.text


def test_practice_quiz_ignores_foreign_item_ids(client, provider, fetcher):
    sid = _imported_subject(client)
    iids = _item_ids(client, sid)
    # 999999 不屬於該 subject → 被忽略,只就合法單元出題。
    r = client.post(
        f"/practice/{sid}/quiz",
        data={"item_ids": [iids[0], 999999], "n": 4},
    )
    assert r.status_code == 200
    assert len(_quiz_question_ids(r.text)) == 4
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_quiz.py -k practice_quiz -v`
Expected: FAIL — 404(端點未定義)或斷言失敗

- [ ] **Step 3: 實作端點**

在 `app/routers/quiz.py` 更新 imports,並在 `practice()` 路由「之前」加新端點。

更新 import 行(`from ..services import ...`)為:

```python
from ..services import (
    allocate_questions,
    assemble_quiz_plan,
    practice_units,
    practice_weight,
    resolve_source_text,
    select_practice_item,
)
```

新增端點(放在 `answer_question` 與 `practice` 之間):

```python
@router.post("/practice/{subject_id}/quiz", response_class=HTMLResponse)
def practice_quiz(
    subject_id: int,
    request: Request,
    item_ids: list[int] = Form(default=[]),
    n: int = Form(5),
    session: Session = Depends(get_session),
    provider: QuestionProvider = Depends(get_question_provider),
    fetcher: TranscriptFetcher = Depends(get_transcript_fetcher),
):
    """Build one quiz across several selected units (practice page, entry B)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")

    # Keep only ids that belong to this subject, preserving need order.
    units = practice_units(subject)
    selected = [u.item for u in units if u.item.id in set(item_ids)]
    if not selected:
        return _error(request, "請至少勾選一個單元。")

    n = _clamp_n(n)
    weights = [(it.id, practice_weight(it)) for it in selected]
    plan = allocate_questions(weights, n)

    by_id = {it.id: it for it in selected}
    questions: list[Question] = []
    new_questions: list[Question] = []
    for item_id, count in plan.items():
        if count <= 0:
            continue
        item = by_id[item_id]
        reuse, to_generate = assemble_quiz_plan(item, count)
        questions.extend(reuse)
        if to_generate > 0:
            transcript = fetcher.fetch(item.video_id)
            source = resolve_source_text(item, transcript)
            try:
                generated = provider.generate(source, to_generate)
            except AIError as exc:
                return _error(request, str(exc))
            for g in generated:
                q = Question(
                    item_id=item.id,
                    type=g.type,
                    stem=g.stem,
                    options_json=json.dumps(g.options, ensure_ascii=False),
                    answer_index=g.answer_index,
                    explanation=g.explanation,
                )
                session.add(q)
                new_questions.append(q)
                questions.append(q)

    if new_questions:
        session.commit()
        for q in new_questions:
            session.refresh(q)

    return templates.TemplateResponse(
        request, "partials/quiz.html", {"item": subject, "questions": questions}
    )
```

> 註:`partials/quiz.html` 只用 `questions`,模板 context 的 `item` 不被該 partial 引用,傳 `subject` 無妨(保持 key 存在)。

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_quiz.py -k practice_quiz -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/routers/quiz.py tests/test_quiz.py
git commit -m "feat: POST /practice/{id}/quiz — multi-unit practice quiz endpoint"
```

---

## Task 4: 改寫 `practice()` 路由 + `practice.html`

練習頁列出全部單元勾選清單 + 總題數 + 開始出題,改用新端點。

**Files:**
- Modify: `app/routers/quiz.py`(`practice` 路由)
- Modify: `app/templates/practice.html`
- Test: `tests/test_quiz.py`(更新 `test_practice_route_picks_item_and_offers_quiz`)

- [ ] **Step 1: 更新/新增測試**

把既有 `test_practice_route_picks_item_and_offers_quiz` 整段替換為:

```python
def test_practice_route_lists_selectable_units(client):
    sid = _imported_subject(client)
    resp = client.get(f"/practice/{sid}")
    assert resp.status_code == 200
    # 勾選清單:3 支影片各一個 checkbox,送到新端點。
    assert resp.text.count('name="item_ids"') == 3
    assert f'/practice/{sid}/quiz' in resp.text
    assert "Charlie" in resp.text  # 影片標題列出
    assert "開始出題" in resp.text
```

`test_practice_empty_subject` 保持不變(空狀態文案沿用)。

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_quiz.py -k "practice_route or practice_empty" -v`
Expected: FAIL — 新斷言(`name="item_ids"` 等)在舊模板中不存在

- [ ] **Step 3: 改寫 `practice()` 路由**

替換 `app/routers/quiz.py` 的 `practice` 函式為:

```python
@router.get("/practice/{subject_id}", response_class=HTMLResponse)
def practice(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Entry B: list every unit with stats so the learner picks what to drill."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    units = practice_units(subject)
    return templates.TemplateResponse(
        request, "practice.html", {"subject": subject, "units": units}
    )
```

> `select_practice_item` 已不再於此路由使用,但保留於 services(可能他用);若 lint 報未使用 import,從 `quiz.py` 的 services import 移除 `select_practice_item`。

- [ ] **Step 4: 改寫 `practice.html`**

整檔替換 `app/templates/practice.html`:

```html
{% extends "base.html" %}
{% block content %}
<nav class="crumb"><a href="/subjects/{{ subject.id }}">← {{ subject.name }}</a></nav>
<section class="panel">
  <h2>練習推薦:{{ subject.name }}</h2>
  {% if units %}
  <p class="hint">勾選想練的單元(沒練過或錯誤率高的排在前面),選好總題數,AI 會依弱項分配題目。</p>
  <form class="practice-pick"
        hx-post="/practice/{{ subject.id }}/quiz"
        hx-target="#practice-quiz"
        hx-swap="innerHTML"
        hx-indicator="#practice-spin"
        hx-disabled-elt="find button[type=submit]">
    <div class="pick-toolbar">
      <label><input type="checkbox" id="pick-all" checked> 全選</label>
      <label class="quiz-n">總題數
        <select name="n">
          {% for i in range(1, 11) %}
          <option value="{{ i }}" {{ 'selected' if i == 5 }}>{{ i }}</option>
          {% endfor %}
        </select>
      </label>
      <button type="submit">開始出題</button>
      <span id="practice-spin" class="htmx-indicator spinner">出題中…</span>
    </div>
    <ul class="pick-list">
      {% for u in units %}
      <li class="pick-row">
        <label>
          <input type="checkbox" name="item_ids" value="{{ u.item.id }}" checked>
          <span class="pick-title">{{ u.item.title }}</span>
        </label>
        <span class="pick-stats">
          {% if u.practiced %}
          練習 {{ u.attempts }} 次 · 錯誤率 {{ u.error_rate }}%
          {% else %}
          未練習
          {% endif %}
        </span>
      </li>
      {% endfor %}
    </ul>
  </form>
  <div id="practice-quiz" class="quiz-panel-box"></div>
  <script>
    (function () {
      var all = document.getElementById('pick-all');
      if (!all) return;
      var boxes = function () {
        return document.querySelectorAll('.pick-list input[name="item_ids"]');
      };
      all.addEventListener('change', function () {
        boxes().forEach(function (b) { b.checked = all.checked; });
      });
    })();
  </script>
  {% else %}
  <p class="empty">這個主題還沒有可練習的影片,先去匯入一些吧!</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/test_quiz.py -k "practice_route or practice_empty" -v`
Expected: PASS(2 passed)

- [ ] **Step 6: 全測試回歸**

Run: `python -m pytest -q`
Expected: 全綠(既有 quiz/app 測試不受影響)

- [ ] **Step 7: Commit**

```bash
git add app/routers/quiz.py app/templates/practice.html tests/test_quiz.py
git commit -m "feat: practice page multi-unit selection UI wired to new endpoint"
```

---

## Task 5: 樣式(`styles.css`)

讓勾選清單可讀(列分隔、統計右對齊)。樣式為視覺微調,無對應自動測試。

**Files:**
- Modify: `app/static/styles.css`

- [ ] **Step 1: 加樣式**

在 `app/static/styles.css` 末尾(quiz 相關區段附近)加:

```css
.practice-pick .pick-toolbar {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}
.practice-pick .pick-list {
  list-style: none;
  padding: 0;
  margin: 0 0 1rem;
}
.practice-pick .pick-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--border, #eee);
}
.practice-pick .pick-row label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}
.practice-pick .pick-stats {
  color: var(--muted, #666);
  font-size: 0.85rem;
  white-space: nowrap;
}
```

> 確認 `--border` / `--muted` 變數已存在;若無,改用既有色票或硬色。先檢視 `styles.css` 既有變數命名再貼。

- [ ] **Step 2: 手動驗證(preview)**

啟動 dev server,開 `/practice/{某主業id}`:勾選列表可讀、全選可用、出題回填正常。截圖佐證。

- [ ] **Step 3: Commit**

```bash
git add app/static/styles.css
git commit -m "style: practice page unit-selection list"
```

---

## Self-Review 註記

- **Spec 覆蓋:** 勾選清單(Task 4)、練習次數/錯誤率(Task 2 `PracticeUnit`)、AI 自動分配權重(Task 1+2)、使用者選總題數(Task 4 表單 + Task 3 `_clamp_n`)、保底 1 題(Task 1)、扁平清單(Task 4)、新端點路線 A(Task 3)、錯題重用(Task 3 沿用 `assemble_quiz_plan`)、未勾提示與外來 id 忽略(Task 3 測試)。全部對應。
- **型別一致:** `allocate_questions(weights: list[tuple[int,float]], n) -> dict[int,int]`、`practice_weight(item)->float`、`practice_units(subject)->list[PracticeUnit]`,跨 Task 3/4 引用一致。
- **無 placeholder:** 每步含完整程式碼與指令。
- **邊界:** `n < 單元數` 時保底退讓為 top-n 各 1 題(Task 1 已實作並測)。
```

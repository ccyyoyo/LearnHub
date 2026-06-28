"""Quiz routes (PRD Phase 3): generate questions, answer, practice entry.

Generation depends on a ``QuestionProvider`` and a ``TranscriptFetcher``, both
injected as FastAPI dependencies so tests can swap in fakes (mirroring how
``YouTubeClient`` is overridden).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ..ai.base import QuestionProvider
from ..ai.errors import AIError
from ..ai.factory import get_provider
from ..db import get_session
from ..models import Attempt, Item, Question, Subject
from ..services import (
    allocate_questions,
    assemble_quiz_plan,
    practice_units,
    practice_weight,
    resolve_source_text,
    select_practice_item,
)
from ..templating import templates
from ..transcripts import TranscriptFetcher

router = APIRouter()


def get_question_provider() -> QuestionProvider:
    """Active provider (overridden in tests)."""
    return get_provider()


def get_transcript_fetcher() -> TranscriptFetcher:
    """Transcript source (overridden in tests)."""
    return TranscriptFetcher()


def _clamp_n(n: int) -> int:
    return max(1, min(10, n))


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/import_error.html", {"message": message}
    )


@router.post("/items/{item_id}/quiz", response_class=HTMLResponse)
def make_quiz(
    item_id: int,
    request: Request,
    n: int = Form(5),
    session: Session = Depends(get_session),
    provider: QuestionProvider = Depends(get_question_provider),
    fetcher: TranscriptFetcher = Depends(get_transcript_fetcher),
):
    """Build an N-question quiz: reuse wrong questions, generate the rest."""
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    n = _clamp_n(n)

    reuse, to_generate = assemble_quiz_plan(item, n)

    new_questions: list[Question] = []
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
        session.commit()
        for q in new_questions:
            session.refresh(q)

    questions = list(reuse) + new_questions
    return templates.TemplateResponse(
        request, "partials/quiz.html", {"item": item, "questions": questions}
    )


@router.post("/questions/{question_id}/answer", response_class=HTMLResponse)
def answer_question(
    question_id: int,
    request: Request,
    chosen_index: int = Form(...),
    session: Session = Depends(get_session),
):
    """Record an answer and return the graded question fragment."""
    question = session.get(Question, question_id)
    if not question:
        raise HTTPException(404, "Question not found")
    is_correct = chosen_index == question.answer_index
    session.add(
        Attempt(
            question_id=question.id,
            chosen_index=chosen_index,
            is_correct=is_correct,
        )
    )
    session.commit()
    return templates.TemplateResponse(
        request,
        "partials/quiz_result.html",
        {"question": question, "chosen_index": chosen_index, "is_correct": is_correct},
    )


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


@router.get("/practice/{subject_id}", response_class=HTMLResponse)
def practice(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Entry B: auto-pick the subject's most-needed item, then offer 出題."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    item = select_practice_item(subject)
    return templates.TemplateResponse(
        request, "practice.html", {"subject": subject, "item": item}
    )

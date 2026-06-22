"""Subject + page routes (FR-1, FR-3, FR-4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import ItemStatus, Subject
from ..templating import templates

router = APIRouter()


def _subject_counts(session: Session) -> list[tuple[Subject, int]]:
    subjects = session.exec(select(Subject).order_by(Subject.created_at)).all()
    rows: list[tuple[Subject, int]] = []
    for subject in subjects:
        count = len(subject.resources)
        rows.append((subject, count))
    return rows


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    """Landing page: subjects with their resource counts (FR-1.2)."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"subject_rows": _subject_counts(session)},
    )


@router.post("/subjects", response_class=HTMLResponse)
def create_subject(
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Add a subject (FR-1.1). Returns the refreshed subject list (HTMX)."""
    name = name.strip()
    if name:
        session.add(Subject(name=name))
        session.commit()
    return templates.TemplateResponse(
        request,
        "partials/subject_list.html",
        {"subject_rows": _subject_counts(session)},
    )


@router.post("/subjects/{subject_id}/rename", response_class=HTMLResponse)
def rename_subject(
    subject_id: int,
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Rename a subject (FR-1.3, optional)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    name = name.strip()
    if name:
        subject.name = name
        session.add(subject)
        session.commit()
    return RedirectResponse(f"/subjects/{subject_id}", status_code=303)


@router.delete("/subjects/{subject_id}", response_class=HTMLResponse)
def delete_subject(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Delete a subject and its resources/items (FR-1.3, optional)."""
    subject = session.get(Subject, subject_id)
    if subject:
        session.delete(subject)
        session.commit()
    return templates.TemplateResponse(
        request,
        "partials/subject_list.html",
        {"subject_rows": _subject_counts(session)},
    )


@router.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_detail(
    subject_id: int,
    request: Request,
    filter: str = "all",
    session: Session = Depends(get_session),
):
    """Subject detail: resources, completion, and status-filtered items (FR-4.2)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")

    if filter not in {"all", "in_progress", "incomplete"}:
        filter = "all"

    return templates.TemplateResponse(
        request,
        "subject.html",
        {
            "subject": subject,
            "resources": sorted(subject.resources, key=lambda r: r.created_at),
            "filter": filter,
            "filter_item": _filter_predicate(filter),
        },
    )


def _filter_predicate(filter: str):
    if filter == "in_progress":
        return lambda it: it.status is ItemStatus.in_progress
    if filter == "incomplete":
        return lambda it: it.status is not ItemStatus.done
    return lambda it: True

"""Subject + page routes (FR-1, FR-3, FR-4) + edit mode (rename / bulk / delete)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Item, ItemStatus, Resource, Subject, utcnow
from ..templating import templates

router = APIRouter()


def _subject_counts(session: Session) -> list[tuple[Subject, int]]:
    subjects = session.exec(select(Subject).order_by(Subject.created_at)).all()
    rows: list[tuple[Subject, int]] = []
    for subject in subjects:
        count = len(subject.resources)
        rows.append((subject, count))
    return rows


def _filter_predicate(filter: str):
    if filter == "in_progress":
        return lambda it: it.status is ItemStatus.in_progress
    if filter == "incomplete":
        return lambda it: it.status is not ItemStatus.done
    return lambda it: True


def _normalize_filter(filter: str) -> str:
    return filter if filter in {"all", "in_progress", "incomplete"} else "all"


def _subject_context(subject: Subject, filter: str, edit: bool) -> dict:
    """Context shared by the subject page and the resources partial."""
    return {
        "subject": subject,
        "resources": sorted(subject.resources, key=lambda r: r.created_at),
        "filter": filter,
        "filter_item": _filter_predicate(filter),
        "edit": edit,
    }


def _render_resources(
    request: Request, subject: Subject, filter: str, edit: bool
) -> HTMLResponse:
    """Re-render just the resources list, preserving filter + edit state."""
    return templates.TemplateResponse(
        request, "partials/resources.html", _subject_context(subject, filter, edit)
    )


def _subject_items(
    session: Session, subject_id: int, item_ids: list[int]
) -> list[Item]:
    """Items in ``item_ids`` that actually belong to this subject (ignore the rest)."""
    if not item_ids:
        return []
    return session.exec(
        select(Item)
        .join(Resource)
        .where(Resource.subject_id == subject_id, Item.id.in_(item_ids))
    ).all()


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


@router.get("/subjects/{subject_id}/header", response_class=HTMLResponse)
def subject_header(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Static subject title with the 改名 trigger (used to cancel renaming)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    return templates.TemplateResponse(
        request, "partials/subject_header.html", {"subject": subject}
    )


@router.get("/subjects/{subject_id}/rename-form", response_class=HTMLResponse)
def rename_form(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Inline rename form that swaps the subject header (FR-1.3)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    return templates.TemplateResponse(
        request, "partials/rename_form.html", {"subject": subject}
    )


@router.post("/subjects/{subject_id}/rename", response_class=HTMLResponse)
def rename_subject(
    subject_id: int,
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Rename a subject (FR-1.3). Returns the refreshed header fragment (HTMX)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    name = name.strip()
    if name:
        subject.name = name
        session.add(subject)
        session.commit()
        session.refresh(subject)
    return templates.TemplateResponse(
        request, "partials/subject_header.html", {"subject": subject}
    )


@router.delete("/subjects/{subject_id}", response_class=HTMLResponse)
def delete_subject(
    subject_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Delete a subject and its resources/items (FR-1.3)."""
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
    edit: bool = False,
    session: Session = Depends(get_session),
):
    """Subject detail: resources, completion, status filter, and edit mode (FR-4.2)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    return templates.TemplateResponse(
        request, "subject.html", _subject_context(subject, _normalize_filter(filter), edit)
    )


@router.post("/subjects/{subject_id}/items/bulk-status", response_class=HTMLResponse)
def bulk_status(
    subject_id: int,
    request: Request,
    item_ids: list[int] = Form(default=[]),
    status: str = Form(...),
    filter: str = Form("all"),
    edit: bool = Form(True),
    session: Session = Depends(get_session),
):
    """Set the same status on every selected item (edit mode bulk action)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    try:
        new_status = ItemStatus(status)
    except ValueError:
        raise HTTPException(400, "Invalid status")
    for item in _subject_items(session, subject_id, item_ids):
        item.status = new_status
        item.updated_at = utcnow()
        session.add(item)
    session.commit()
    session.refresh(subject)
    return _render_resources(request, subject, _normalize_filter(filter), edit)


@router.post("/subjects/{subject_id}/items/bulk-delete", response_class=HTMLResponse)
def bulk_delete(
    subject_id: int,
    request: Request,
    item_ids: list[int] = Form(default=[]),
    filter: str = Form("all"),
    edit: bool = Form(True),
    session: Session = Depends(get_session),
):
    """Delete every selected item (edit mode bulk action)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    for item in _subject_items(session, subject_id, item_ids):
        session.delete(item)
    session.commit()
    session.refresh(subject)
    return _render_resources(request, subject, _normalize_filter(filter), edit)


@router.delete(
    "/subjects/{subject_id}/resources/{resource_id}", response_class=HTMLResponse
)
def delete_resource(
    subject_id: int,
    resource_id: int,
    request: Request,
    filter: str = "all",
    edit: bool = True,
    session: Session = Depends(get_session),
):
    """Delete a whole resource and its items (edit mode)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    resource = session.get(Resource, resource_id)
    if resource and resource.subject_id == subject_id:
        session.delete(resource)
        session.commit()
        session.refresh(subject)
    return _render_resources(request, subject, _normalize_filter(filter), edit)

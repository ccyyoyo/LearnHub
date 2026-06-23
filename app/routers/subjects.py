"""Subject + page routes (FR-1, FR-3, FR-4) + edit mode (rename / bulk / delete)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Item, ItemStatus, Resource, Subject, utcnow
from ..services import normalize_progress_mode, overall_progress, subject_progress
from ..templating import templates
from ..youtube import YouTubeClient, YouTubeError

router = APIRouter()


def _subjects_with_counts(
    session: Session,
) -> tuple[list[Subject], list[tuple[Subject, int]]]:
    subjects = session.exec(select(Subject).order_by(Subject.created_at)).all()
    rows = [(subject, len(subject.resources)) for subject in subjects]
    return subjects, rows


def _subject_list_context(session: Session) -> dict:
    """Subject list rows + the floating overall-progress widget (OOB)."""
    subjects, rows = _subjects_with_counts(session)
    return {
        "subject_rows": rows,
        "fp": overall_progress(subjects),
        "floating_progress_title": "總進度",
        "emit_oob_floating": True,
    }


def _filter_predicate(filter: str):
    if filter == "in_progress":
        return lambda it: it.status is ItemStatus.in_progress
    if filter == "incomplete":
        return lambda it: it.status is not ItemStatus.done
    return lambda it: True


def _normalize_filter(filter: str) -> str:
    return filter if filter in {"all", "in_progress", "incomplete"} else "all"


def _subject_context(
    subject: Subject, filter: str, edit: bool, progress: str = "count"
) -> dict:
    """Context shared by the subject page and the resources partial."""
    return {
        "subject": subject,
        "resources": sorted(subject.resources, key=lambda r: r.created_at),
        "filter": filter,
        "filter_item": _filter_predicate(filter),
        "edit": edit,
        "progress_mode": normalize_progress_mode(progress),
        "fp": subject_progress(subject),
        "floating_progress_title": subject.name,
    }


def _render_resources(
    request: Request, subject: Subject, filter: str, edit: bool, progress: str = "count"
) -> HTMLResponse:
    """Re-render the resources list, preserving filter + edit + progress state."""
    context = _subject_context(subject, filter, edit, progress)
    context["emit_oob_floating"] = True  # refresh the floating widget too
    return templates.TemplateResponse(request, "partials/resources.html", context)


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
    context = _subject_list_context(session)
    context["emit_oob_floating"] = False  # full page: base.html renders it inline
    return templates.TemplateResponse(request, "index.html", context)


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
        request, "partials/subject_list.html", _subject_list_context(session)
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
        request, "partials/subject_list.html", _subject_list_context(session)
    )


@router.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_detail(
    subject_id: int,
    request: Request,
    filter: str = "all",
    edit: bool = False,
    progress: str = "count",
    session: Session = Depends(get_session),
):
    """Subject detail: resources, completion, status filter, and edit mode (FR-4.2)."""
    subject = session.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    return templates.TemplateResponse(
        request,
        "subject.html",
        _subject_context(subject, _normalize_filter(filter), edit, progress),
    )


@router.post("/subjects/{subject_id}/items/bulk-status", response_class=HTMLResponse)
def bulk_status(
    subject_id: int,
    request: Request,
    item_ids: list[int] = Form(default=[]),
    status: str = Form(...),
    filter: str = Form("all"),
    edit: bool = Form(True),
    progress: str = Form("count"),
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
    return _render_resources(request, subject, _normalize_filter(filter), edit, progress)


@router.post("/subjects/{subject_id}/items/bulk-delete", response_class=HTMLResponse)
def bulk_delete(
    subject_id: int,
    request: Request,
    item_ids: list[int] = Form(default=[]),
    filter: str = Form("all"),
    edit: bool = Form(True),
    progress: str = Form("count"),
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
    return _render_resources(request, subject, _normalize_filter(filter), edit, progress)


@router.delete(
    "/subjects/{subject_id}/resources/{resource_id}", response_class=HTMLResponse
)
def delete_resource(
    subject_id: int,
    resource_id: int,
    request: Request,
    filter: str = "all",
    edit: bool = True,
    progress: str = "count",
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
    return _render_resources(request, subject, _normalize_filter(filter), edit, progress)


@router.post(
    "/subjects/{subject_id}/resources/{resource_id}/refresh-durations",
    response_class=HTMLResponse,
)
async def refresh_durations(
    subject_id: int,
    resource_id: int,
    request: Request,
    filter: str = Form("all"),
    edit: bool = Form(False),
    progress: str = Form("count"),
    session: Session = Depends(get_session),
    client: YouTubeClient = Depends(YouTubeClient),
):
    """Re-fetch each video's length from YouTube and update the stored items.

    Returns a flash plus an out-of-band swap of the resources list (same shape
    as an import), so durations/totals refresh in place. On API failure we only
    swap in an error flash, leaving the resources untouched.
    """
    subject = session.get(Subject, subject_id)
    resource = session.get(Resource, resource_id)
    if not subject or not resource or resource.subject_id != subject_id:
        return templates.TemplateResponse(
            request,
            "partials/import_error.html",
            {"message": "找不到資源,請重新整理頁面。"},
        )

    try:
        durations = await client.fetch_durations([it.video_id for it in resource.items])
    except YouTubeError as exc:
        return templates.TemplateResponse(
            request, "partials/import_error.html", {"message": str(exc)}
        )

    updated = 0
    for item in resource.items:
        new_seconds = durations.get(item.video_id)
        if new_seconds is not None and new_seconds != item.duration_seconds:
            item.duration_seconds = new_seconds
            session.add(item)
            updated += 1
    session.commit()
    session.refresh(subject)

    context = _subject_context(subject, _normalize_filter(filter), edit, progress)
    context.update({"resource": resource, "updated": updated})
    return templates.TemplateResponse(request, "partials/refresh_result.html", context)

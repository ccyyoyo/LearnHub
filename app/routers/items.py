"""Item status routes (FR-3.1, FR-3.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Item, ItemStatus, utcnow
from ..services import next_status, subject_progress, sync_video_siblings
from ..templating import templates

router = APIRouter(prefix="/items")


def _render(request: Request, item: Item, changed_siblings: list[Item]) -> HTMLResponse:
    """Return the swapped item row plus out-of-band fragments.

    HTMX swaps the clicked row in place; OOB fragments update the parent
    resource's completion and the floating subject-progress widget (x/y + %)
    without a full reload (FR-3.2). Copies of the same video keep their status
    in sync, so any of those copies visible on the current page is swapped OOB
    too, along with the progress bar of the list it lives in. Each bar renders
    both count and time readings; the active mode is picked client-side.
    """
    subject = item.resource.subject
    # Only siblings on the current subject page can be swapped in place.
    page_siblings = [s for s in changed_siblings if s.resource.subject_id == subject.id]
    # Distinct other lists whose progress bars also moved.
    sibling_resources = []
    seen: set[int] = set()
    for s in page_siblings:
        if s.resource_id != item.resource_id and s.resource_id not in seen:
            seen.add(s.resource_id)
            sibling_resources.append(s.resource)
    return templates.TemplateResponse(
        request,
        "partials/item_status_response.html",
        {
            "item": item,
            "resource": item.resource,
            "with_oob_progress": True,
            "with_oob_floating": True,
            "siblings": page_siblings,
            "sibling_resources": sibling_resources,
            "fp": subject_progress(subject),
            "floating_progress_title": subject.name,
        },
    )


@router.post("/{item_id}/cycle", response_class=HTMLResponse)
def cycle_status(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """One-click cycle: not_started → in_progress → done → not_started."""
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    item.status = next_status(item.status)
    item.updated_at = utcnow()
    session.add(item)
    changed = sync_video_siblings(session, item)
    session.commit()
    session.refresh(item)
    return _render(request, item, changed)


@router.post("/{item_id}/status", response_class=HTMLResponse)
def set_status(
    item_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    """Set an explicit status value (FR-3.1)."""
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    try:
        item.status = ItemStatus(status)
    except ValueError:
        raise HTTPException(400, "Invalid status")
    item.updated_at = utcnow()
    session.add(item)
    changed = sync_video_siblings(session, item)
    session.commit()
    session.refresh(item)
    return _render(request, item, changed)

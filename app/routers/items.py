"""Item status routes (FR-3.1, FR-3.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Item, ItemStatus, utcnow
from ..services import next_status, normalize_progress_mode
from ..templating import templates

router = APIRouter(prefix="/items")


def _render(request: Request, item: Item, progress: str = "count") -> HTMLResponse:
    """Return the swapped item row plus an out-of-band resource progress bar.

    HTMX swaps the row in place, and the OOB fragment updates the parent
    resource's completion without a full reload (FR-3.2). ``progress`` keeps the
    re-rendered bar in whichever mode (count / time) the user is viewing.
    """
    return templates.TemplateResponse(
        request,
        "partials/item_row.html",
        {
            "item": item,
            "resource": item.resource,
            "with_oob_progress": True,
            "progress_mode": normalize_progress_mode(progress),
        },
    )


@router.post("/{item_id}/cycle", response_class=HTMLResponse)
def cycle_status(
    item_id: int,
    request: Request,
    progress: str = "count",
    session: Session = Depends(get_session),
):
    """One-click cycle: not_started → in_progress → done → not_started."""
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    item.status = next_status(item.status)
    item.updated_at = utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _render(request, item, progress)


@router.post("/{item_id}/status", response_class=HTMLResponse)
def set_status(
    item_id: int,
    request: Request,
    status: str = Form(...),
    progress: str = Form("count"),
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
    session.commit()
    session.refresh(item)
    return _render(request, item, progress)

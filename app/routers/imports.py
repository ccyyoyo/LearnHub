"""Integrated import route (FR-2) — the product's core loop.

Paste a URL → fetch from YouTube → write to DB → render items, all inside the
UI with an HTMX spinner, no external scripts (G2 / FR-2.5 / NFR-2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Item, Resource, Subject
from ..services import normalize_item_sort, sort_items, subject_progress
from ..templating import templates
from ..youtube import YouTubeClient, YouTubeError, parse_youtube_url

router = APIRouter()

# Sentinel stored in source_url for the aggregate "single videos" resource.
# Not shown to users — just an internal bucket identifier.
_SINGLES_SOURCE = "__singles__"


@router.post("/import", response_class=HTMLResponse)
async def import_resource(
    request: Request,
    subject_id: int = Form(...),
    url: str = Form(...),
    sort: str = Form("original"),
    session: Session = Depends(get_session),
    client: YouTubeClient = Depends(YouTubeClient),
):
    subject = session.get(Subject, subject_id)
    if not subject:
        return _error(request, "找不到主題,請重新整理頁面。")

    try:
        parsed = parse_youtube_url(url)
        title, videos = await client.fetch(parsed)
    except YouTubeError as exc:
        return _error(request, str(exc))

    from ..models import ResourceType

    if parsed.type is ResourceType.video:
        # All single-video imports share one aggregate resource per subject,
        # grouped by source type rather than by URL.
        resource = session.exec(
            select(Resource).where(
                Resource.subject_id == subject_id,
                Resource.type == ResourceType.video,
            )
        ).first()
        if resource is None:
            resource = Resource(
                subject_id=subject_id,
                type=ResourceType.video,
                source_url=_SINGLES_SOURCE,
                title="個別影片",
            )
            session.add(resource)
            session.commit()
            session.refresh(resource)
    else:
        # Playlists each get their own resource, looked up by URL (idempotent).
        resource = session.exec(
            select(Resource).where(
                Resource.subject_id == subject_id,
                Resource.source_url == url.strip(),
            )
        ).first()
        if resource is None:
            resource = Resource(
                subject_id=subject_id,
                type=parsed.type,
                source_url=url.strip(),
                title=title,
            )
            session.add(resource)
            session.commit()
            session.refresh(resource)

    existing_ids = {it.video_id for it in resource.items}
    # For the aggregate single-video resource, append after the last position.
    # For playlists, the position from the API reflects the playlist order.
    next_pos = max((it.position for it in resource.items), default=-1) + 1
    added = 0
    for video in videos:
        if video.video_id in existing_ids:
            continue
        pos = next_pos + added if parsed.type is ResourceType.video else video.position
        session.add(
            Item(
                resource_id=resource.id,
                video_id=video.video_id,
                title=video.title,
                thumbnail_url=video.thumbnail_url,
                duration_seconds=video.duration_seconds,
                position=pos,
            )
        )
        existing_ids.add(video.video_id)
        added += 1
    session.commit()
    session.refresh(resource)
    session.refresh(subject)
    sort = normalize_item_sort(sort)

    return templates.TemplateResponse(
        request,
        "partials/import_result.html",
        {
            "subject": subject,
            "resource": resource,
            "added": added,
            "total": len(videos),
            "resources": sorted(subject.resources, key=lambda r: r.created_at),
            "filter_item": lambda it: True,
            "filter": "all",
            "sort": sort,
            "sort_items": lambda items: sort_items(list(items), sort),
            "edit": False,
            "fp": subject_progress(subject),
            "floating_progress_title": subject.name,
        },
    )


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/import_error.html",
        {"message": message},
        status_code=200,  # HTMX swaps the fragment regardless; keep it 200.
    )

"""AI assist routes (Phase 3): on-demand summary / study notes per item.

The pipeline per click is: ``item.video_id`` → transcript (cached in
``Transcript``) → LLM (cached in ``AIArtifact``) → HTMX fragment. Both caches are
keyed by ``video_id`` so we never re-fetch or re-generate the same thing, and a
playlist where the same video recurs only pays once.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..ai import AIClient, AIError
from ..config import get_settings
from ..db import get_session
from ..models import AIArtifact, AIKind, Item, Transcript
from ..templating import templates
from ..transcript import TranscriptError, TranscriptFetcher

router = APIRouter(prefix="/items")


@router.post("/{item_id}/summarize", response_class=HTMLResponse)
async def summarize(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
    fetcher: TranscriptFetcher = Depends(TranscriptFetcher),
    ai: AIClient = Depends(AIClient),
):
    return await _generate(request, item_id, AIKind.summary, session, fetcher, ai)


@router.post("/{item_id}/notes", response_class=HTMLResponse)
async def notes(
    item_id: int,
    request: Request,
    session: Session = Depends(get_session),
    fetcher: TranscriptFetcher = Depends(TranscriptFetcher),
    ai: AIClient = Depends(AIClient),
):
    return await _generate(request, item_id, AIKind.notes, session, fetcher, ai)


async def _generate(
    request: Request,
    item_id: int,
    kind: AIKind,
    session: Session,
    fetcher: TranscriptFetcher,
    ai: AIClient,
) -> HTMLResponse:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    artifact = session.exec(
        select(AIArtifact).where(
            AIArtifact.video_id == item.video_id, AIArtifact.kind == kind
        )
    ).first()

    if artifact is None:
        try:
            transcript_text = await _transcript_text(session, fetcher, item.video_id)
            content = await ai.generate(kind, transcript_text)
        except (TranscriptError, AIError) as exc:
            return _error(request, str(exc))
        artifact = AIArtifact(
            video_id=item.video_id,
            kind=kind,
            content_md=content,
            model=get_settings().llm_model,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)

    return templates.TemplateResponse(
        request, "partials/ai_result.html", {"art": artifact, "item": item}
    )


async def _transcript_text(
    session: Session, fetcher: TranscriptFetcher, video_id: str
) -> str:
    """Return cached transcript text, fetching + caching it on first use."""
    cached = session.get(Transcript, video_id)
    if cached:
        return cached.content
    # The library is blocking I/O — keep the event loop free.
    result = await asyncio.to_thread(fetcher.fetch, video_id)
    session.add(
        Transcript(video_id=video_id, language=result.language, content=result.text)
    )
    session.commit()
    return result.text


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/ai_error.html",
        {"message": message},
        status_code=200,  # HTMX swaps the fragment regardless; keep it 200.
    )

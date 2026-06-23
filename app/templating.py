"""Shared Jinja2 environment, with domain helpers exposed to templates."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import STATUS_LABELS, ItemStatus
from .services import (
    DEFAULT_PROGRESS_MODE,
    format_duration,
    item_progress,
    resource_progress,
    resource_total_seconds,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Expose helpers/enums so templates don't need them passed every time.
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["ItemStatus"] = ItemStatus
templates.env.globals["resource_progress"] = resource_progress
templates.env.globals["item_progress"] = item_progress
templates.env.globals["resource_total_seconds"] = resource_total_seconds
templates.env.globals["format_duration"] = format_duration
# Default progress mode; any render context can override it per request.
templates.env.globals["progress_mode"] = DEFAULT_PROGRESS_MODE

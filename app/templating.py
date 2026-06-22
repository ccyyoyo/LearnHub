"""Shared Jinja2 environment, with domain helpers exposed to templates."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import STATUS_LABELS, ItemStatus
from .services import item_progress, resource_progress

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Expose helpers/enums so templates don't need them passed every time.
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["ItemStatus"] = ItemStatus
templates.env.globals["resource_progress"] = resource_progress
templates.env.globals["item_progress"] = item_progress

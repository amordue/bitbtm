"""Shared UI helpers for Jinja responses."""

from pathlib import Path
from typing import Any, Iterable, Mapping

from fastapi import Request
from fastapi.templating import Jinja2Templates

HTMX_SCRIPT_URL = "https://unpkg.com/htmx.org@1.9.12"

_TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def badge_props(status: Any) -> dict[str, str]:
    """Build template-friendly badge metadata for Enum-backed status values."""
    value = getattr(status, "value", str(status))
    return {
        "value": value,
        "class_name": f"badge badge-{value}",
    }


templates.env.globals["badge_props"] = badge_props
templates.env.globals["app_name"] = "BitBT"


def render_template(
    request: Request,
    template_name: str,
    *,
    title: str,
    context: Mapping[str, Any] | None = None,
    stylesheets: Iterable[str] = (),
    script_srcs: Iterable[str] = (),
    body_class: str = "",
    status_code: int = 200,
):
    """Render a Jinja template with shared page context."""
    template_context = {
        "request": request,
        "page_title": title,
        "stylesheets": list(stylesheets),
        "script_srcs": list(script_srcs),
        "body_class": body_class,
    }
    if context:
        template_context.update(context)

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=template_context,
        status_code=status_code,
    )
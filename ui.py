"""Shared UI helpers for FastHTML responses."""

from typing import Any, Iterable

from fastapi.responses import HTMLResponse
from fasthtml.common import Body, Head, Html, Meta, Script, Style, Title, to_xml

HTMX_SCRIPT_URL = "https://unpkg.com/htmx.org@1.9.12"

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #111;
    color: #f0f0f0;
    min-height: 100vh;
}
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
.card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.2rem;
}
.btn {
    display: inline-block;
    padding: 0.55rem 1.1rem;
    border-radius: 6px;
    border: none;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    transition: opacity 0.15s;
}
.btn:hover { opacity: 0.85; text-decoration: none; }
.btn-primary { background: #3b82f6; color: #fff; }
.btn-secondary { background: #2f2f2f; color: #ccc; border: 1px solid #3a3a3a; }
.btn-danger  { background: #ef4444; color: #fff; }
.btn-warning { background: #f59e0b; color: #111; }
.btn-success { background: #22c55e; color: #111; }
.btn-sm { padding: 0.3rem 0.7rem; font-size: 0.78rem; }
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; color: #aaa; font-size: 0.85rem; margin-bottom: 0.3rem; }
.form-control {
    width: 100%;
    background: #111;
    border: 1px solid #333;
    border-radius: 6px;
    color: #f0f0f0;
    padding: 0.55rem 0.75rem;
    font-size: 0.95rem;
}
.form-control:focus { outline: none; border-color: #3b82f6; }
select.form-control { cursor: pointer; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th {
    text-align: left;
    padding: 0.55rem 0.8rem;
    color: #888;
    font-weight: 600;
    border-bottom: 1px solid #2a2a2a;
    white-space: nowrap;
}
td { padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e1e1e; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
.badge {
    display: inline-block;
    padding: 0.18rem 0.5rem;
    border-radius: 99px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.badge-setup       { background: #1f2937; color: #9ca3af; }
.badge-registration{ background: #1e3a5f; color: #60a5fa; }
.badge-qualifying  { background: #1a3a26; color: #4ade80; }
.badge-bracket     { background: #3b1a5f; color: #c084fc; }
.badge-sub_events  { background: #3a2a10; color: #fcd34d; }
.badge-complete    { background: #1a3a1a; color: #86efac; }
.badge-pending     { background: #292929; color: #777; }
.badge-active      { background: #1a3a26; color: #4ade80; }
.badge-completed   { background: #1a3a26; color: #4ade80; }
.badge-reserve     { background: #292929; color: #a78bfa; }
.robot-thumb { width: 44px; height: 44px; object-fit: cover; border-radius: 6px; }
.empty { color: #555; padding: 1.5rem 0; text-align: center; font-size: 0.9rem; }
.alert {
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.2rem;
    font-size: 0.9rem;
}
.alert-error   { background: #3b1010; border: 1px solid #ef4444; color: #fca5a5; }
.alert-success { background: #0f2f1a; border: 1px solid #22c55e; color: #86efac; }
.alert-info    { background: #1e2f4a; border: 1px solid #3b82f6; color: #93c5fd; }
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator { display: inline; }
"""


def page_response(
    title: str,
    *body_content: Any,
    css: str = "",
    script_srcs: Iterable[str] = (),
) -> HTMLResponse:
    """Build a full HTML page response with shared metadata and styles."""
    styles = BASE_CSS if not css else f"{BASE_CSS}\n{css}"
    head_children = [
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Title(f"{title} — BitBT"),
        Style(styles),
    ]
    head_children.extend(Script(src=src) for src in script_srcs)
    return HTMLResponse(to_xml(Html(Head(*head_children), Body(*body_content))))


def status_badge(status: Any):
    """Render a badge for Enum-backed status values."""
    value = getattr(status, "value", str(status))
    from fasthtml.common import Span

    return Span(value, cls=f"badge badge-{value}")
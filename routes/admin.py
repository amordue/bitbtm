"""Organizer-only admin routes (Phase 2 stub — event management added in Phase 4)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fasthtml.common import (
    A,
    Body,
    Div,
    H1,
    H2,
    Head,
    Header,
    Html,
    Li,
    Meta,
    P,
    Style,
    Title,
    Ul,
    to_xml,
)

from auth import NotAuthenticatedException, require_organizer
from models import User

router = APIRouter(prefix="/admin")

_ADMIN_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #111;
    color: #f0f0f0;
    min-height: 100vh;
    padding: 2rem;
}
header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid #333;
}
h1 { font-size: 1.8rem; }
.logout { color: #888; text-decoration: none; font-size: 0.9rem; }
.logout:hover { color: #f0f0f0; }
.card {
    background: #1e1e1e;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}
.coming-soon { color: #666; font-size: 0.9rem; margin-top: 0.5rem; }
ul { list-style: none; margin-top: 0.75rem; }
ul li { padding: 0.4rem 0; color: #aaa; font-size: 0.9rem; }
"""


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    user: User = Depends(require_organizer),
):
    """Organizer dashboard — landing page after login."""
    page = Html(
        Head(
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Title("Dashboard — BitBT"),
            Style(_ADMIN_CSS),
        ),
        Body(
            Div(
                Header(
                    H1("⚙ BitBT Admin"),
                    A("Sign out", href="/auth/logout", cls="logout"),
                ),
                P(f"Signed in as {user.name} ({user.email})"),
                Div(
                    H2("Events"),
                    P("Event management coming in Phase 4.", cls="coming-soon"),
                    cls="card",
                ),
                Div(
                    H2("Upcoming phases"),
                    Ul(
                        Li("Phase 3 — Public roboteer views"),
                        Li("Phase 4 — Event management & Google Sheets import"),
                        Li("Phase 5 — Tournament execution & scoring"),
                    ),
                    cls="card",
                ),
            )
        ),
    )
    return HTMLResponse(to_xml(page))

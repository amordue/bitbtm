"""Auth routes: login page, Google OAuth flow, logout."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fasthtml.common import (
    A,
    Div,
    H1,
    P,
)
from sqlalchemy.orm import Session

from auth import exchange_code_for_tokens, get_authorization_url, get_user_info, upsert_user
from database import get_db
from ui import page_response

router = APIRouter()

_LOGIN_CSS = """
body {
    display: flex;
    align-items: center;
    justify-content: center;
}
.card {
    background: #1e1e1e;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 2.5rem 3rem;
    text-align: center;
    max-width: 380px;
    width: 100%;
}
h1 { font-size: 2.4rem; letter-spacing: -1px; margin-bottom: 0.4rem; }
.subtitle { color: #888; margin-bottom: 2rem; font-size: 0.95rem; }
.btn-google {
    display: inline-block;
    background: #fff;
    color: #333;
    padding: 0.75rem 1.5rem;
    border-radius: 6px;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.95rem;
    transition: background 0.15s;
}
.btn-google:hover { background: #e8e8e8; }
.error { color: #f87171; margin-bottom: 1rem; font-size: 0.9rem; }
"""


@router.get("/login", response_class=HTMLResponse)
def login_page(error: str = ""):
    """Render the Sign-in page."""
    error_el = P(
        "Sign-in failed. Please try again.",
        cls="error",
    ) if error else ""

    return page_response(
        "Sign In",
        Div(
            H1("⚙ BitBT"),
            P("Robot Combat Tournament Manager", cls="subtitle"),
            error_el,
            A("Sign in with Google", href="/auth/google", cls="btn-google"),
            cls="card",
        ),
        css=_LOGIN_CSS,
    )


@router.get("/auth/google")
def google_login(request: Request):
    """Redirect the organizer to Google's OAuth consent screen."""
    auth_url, state, code_verifier = get_authorization_url()
    request.session["oauth_state"] = state
    if code_verifier:
        request.session["oauth_code_verifier"] = code_verifier
    return RedirectResponse(auth_url)


@router.get("/auth/callback")
def auth_callback(
    request: Request,
    code: str,
    state: str,
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback: exchange code, persist user, set session."""
    stored_state = request.session.get("oauth_state")
    if stored_state != state:
        return RedirectResponse("/login?error=1")

    tokens = exchange_code_for_tokens(
        code, state, code_verifier=request.session.pop("oauth_code_verifier", None)
    )
    profile = get_user_info(tokens["access_token"])

    user = upsert_user(
        db,
        google_id=profile["id"],
        email=profile["email"],
        name=profile["name"],
        picture_url=profile.get("picture"),
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        token_expiry=tokens.get("token_expiry"),
    )

    request.session["user_id"] = user.id
    request.session.pop("oauth_state", None)
    return RedirectResponse("/admin", status_code=303)


@router.get("/auth/logout")
def logout(request: Request):
    """Clear the session and redirect to the login page."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

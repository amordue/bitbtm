"""Auth routes: login page, Google OAuth flow, logout."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import exchange_code_for_tokens, get_authorization_url, get_user_info, upsert_user
from database import get_db
from ui import render_template

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    """Render the Sign-in page."""
    return render_template(
        request,
        "auth/login.html",
        title="Sign In",
        context={
            "error_message": "Sign-in failed. Please try again." if error else "",
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/auth.css",),
        body_class="auth-page",
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

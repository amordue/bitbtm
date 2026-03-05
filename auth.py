"""Google OAuth flow, session management, and organizer auth dependencies."""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from config import APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SCOPES
from database import get_db
from models import User

# Allow oauthlib to accept token responses whose scope list differs from what
# was requested (can happen with Google's incremental-auth merging behaviour).
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

_CALLBACK_URL = f"{APP_BASE_URL}/auth/callback"

_CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [_CALLBACK_URL],
    }
}


def _create_flow(state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_config(_CLIENT_CONFIG, scopes=GOOGLE_SCOPES, state=state)
    flow.redirect_uri = _CALLBACK_URL
    return flow


def get_authorization_url() -> tuple[str, str, Optional[str]]:
    """Return (authorization_url, state, code_verifier) to start the OAuth dance.

    google-auth-oauthlib ≥1.0 may auto-generate a PKCE code_verifier; callers
    must persist it in the session so it can be supplied when exchanging the code.
    """
    flow = _create_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    # Retrieve the verifier the library may have injected into the flow.
    code_verifier = getattr(flow, "code_verifier", None)
    return auth_url, state, code_verifier


def exchange_code_for_tokens(code: str, state: str, code_verifier: Optional[str] = None) -> dict:
    """Exchange an authorization code for access/refresh tokens."""
    flow = _create_flow(state=state)
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_expiry": creds.expiry,
    }


def get_user_info(access_token: str) -> dict:
    """Fetch Google profile (id, email, name, picture) using an access token."""
    creds = Credentials(token=access_token)
    service = build("oauth2", "v2", credentials=creds)
    return service.userinfo().get().execute()


def get_valid_access_token(user: User, db: Session) -> str:
    """Return a valid access token, refreshing it automatically if expired."""
    now = datetime.utcnow()
    if user.token_expiry and user.token_expiry > now + timedelta(minutes=1):
        return user.access_token  # still fresh

    creds = Credentials(
        token=user.access_token,
        refresh_token=user.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    creds.refresh(GoogleRequest())
    user.access_token = creds.token
    user.token_expiry = creds.expiry
    db.commit()
    return creds.token


def upsert_user(
    db: Session,
    *,
    google_id: str,
    email: str,
    name: str,
    picture_url: Optional[str],
    access_token: str,
    refresh_token: Optional[str],
    token_expiry: Optional[datetime],
) -> User:
    """Create or update the organizer User record from OAuth profile data."""
    user = db.query(User).filter(User.google_id == google_id).first()
    if user is None:
        user = User(google_id=google_id)
        db.add(user)
    user.email = email
    user.name = name
    user.picture_url = picture_url
    user.access_token = access_token
    if refresh_token:
        user.refresh_token = refresh_token
    user.token_expiry = token_expiry
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """FastAPI dependency — returns the logged-in User, or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


class NotAuthenticatedException(Exception):
    """Raised by require_organizer when no valid session exists."""


def require_organizer(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """FastAPI dependency — raises NotAuthenticatedException if not logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotAuthenticatedException()
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise NotAuthenticatedException()
    return user

"""Auth API endpoints — registration, login, and key validation."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.auth import (
    create_jwt,
    get_api_key,
    get_current_user,
    hash_password,
    require_auth,
    validate_password,
    verify_password,
)
from app.config import settings
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    invite_code: str = ""


class LoginRequest(BaseModel):
    email: str | None = None
    password: str | None = None
    key: str | None = None  # legacy API key login


class LoginResponse(BaseModel):
    ok: bool
    token: str
    user: UserInfo | None = None


class UserInfo(BaseModel):
    id: str
    email: str
    name: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=LoginResponse)
async def register(
    body: RegisterRequest,
    session: Session = Depends(get_session),
) -> LoginResponse:
    """Register a new user account. Returns a JWT token.

    Requires a valid ``invite_code`` when ``CALLME_INVITE_CODE`` is set.
    If the env var is not set, registration is disabled entirely (403).
    """
    # Gate: invite code check
    if not settings.callme_invite_code:
        raise HTTPException(status_code=403, detail="Registration is disabled")
    if body.invite_code != settings.callme_invite_code:
        raise HTTPException(status_code=403, detail="Invalid invite code")

    # Password policy
    password_error = validate_password(body.password)
    if password_error:
        raise HTTPException(status_code=422, detail=password_error)

    # Check for duplicate email
    existing = session.exec(select(User).where(User.email == body.email)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name or body.email.split("@")[0],
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_jwt(user.id, user.email, user.name)
    return LoginResponse(
        ok=True,
        token=token,
        user=UserInfo(id=str(user.id), email=user.email, name=user.name),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: Session = Depends(get_session),
) -> LoginResponse:
    """Login with email+password or legacy API key. Returns a JWT token."""
    # Legacy API key login
    if body.key:
        api_key = get_api_key()
        if not secrets.compare_digest(body.key, api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")
        # Return a JWT for the admin user
        from app.auth import ensure_admin_user
        admin = ensure_admin_user(session)
        token = create_jwt(admin.id, admin.email, admin.name)
        return LoginResponse(
            ok=True,
            token=token,
            user=UserInfo(id=str(admin.id), email=admin.email, name=admin.name),
        )

    # Email + password login
    if not body.email or not body.password:
        raise HTTPException(status_code=422, detail="Email and password are required")

    user = session.exec(select(User).where(User.email == body.email)).first()
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_jwt(user.id, user.email, user.name)
    return LoginResponse(
        ok=True,
        token=token,
        user=UserInfo(id=str(user.id), email=user.email, name=user.name),
    )


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> dict:
    """Return the current user's info."""
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
    }


@router.get("/check")
async def check() -> dict:
    """Return whether auth is enabled (i.e. an API key is configured)."""
    key = get_api_key()
    return {"auth_enabled": bool(key)}


@router.get("/config-warnings", dependencies=[Depends(require_auth)])
async def config_warnings() -> dict:
    """Return warnings about missing configuration.

    Protected by auth (callers must be logged in).
    """
    from app.config import settings
    from app.credentials import get_admin_phone_number

    warnings: list[str] = []
    if not settings.callme_fallback_number and not get_admin_phone_number():
        warnings.append(
            "No fallback phone number configured. Enter your mobile number in "
            "Setup → Phone Number, or set CALLME_FALLBACK_NUMBER in your .env."
        )
    if not settings.twilio_auth_token and not (settings.twilio_api_key_sid and settings.twilio_api_key_secret):
        warnings.append(
            "No Twilio auth credentials configured. Set TWILIO_API_KEY_SID + "
            "TWILIO_API_KEY_SECRET (or TWILIO_AUTH_TOKEN) to enable API calls "
            "and webhook signature validation."
        )
    return {"warnings": warnings}

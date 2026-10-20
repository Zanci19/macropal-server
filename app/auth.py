import logging
from functools import lru_cache
from typing import Annotated, Any

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

INVALID_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

AUTH_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Authentication is not configured on this server",
)


@lru_cache(maxsize=1)
def firebase_app() -> firebase_admin.App:
    if firebase_admin._apps:
        return firebase_admin.get_app()

    settings = get_settings()

    if settings.firebase_credentials_file:
        certificate = credentials.Certificate(settings.firebase_credentials_file)

        return firebase_admin.initialize_app(certificate)

    return firebase_admin.initialize_app()


def verify_token(
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if credential is None or not credential.credentials:
        raise INVALID_TOKEN

    try:
        app = firebase_app()
    except Exception:
        logger.exception("Firebase Admin could not be initialised")

        raise AUTH_UNAVAILABLE from None

    try:
        return firebase_auth.verify_id_token(
            credential.credentials,
            app=app,
            check_revoked=settings.firebase_check_revoked,
        )
    except firebase_auth.RevokedIdTokenError:
        logger.info("Rejected a revoked Firebase ID token")
        raise INVALID_TOKEN from None
    except firebase_auth.ExpiredIdTokenError:
        raise INVALID_TOKEN from None
    except (firebase_auth.InvalidIdTokenError, firebase_auth.UserDisabledError, ValueError):
        raise INVALID_TOKEN from None


def get_current_user(
    claims: Annotated[dict[str, Any], Depends(verify_token)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    firebase_uid = claims.get("uid") or claims.get("sub")

    if not firebase_uid:
        raise INVALID_TOKEN

    user = db.execute(
        select(User).where(User.firebase_uid == firebase_uid)
    ).scalar_one_or_none()

    if user is not None:
        return refresh_identity(db, user, claims)

    statement = (
        insert(User)
        .values(
            firebase_uid=firebase_uid,
            email=claims.get("email"),
            display_name=claims.get("name"),
        )
        .on_conflict_do_nothing(index_elements=[User.firebase_uid])
        .returning(User.id)
    )
    created_id = db.execute(statement).scalar_one_or_none()
    db.commit()

    if created_id is None:
        return db.execute(
            select(User).where(User.firebase_uid == firebase_uid)
        ).scalar_one()

    return db.get(User, created_id)


def refresh_identity(db: Session, user: User, claims: dict[str, Any]) -> User:
    email = claims.get("email")
    display_name = claims.get("name")
    changed = False

    if email and user.email != email:
        user.email = email
        changed = True

    if display_name and not user.display_name:
        user.display_name = display_name
        changed = True

    if changed:
        db.commit()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

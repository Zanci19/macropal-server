from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.auth import CurrentUser
from app.database import get_db
from app.models import Goal

router = APIRouter(prefix="/v1/me", tags=["me"])


@router.get("", response_model=schemas.UserOut, summary="Current user profile")
def get_me(user: CurrentUser) -> schemas.UserOut:
    return schemas.UserOut.model_validate(user)


@router.patch("", response_model=schemas.UserOut, summary="Update the current profile")
def update_me(
    payload: schemas.UserUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.UserOut:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken",
        ) from None

    db.refresh(user)

    return schemas.UserOut.model_validate(user)


@router.get("/goals", response_model=list[schemas.GoalOut], summary="Goal history")
def list_goals(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[schemas.GoalOut]:
    goals = db.execute(
        select(Goal)
        .where(Goal.user_id == user.id)
        .order_by(Goal.effective_from.desc(), Goal.id.desc())
    ).scalars().all()

    return [schemas.GoalOut.model_validate(goal) for goal in goals]


@router.post(
    "/goals",
    response_model=schemas.GoalOut,
    status_code=status.HTTP_201_CREATED,
    summary="Set new targets",
)
def create_goal(
    payload: schemas.GoalCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.GoalOut:
    effective_from = payload.effective_from or date.today()

    goal = db.execute(
        select(Goal).where(
            Goal.user_id == user.id,
            Goal.effective_from == effective_from,
        )
    ).scalar_one_or_none()

    values = payload.model_dump(exclude={"effective_from"}, exclude_unset=True)

    if goal is None:
        goal = Goal(user_id=user.id, effective_from=effective_from, **values)
        db.add(goal)
    else:
        for field, value in values.items():
            setattr(goal, field, value)

    for field in ("goal", "calorie_target", "protein_target", "carbs_target", "fat_target"):
        if field in values:
            setattr(user, field, values[field])

    db.commit()
    db.refresh(goal)

    return schemas.GoalOut.model_validate(goal)

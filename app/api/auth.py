from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, security
from app.database import get_db
from app.models import User
from app.schemas import ErrorResponse, RegisterRequest, RegisterResponse, UserResponse
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
    summary="Зарегистрировать пользователя и получить API-токен",
)
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> RegisterResponse:
    token = security.generate_token()
    try:
        user = await crud.create_user(db, payload.username, security.hash_token(token))
    except crud.UsernameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        ) from None
    return RegisterResponse(user_id=user.id, username=user.username, token=token)


@router.get("/me", response_model=UserResponse, summary="Текущий пользователь")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)

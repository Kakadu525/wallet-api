import uuid

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.database import get_db
from app.metrics import observe_operation
from app.models import User
from app.rate_limit import rate_limit
from app.schemas import (
    ErrorResponse,
    OperationRequest,
    OperationResponse,
    TransactionListResponse,
    TransactionResponse,
    WalletListResponse,
    WalletResponse,
)
from app.security import get_current_user

router = APIRouter(
    prefix="/api/v1/wallets",
    tags=["wallets"],
    dependencies=[Depends(rate_limit)],
)

AUTH_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
}
NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}


@router.post(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    responses=AUTH_ERRORS,
    summary="Создать новый кошелёк",
)
async def create_wallet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalletResponse:
    wallet = await crud.create_wallet(db, owner_id=current_user.id)
    return WalletResponse.model_validate(wallet)


@router.get(
    "",
    response_model=WalletListResponse,
    responses=AUTH_ERRORS,
    summary="Список своих кошельков",
)
async def list_wallets(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalletListResponse:
    wallets = await crud.list_wallets(
        db, owner_id=current_user.id, limit=limit, offset=offset
    )
    return WalletListResponse(
        items=[WalletResponse.model_validate(w) for w in wallets],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{wallet_id}/operation",
    response_model=OperationResponse,
    responses={
        **AUTH_ERRORS,
        **NOT_FOUND,
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
    summary="Изменить баланс кошелька (DEPOSIT / WITHDRAW)",
)
async def perform_operation(
    payload: OperationRequest,
    response: Response,
    wallet_id: uuid.UUID = Path(description="UUID кошелька"),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OperationResponse:
    try:
        tx, replayed = await crud.apply_operation(
            db,
            wallet_id,
            current_user.id,
            payload.operation_type,
            payload.amount,
            idempotency_key=idempotency_key,
        )
    except crud.WalletNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found"
        ) from None
    except crud.InsufficientFundsError as exc:
        observe_operation(payload.operation_type.value, "insufficient_funds")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    except crud.IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None

    observe_operation(payload.operation_type.value, "replay" if replayed else "success")
    response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    return OperationResponse(
        wallet_id=tx.wallet_id,
        balance=tx.balance_after,
        transaction_id=tx.id,
        type=payload.operation_type,
        amount=tx.amount,
        created_at=tx.created_at,
        replayed=replayed,
    )


@router.get(
    "/{wallet_id}",
    response_model=WalletResponse,
    responses={**AUTH_ERRORS, **NOT_FOUND},
    summary="Получить текущий баланс кошелька",
)
async def get_balance(
    wallet_id: uuid.UUID = Path(description="UUID кошелька"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalletResponse:
    try:
        wallet = await crud.get_owned_wallet(db, wallet_id, current_user.id)
    except crud.WalletNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found"
        ) from None
    return WalletResponse.model_validate(wallet)


@router.get(
    "/{wallet_id}/transactions",
    response_model=TransactionListResponse,
    responses={**AUTH_ERRORS, **NOT_FOUND},
    summary="Журнал операций кошелька",
)
async def list_wallet_transactions(
    wallet_id: uuid.UUID = Path(description="UUID кошелька"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionListResponse:
    try:
        await crud.get_owned_wallet(db, wallet_id, current_user.id)
    except crud.WalletNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found"
        ) from None

    txs = await crud.list_transactions(db, wallet_id, limit=limit, offset=offset)
    return TransactionListResponse(
        items=[TransactionResponse.model_validate(t) for t in txs],
        limit=limit,
        offset=offset,
    )

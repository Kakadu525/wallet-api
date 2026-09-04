import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User, Wallet
from app.schemas import OperationType


class WalletError(Exception):
    pass


class WalletNotFoundError(WalletError):
    pass


class InsufficientFundsError(WalletError):
    pass


class IdempotencyConflictError(WalletError):
    pass


class UsernameTakenError(Exception):
    pass


async def create_user(db: AsyncSession, username: str, token_hash: str) -> User:
    user = User(id=uuid.uuid4(), username=username, token_hash=token_hash)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise UsernameTakenError(username) from exc
    await db.refresh(user)
    return user


async def get_user_by_token_hash(db: AsyncSession, token_hash: str) -> User | None:
    result = await db.execute(select(User).where(User.token_hash == token_hash))
    return result.scalar_one_or_none()


async def create_wallet(db: AsyncSession, owner_id: uuid.UUID) -> Wallet:
    wallet = Wallet(id=uuid.uuid4(), owner_id=owner_id, balance=Decimal("0"))
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    return wallet


async def get_owned_wallet(
    db: AsyncSession, wallet_id: uuid.UUID, owner_id: uuid.UUID
) -> Wallet:
    wallet = await db.get(Wallet, wallet_id)
    if wallet is None or wallet.owner_id != owner_id:
        # Чужой кошелёк неотличим от несуществующего.
        raise WalletNotFoundError(str(wallet_id))
    return wallet


async def list_wallets(
    db: AsyncSession, owner_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> Sequence[Wallet]:
    result = await db.execute(
        select(Wallet)
        .where(Wallet.owner_id == owner_id)
        .order_by(Wallet.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def list_transactions(
    db: AsyncSession, wallet_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> Sequence[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.wallet_id == wallet_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def _find_transaction_by_key(
    db: AsyncSession, wallet_id: uuid.UUID, idempotency_key: str
) -> Transaction | None:
    result = await db.execute(
        select(Transaction).where(
            Transaction.wallet_id == wallet_id,
            Transaction.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def apply_operation(
    db: AsyncSession,
    wallet_id: uuid.UUID,
    owner_id: uuid.UUID,
    operation_type: OperationType,
    amount: Decimal,
    idempotency_key: str | None = None,
) -> tuple[Transaction, bool]:
    """
    Меняет баланс, пишет запись в журнал и обеспечивает идемпотентность.
    Возвращает (транзакция, replayed).

    Баланс и его запись в журнал меняются в одной транзакции БД. Само
    изменение — атомарный UPDATE ... WHERE balance >= amount RETURNING:
    новое значение считает БД по актуальной строке, а не приложение по
    своей копии, поэтому lost update невозможен, а списание не уходит
    в минус. Идемпотентность держится на UNIQUE(wallet_id, key): дубликат
    упирается в него, его транзакция откатывается целиком, дельта
    применяется один раз.
    """
    if idempotency_key is not None:
        existing = await _find_transaction_by_key(db, wallet_id, idempotency_key)
        if existing is not None:
            _ensure_same_operation(existing, operation_type, amount)
            return existing, True

    delta = amount if operation_type is OperationType.DEPOSIT else -amount

    stmt = (
        update(Wallet)
        .where(Wallet.id == wallet_id, Wallet.owner_id == owner_id)
        .values(balance=Wallet.balance + delta, updated_at=func.now())
        .returning(Wallet.balance)
    )
    if operation_type is OperationType.WITHDRAW:
        stmt = stmt.where(Wallet.balance >= amount)

    new_balance = await db.scalar(stmt)

    if new_balance is None:
        # Ноль строк: нет кошелька, чужой кошелёк или нехватка средств.
        await db.rollback()
        row = (
            await db.execute(
                select(Wallet.owner_id, Wallet.balance).where(Wallet.id == wallet_id)
            )
        ).first()
        if row is None or row.owner_id != owner_id:
            raise WalletNotFoundError(str(wallet_id))
        raise InsufficientFundsError(
            f"Insufficient funds: balance={row.balance}, requested={amount}"
        )

    tx = Transaction(
        id=uuid.uuid4(),
        wallet_id=wallet_id,
        type=operation_type.value,
        amount=amount,
        balance_after=new_balance,
        idempotency_key=idempotency_key,
    )
    db.add(tx)

    try:
        await db.commit()
    except IntegrityError:
        # Конкурентный дубликат по ключу: наш UPDATE откатился вместе с
        # INSERT, возвращаем результат выигравшего запроса.
        await db.rollback()
        if idempotency_key is not None:
            existing = await _find_transaction_by_key(db, wallet_id, idempotency_key)
            if existing is not None:
                _ensure_same_operation(existing, operation_type, amount)
                return existing, True
        raise

    await db.refresh(tx)
    return tx, False


def _ensure_same_operation(
    existing: Transaction, operation_type: OperationType, amount: Decimal
) -> None:
    if existing.type != operation_type.value or existing.amount != amount:
        raise IdempotencyConflictError(
            "Idempotency key already used for a different operation"
        )

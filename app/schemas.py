import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class OperationType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    token: str = Field(description="API-токен, показывается один раз")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: uuid.UUID = Field(validation_alias=AliasChoices("user_id", "id"))
    username: str
    created_at: datetime | None = None


class OperationRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"operation_type": "DEPOSIT", "amount": "1000.00"}]
        }
    )

    operation_type: OperationType
    # decimal_places=2 отсекает суммы вроде 0.001 (иначе округлились бы в 0).
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class OperationResponse(BaseModel):
    wallet_id: uuid.UUID
    balance: Decimal
    transaction_id: uuid.UUID
    type: OperationType
    amount: Decimal
    created_at: datetime | None = None
    replayed: bool = False


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    wallet_id: uuid.UUID = Field(validation_alias=AliasChoices("wallet_id", "id"))
    balance: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WalletListResponse(BaseModel):
    items: list[WalletResponse]
    limit: int
    offset: int


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    transaction_id: uuid.UUID = Field(
        validation_alias=AliasChoices("transaction_id", "id")
    )
    wallet_id: uuid.UUID
    type: OperationType
    amount: Decimal
    balance_after: Decimal
    idempotency_key: str | None = None
    created_at: datetime | None = None


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str

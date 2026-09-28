from decimal import Decimal

from pydantic import BaseModel, Field


class BalanceResponse(BaseModel):
    account_id: str
    user_id: str
    balance: Decimal
    kyc_verified: bool

    model_config = {"from_attributes": True}


class TransferRequest(BaseModel):
    # to_user_id is the IAM UUID of the recipient — the wallet service resolves
    # this to an account_id internally. Clients know IAM user IDs (from the login
    # response), not internal account IDs.
    to_user_id: str
    # gt=0 enforced by Pydantic before the handler runs — rejects zero/negative
    # amounts at the schema layer, before any DB call.
    amount: Decimal = Field(gt=0)
    description: str = ""


class TransferResponse(BaseModel):
    sender_account_id: str
    receiver_account_id: str
    amount: Decimal
    description: str
    status: str = "completed"

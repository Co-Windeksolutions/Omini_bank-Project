from datetime import datetime

from pydantic import BaseModel, EmailStr


# --- Request bodies ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ValidateRequest(BaseModel):
    token: str


# --- Response bodies ---

class RegisterResponse(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ValidateResponse(BaseModel):
    valid: bool
    user_id: str | None = None
    email: str | None = None
    role: str | None = None

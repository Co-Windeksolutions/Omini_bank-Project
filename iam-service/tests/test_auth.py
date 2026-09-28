"""
Unit tests for auth.py — password hashing and JWT utilities.

These are pure-function tests: no database, no HTTP, no mocking required.
auth.py has zero I/O dependencies — every function takes plain values and
returns plain values. pytest runs these in milliseconds with no setup.
"""
import time

import pytest

# auth.py reads settings at import time using config.py defaults — no .env needed.
from auth import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        """The stored hash must never equal the original password."""
        hashed = hash_password("hunter2")
        assert hashed != "hunter2"

    def test_correct_password_verifies(self):
        """A correct password must verify against its hash."""
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_wrong_password_does_not_verify(self):
        """A wrong password must not verify against a different password's hash."""
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_each_hash_is_unique(self):
        """bcrypt embeds a random salt — hashing the same password twice must
        produce two different hashes, both of which verify correctly."""
        hashed_a = hash_password("same-password")
        hashed_b = hash_password("same-password")
        assert hashed_a != hashed_b
        assert verify_password("same-password", hashed_a) is True
        assert verify_password("same-password", hashed_b) is True


# ---------------------------------------------------------------------------
# JWT creation and decoding
# ---------------------------------------------------------------------------

class TestJWT:
    USER_ID = "test-uuid-1234"
    EMAIL = "test@example.com"
    ROLE = "user"

    def test_valid_token_decodes(self):
        """A freshly created token must decode to the correct claims."""
        token = create_token(self.USER_ID, self.EMAIL, self.ROLE)
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == self.USER_ID
        assert payload["email"] == self.EMAIL
        assert payload["role"] == self.ROLE

    def test_token_contains_exp_and_iat(self):
        """Tokens must carry expiry and issued-at claims for audit and K8s probe
        correctness."""
        token = create_token(self.USER_ID, self.EMAIL, self.ROLE)
        payload = decode_token(token)

        assert "exp" in payload
        assert "iat" in payload
        assert payload["exp"] > payload["iat"]

    def test_expired_token_returns_none(self):
        """decode_token must return None (not raise) for an expired token.
        We force expiry by manipulating jwt directly with a past exp claim."""
        import jwt as pyjwt
        from config import settings
        from datetime import datetime, timedelta, timezone

        past_payload = {
            "sub": self.USER_ID,
            "email": self.EMAIL,
            "role": self.ROLE,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "iat": datetime.now(timezone.utc) - timedelta(minutes=61),
        }
        expired_token = pyjwt.encode(
            past_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        result = decode_token(expired_token)
        assert result is None

    def test_tampered_token_returns_none(self):
        """decode_token must return None for a token whose signature has been
        invalidated by modifying the payload."""
        token = create_token(self.USER_ID, self.EMAIL, self.ROLE)

        # Corrupt the FIRST character of the signature segment.
        # HS256 produces a 32-byte (256-bit) HMAC encoded as 43 base64url chars.
        # The very last character only encodes 2 meaningful bits — the other 4
        # are ignored padding, so flipping it can leave the decoded bytes unchanged
        # and PyJWT still accepts the token. The first character always encodes 6
        # full bits of the actual HMAC, so changing it reliably invalidates the
        # signature regardless of what value it happens to hold.
        header, payload, signature = token.split(".")
        bad_first_char = "B" if signature[0] != "B" else "C"
        bad_signature = bad_first_char + signature[1:]
        tampered = f"{header}.{payload}.{bad_signature}"

        result = decode_token(tampered)
        assert result is None

    def test_garbage_string_returns_none(self):
        """decode_token must return None for a completely malformed input,
        not raise an unhandled exception."""
        result = decode_token("this.is.not.a.jwt")
        assert result is None

    def test_empty_string_returns_none(self):
        """Edge case: empty string must not raise."""
        result = decode_token("")
        assert result is None

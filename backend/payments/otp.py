"""One-time-code primitives. The plaintext code exists only in memory between generation and the
e-mail hand-off: it is never stored, logged, or returned by an API."""
import hashlib
import hmac
import secrets

from django.conf import settings


def generate_code() -> str:
    """Cryptographically secure, zero-padded numeric code (secrets uses the OS CSPRNG)."""
    return str(secrets.randbelow(10 ** settings.OTP_LENGTH)).zfill(settings.OTP_LENGTH)


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_code(code: str, salt: str, transaction_pk: int, user_pk: int) -> str:
    """Keyed hash bound to the transaction and the user, so a code cannot be replayed against another
    transaction or account. (A 6-digit space is brute-forceable by anyone who holds both the database
    and SECRET_KEY, which is why attempts are limited and codes are short-lived.)"""
    message = f'{salt}|{transaction_pk}|{user_pk}|{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def matches(code: str, stored_hash: str, salt: str, transaction_pk: int, user_pk: int) -> bool:
    return hmac.compare_digest(hash_code(code, salt, transaction_pk, user_pk), stored_hash)

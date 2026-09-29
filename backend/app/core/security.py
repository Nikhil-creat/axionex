"""HMAC-SHA256 webhook verification with replay protection."""
import hashlib
import hmac
import time

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


async def verify_webhook(
    request: Request,
    x_signature: str = Header(..., alias="X-Signature"),
    x_timestamp: str = Header(..., alias="X-Timestamp"),
) -> bytes:
    body = await request.body()
    try:
        drift = abs(time.time() - float(x_timestamp))
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Timestamp")
    if drift > settings.webhook_tolerance_seconds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Stale webhook timestamp")
    if not hmac.compare_digest(sign(settings.webhook_secret, x_timestamp, body), x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    return body

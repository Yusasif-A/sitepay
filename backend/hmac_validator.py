import hashlib
import hmac
import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger("whatsapp.hmac_validator")


async def validate_whatsapp_hmac(request: Request) -> None:
    """Validate the x-hub-signature-256 header from Meta using the App Secret.

    Meta signs webhook payloads with the Facebook App Secret (not the access token).
    Set WHATSAPP_APP_SECRET to the value shown in your Meta App Dashboard → App Settings → Basic.

    If WHATSAPP_APP_SECRET is not set, validation is skipped with a warning.
    """
    app_secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not app_secret:
        logger.warning(
            "WHATSAPP_APP_SECRET not set — skipping HMAC validation. "
            "Set this to your Meta App Secret to secure the webhook endpoint."
        )
        return

    sig = request.headers.get("x-hub-signature-256", "")
    body = await request.body()  # Starlette caches this — request.json() still works after
    expected = "sha256=" + hmac.new(
        app_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail="Invalid signature")

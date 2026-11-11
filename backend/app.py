"""
SitePay API server: WhatsApp webhook + supervisor dashboard API.

    uvicorn app:app --reload --port 5001
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("sitepay")

import bot
import config
import payruns
import whatsapp
from db import get_db
from hmac_validator import validate_whatsapp_hmac
from routers.api import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(get_db)
    logger.info("=" * 50)
    logger.info("🏗️  SitePay ready")
    logger.info(f"   PayPal: {'SIMULATED (no credentials)' if payruns.simulate_mode() else config.PAYPAL_ENV}")
    logger.info(f"   AI:     {'on (' + config.LLM_MODEL + ')' if config.AI_ENABLED else 'off'}")
    logger.info(f"   WhatsApp: {'live' if whatsapp.configured() else 'simulator only'}")
    logger.info("=" * 50)
    yield


app = FastAPI(title="SitePay", lifespan=lifespan)


@app.middleware("http")
async def errors_as_json(request: Request, call_next):
    """Unhandled errors become JSON 500s inside the CORS layer, so the
    dashboard shows the real error instead of a misleading CORS failure."""
    try:
        return await call_next(request)
    except Exception:
        logger.exception(f"Unhandled error on {request.method} {request.url.path}")
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(api_router)


# ── WhatsApp webhook ─────────────────────────────────────────────────────────

_tasks = set()


@app.api_route("/whatsapp", methods=["GET", "POST"])
async def whatsapp_webhook(request: Request) -> Response:
    if request.method == "GET":
        params = request.query_params
        if config.WHATSAPP_VERIFY_TOKEN and params.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN:
            return Response(content=params.get("hub.challenge"), status_code=200)
        return Response(content="Verification token mismatch", status_code=403)

    await validate_whatsapp_hmac(request)
    try:
        data = await request.json()
        value = data["entry"][0]["changes"][0]["value"]
    except Exception:
        return Response(status_code=200)

    for message in value.get("messages", []):
        task = asyncio.create_task(_process(message))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    # Ack immediately; Meta retries anything slower than a few seconds.
    return Response(status_code=200)


async def _process(message: dict) -> None:
    phone = message.get("from", "")
    reply = whatsapp.Replier(phone, simulated=False)
    kind = message.get("type")
    try:
        await whatsapp.mark_read(message.get("id"))
        if kind == "text":
            text = message["text"]["body"]
            whatsapp.log_inbound(phone, text)
            await bot.handle(phone, reply, text=text)
        elif kind == "interactive":
            button = (message["interactive"].get("button_reply") or {})
            whatsapp.log_inbound(phone, button.get("title", ""))
            await bot.handle(phone, reply, button_id=button.get("id", ""))
        elif kind == "image":
            image = await whatsapp.download_media(message["image"]["id"])
            await bot.handle(phone, reply, text=message["image"].get("caption", ""), image_bytes=image)
        elif kind == "location":
            loc = message["location"]
            whatsapp.log_inbound(phone, "[location]")
            await bot.handle(phone, reply, location={"lat": loc.get("latitude"), "lon": loc.get("longitude")})
        else:
            # Voice notes, stickers, video, documents: not used by SitePay.
            whatsapp.log_inbound(phone, f"[{kind}]")
            await reply.text("I can read text, photos, location and button taps. "
                             "Please send a photo of your work or tap a button.")
    except Exception:
        logger.exception(f"Failed to handle {kind} from {phone}")
        try:
            await reply.text("Something went wrong on my side. Please send that again.")
        except Exception:
            pass


@app.get("/")
async def root():
    return {"service": "SitePay", "status": "running"}


@app.get("/health")
async def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

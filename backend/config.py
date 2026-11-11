"""
SitePay configuration — every setting comes from the environment (.env).
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


# ── Database ─────────────────────────────────────────────────────────────────
# Use "mongomock://" for a throwaway in-memory database while developing
# (needs `pip install mongomock`; everything is lost on restart).
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "sitepay")

# ── WhatsApp Cloud API ───────────────────────────────────────────────────────
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v20.0")
# WhatsApp only allows free-form messages within 24h of the worker's last
# message. A pay note sent later needs an approved template. If you create one
# (one body variable {{1}} = the pay note text), name it here.
WHATSAPP_PAYNOTE_TEMPLATE = os.getenv("WHATSAPP_PAYNOTE_TEMPLATE", "")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en")

# Phone numbers typed on the dashboard as 0801... are rewritten to this
# country code so they match the international form WhatsApp sends.
DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "234")

# ── AI (any OpenAI-compatible endpoint whose model accepts images) ──────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "") or LLM_MODEL
AI_ENABLED = bool(LLM_BASE_URL and LLM_MODEL)

# ── PayPal ───────────────────────────────────────────────────────────────────
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "sandbox").strip().lower()  # sandbox | live
PAYPAL_BASE_URL = (
    "https://api-m.paypal.com" if PAYPAL_ENV == "live" else "https://api-m.sandbox.paypal.com"
)

# Wages are kept in the site's local currency (e.g. NGN). PayPal does not pay
# out in every currency (NGN is not supported), so each payout converts at
# PAYOUT_FX_RATE local units per 1 PAYOUT_CURRENCY unit. The rate used is
# stored on every pay run so the conversion is always auditable.
WAGE_CURRENCY = os.getenv("WAGE_CURRENCY", "NGN")
PAYOUT_CURRENCY = os.getenv("PAYOUT_CURRENCY", "USD")
PAYOUT_FX_RATE = float(os.getenv("PAYOUT_FX_RATE", "1500"))

# ── Time ─────────────────────────────────────────────────────────────────────
SITE_TIMEZONE = os.getenv("SITE_TIMEZONE", "Africa/Lagos")

# ── Auth ─────────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

PORT = int(os.getenv("PORT", "5001"))

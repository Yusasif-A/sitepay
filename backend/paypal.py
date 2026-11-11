"""
PayPal REST client: OAuth client-credentials token + Payouts API.

Docs:  https://developer.paypal.com/api/rest  (auth)
       https://developer.paypal.com/api/payouts/standard
Spec:  github.com/paypal/paypal-rest-api-specifications → payments_payouts_batch_v1

    POST /v1/oauth2/token                      client_credentials grant
    POST /v1/payments/payouts                  create a batch (one item per worker)
    GET  /v1/payments/payouts/{batch_id}       batch + per-item status

Idempotency: PayPal rejects a sender_batch_id reused within 30 days, and
stores PayPal-Request-Id keys for 30 days. We send the pay-run id as both, so
a retried "Pay now" (double click, timeout, 5xx) can never pay a crew twice.
"""

import logging
import time
from typing import List, Optional

import httpx

import config

logger = logging.getLogger(__name__)

# Batch statuses PayPal reports (batch_enum) and which of them are final.
BATCH_FINAL = {"SUCCESS", "DENIED", "CANCELED"}
# Item statuses (transaction_enum) that mean money has left the account.
ITEM_PAID = {"SUCCESS"}
# UNCLAIMED: the receiver has no PayPal account yet; PayPal holds the money
# for 30 days, then returns it. Treated as "sent, awaiting claim".
ITEM_FINAL_FAILED = {"FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED"}


class PayPalError(Exception):
    def __init__(self, message: str, status: int = 0, details: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


class PayPalClient:
    def __init__(self, client_id: str = "", client_secret: str = "", base_url: str = "",
                 transport: Optional[httpx.BaseTransport] = None):
        self.client_id = client_id or config.PAYPAL_CLIENT_ID
        self.client_secret = client_secret or config.PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or config.PAYPAL_BASE_URL).rstrip("/")
        self._transport = transport  # injected in tests
        self._token: Optional[str] = None
        self._token_expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=30.0, transport=self._transport)

    # ── Auth ─────────────────────────────────────────────────────────────────

    def access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if not self.configured:
            raise PayPalError("PayPal is not configured: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET")
        with self._client() as client:
            resp = client.post(
                "/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise PayPalError(f"PayPal auth failed ({resp.status_code}). Check the client ID/secret "
                              f"and PAYPAL_ENV.", resp.status_code, _safe_json(resp))
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + int(body.get("expires_in", 3000))
        return self._token

    def _headers(self, request_id: str = "") -> dict:
        headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        return headers

    # ── Payouts ──────────────────────────────────────────────────────────────

    def create_payout(self, sender_batch_id: str, items: List[dict], email_subject: str,
                      email_message: str = "") -> dict:
        """items: [{receiver, recipient_type, amount, currency, note, sender_item_id}]"""
        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": email_subject[:255],
                "email_message": (email_message or email_subject)[:1000],
            },
            "items": [
                {
                    "recipient_type": item.get("recipient_type", "EMAIL"),
                    "amount": {"value": item["amount"], "currency": item["currency"]},
                    "receiver": item["receiver"],
                    "note": item.get("note", "")[:4000],
                    "sender_item_id": item["sender_item_id"][:63],
                    "purpose": "SERVICES",
                }
                for item in items
            ],
        }
        with self._client() as client:
            resp = client.post("/v1/payments/payouts", json=body, headers=self._headers(sender_batch_id))
        if resp.status_code not in (200, 201):
            details = _safe_json(resp)
            raise PayPalError(_error_message(details, resp.status_code), resp.status_code, details)
        return resp.json()

    def get_payout(self, payout_batch_id: str) -> dict:
        with self._client() as client:
            resp = client.get(f"/v1/payments/payouts/{payout_batch_id}",
                              params={"page_size": 1000}, headers=self._headers())
        if resp.status_code != 200:
            details = _safe_json(resp)
            raise PayPalError(_error_message(details, resp.status_code), resp.status_code, details)
        return resp.json()


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:500]}


def _error_message(details: dict, status: int) -> str:
    name = details.get("name", "")
    message = details.get("message", "") or details.get("raw", "")
    if name == "INSUFFICIENT_FUNDS":
        return "The PayPal business account doesn't have enough balance for this payout."
    if name == "DUPLICATE_REQUEST_ID" or "sender_batch_id" in message.lower():
        return "PayPal already received this pay run (duplicate batch id); refresh its status instead."
    return f"PayPal rejected the payout ({status}{': ' + name if name else ''}). {message}".strip()


_default: Optional[PayPalClient] = None


def get_client() -> PayPalClient:
    global _default
    if _default is None:
        _default = PayPalClient()
    return _default


def set_client(client: Optional[PayPalClient]) -> None:
    """Swap the shared client (tests)."""
    global _default
    _default = client

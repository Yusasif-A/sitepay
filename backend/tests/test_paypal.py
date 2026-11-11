import json

import httpx
import pytest

from paypal import PayPalClient, PayPalError


def make_client(handler):
    return PayPalClient("cid", "secret", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))


def test_token_then_payout_body_matches_spec():
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "T", "expires_in": 32400})
        if request.url.path == "/v1/payments/payouts":
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}})
        raise AssertionError(request.url)

    client = make_client(handler)
    out = client.create_payout("RUN-1", [{"receiver": "a@x.com", "amount": "10.00", "currency": "USD",
                                          "note": "Site X", "sender_item_id": "RUN-1-W1"}], "Paid")
    assert out["batch_header"]["payout_batch_id"] == "B1"
    assert seen["headers"]["paypal-request-id"] == "RUN-1"
    assert seen["headers"]["authorization"] == "Bearer T"
    body = seen["body"]
    assert body["sender_batch_header"]["sender_batch_id"] == "RUN-1"
    item = body["items"][0]
    assert item == {"recipient_type": "EMAIL", "amount": {"value": "10.00", "currency": "USD"},
                    "receiver": "a@x.com", "note": "Site X", "sender_item_id": "RUN-1-W1", "purpose": "SERVICES"}


def test_token_cached():
    calls = {"token": 0}

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "T", "expires_in": 32400})
        return httpx.Response(200, json={"batch_header": {"batch_status": "SUCCESS"}, "items": []})

    c = make_client(handler)
    c.get_payout("B1")
    c.get_payout("B1")
    assert calls["token"] == 1


def test_errors_are_readable():
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 32400})
        return httpx.Response(422, json={"name": "INSUFFICIENT_FUNDS", "message": "x"})

    with pytest.raises(PayPalError) as e:
        make_client(handler).create_payout("R", [{"receiver": "a@x.com", "amount": "1.00", "currency": "USD",
                                                  "sender_item_id": "i"}], "s")
    assert "enough balance" in str(e.value)


def test_bad_credentials():
    c = make_client(lambda r: httpx.Response(401, json={"error": "invalid_client"}))
    with pytest.raises(PayPalError) as e:
        c.access_token()
    assert "auth failed" in str(e.value)

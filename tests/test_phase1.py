import importlib
import os
from decimal import Decimal
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_API_TOKEN"] = "phase1-test-secret"
os.environ["CASHFREE_ENV"] = "sandbox"
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)
headers = {"Authorization": "Bearer phase1-test-secret"}

def test_initial_status_and_shop_approval():
    assert client.get("/health").status_code == 200
    response = client.post("/api/shop-applications", json={
        "name": "Demo Print Shop", "slug": "demo-shop-test",
        "email": "demo@example.com", "phone": "9876543210"
    })
    assert response.status_code == 201
    shop_id = response.json()["application_id"]
    assert client.get("/api/admin/shops").status_code == 401
    assert client.post(f"/api/admin/shops/{shop_id}/approve", headers=headers).status_code == 200
    assert not client.get("/api/shops").json()  # No unpaid shop activation.
    return shop_id

def test_checkout_and_verified_activation(monkeypatch):
    shop_id = test_initial_status_and_shop_approval()
    monkeypatch.setattr(main, "APP_ID", "sandbox-app-id")
    monkeypatch.setattr(main, "SECRET", "sandbox-secret")
    state = {}
    async def fake_cashfree(method, url, **kwargs):
        if method == "POST":
            state["order"] = kwargs["json"]
            return {"payment_session_id": "sandbox-session"}
        return {"order_id": state["order"]["order_id"],
                "order_currency": "INR", "order_amount": state["order"]["order_amount"],
                "order_status": "PAID"}
    monkeypatch.setattr(main, "cf_call", fake_cashfree)
    resp = client.post("/api/admin/licenses/checkout", headers=headers, json={
        "shop_id": shop_id, "plan": "professional", "billing_cycle": "monthly"})
    assert resp.status_code == 200, resp.text
    order_id = resp.json()["order_id"]
    assert state["order"]["order_amount"] == 499
    first = client.get("/api/admin/licenses/" + order_id, headers=headers)
    assert first.status_code == 200 and first.json()["status"] == "paid"
    license1 = client.get("/api/admin/shops/" + shop_id + "/license", headers=headers).json()
    second = client.get("/api/admin/licenses/" + order_id, headers=headers)
    assert second.status_code == 200
    license2 = client.get("/api/admin/shops/" + shop_id + "/license", headers=headers).json()
    assert license1["valid_until"] == license2["valid_until"]  # No double extension.
    assert client.get("/api/shops").json()[0]["id"] == shop_id

def test_untrusted_webhook_cannot_activate(monkeypatch):
    monkeypatch.setattr(main, "SECRET", "sandbox-secret")
    payload = {"data": {"order": {"order_id": "rl_" + "a"*32}}}
    response = client.post("/api/webhooks/cashfree/license", json=payload,
        headers={"x-webhook-timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                 "x-webhook-signature": "bad"})
    assert response.status_code == 401

"""Phase 2 tenant isolation, account, brand, QR, order and printer licensing checks."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_API_TOKEN"] = "phase1-test-secret"
os.environ["CASHFREE_ENV"] = "sandbox"

from fastapi.testclient import TestClient
from sqlalchemy import select
import main
from enterprise import ShopOwner, ShopAppearance, PrintOrder, RegisteredDevice

client = TestClient(main.app)
ADMIN = {"Authorization": "Bearer phase1-test-secret"}


def create_shop(n):
    slug = "pilot-" + n + "-" + uuid4().hex[:8]
    r = client.post("/api/shop-applications", json={"name": "Pilot Print " + n, "slug": slug,
             "email": n + "@example.com", "phone": "9876543210"})
    assert r.status_code == 201, r.text
    sid = r.json()["application_id"]
    assert client.post("/api/admin/shops/" + sid + "/approve", headers=ADMIN).status_code == 200
    with main.SessionLocal() as db:
        db.add(main.License(shop_id=sid, plan="starter",
                            valid_until=datetime.now(timezone.utc)+timedelta(days=30),
                            last_invoice_id="test-" + sid))
        db.get(main.Shop, sid).status = "active"
        db.commit()
    return sid, slug


def owner_login(shop_id, slug, email):
    invited = client.post("/api/v2/admin/shops/" + shop_id + "/owner-invite", headers=ADMIN)
    assert invited.status_code == 200, invited.text
    invitation = invited.json()["invitation"]
    password = "ThisIsASecureTestPass123!"
    result = client.post("/api/v2/auth/register", json={"invitation": invitation, "password": password})
    assert result.status_code == 200, result.text
    assert client.post("/api/v2/auth/register", json={"invitation": invitation, "password": password}).status_code == 400
    login = client.post("/api/v2/auth/login", json={"shop_slug": slug, "email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def test_tenant_isolation_branding_marketplace_and_tracking():
    s1, slug1 = create_shop("alpha")
    s2, slug2 = create_shop("beta")
    a1 = owner_login(s1, slug1, "alpha@example.com")
    a2 = owner_login(s2, slug2, "beta@example.com")
    assert client.get("/api/v2/owner/me", headers=a1).json()["shop_id"] == s1
    assert client.get("/api/v2/owner/me", headers=a2).json()["shop_id"] == s2
    response = client.put("/api/v2/owner/appearance", headers=a1, json={
        "headline": "Alpha premium printing", "description": "Fast alpha",
        "primary_color": "#123456", "accent_color": "#eac46f",
        "city": "Kareli", "public_listing": True
    })
    assert response.status_code == 200, response.text
    assert client.get("/api/v2/shops/"+slug1).json()["headline"] == "Alpha premium printing"
    assert client.get("/api/v2/shops/"+slug2).json()["headline"] != "Alpha premium printing"
    assert client.get("/api/v2/shops/"+slug1+"/qr.png").headers["content-type"] == "image/png"
    assert any(shop["slug"] == slug1 for shop in client.get("/api/v2/marketplace?city=Kareli").json()["shops"])
    order = client.post("/api/v2/shops/"+slug1+"/orders", json={"customer_name":"Patron","pages":2,"copies":1,"color_mode":"bw"})
    assert order.status_code == 201, order.text
    data = order.json()
    assert data["document_upload"] == "not_enabled"
    oid = data["order_id"]
    # Beta owner cannot access or update Alpha orders.
    assert all(x["id"] != oid for x in client.get("/api/v2/owner/orders", headers=a2).json())
    assert client.patch("/api/v2/owner/orders/"+oid, headers=a2, json={"status":"printing"}).status_code == 404
    assert client.patch("/api/v2/owner/orders/"+oid, headers=a1, json={"status":"printing"}).status_code == 200
    assert client.get("/api/v2/shops/"+slug2+"/orders/"+oid+"?tracking_token="+data["tracking_token"]).status_code == 404
    assert client.get("/api/v2/shops/"+slug1+"/orders/"+oid+"?tracking_token=wrong").status_code == 404
    assert client.get("/api/v2/shops/"+slug1+"/orders/"+oid+"?tracking_token="+data["tracking_token"]).json()["status"] == "printing"
    # Domain request is private; actual verified DNS and TLS are separate stages.
    dom = client.post("/api/v2/owner/domains", headers=a1, json={"hostname":"pilot-example.org"})
    assert dom.status_code == 200, dom.text
    assert dom.json()["verified"] is False
    assert dom.json()["txt_value"].startswith("raj-verification=")
    pref = client.put("/api/v2/owner/billing/preference", headers=a1,
            json={"renewal_mode":"request_recurring"})
    assert pref.status_code == 200
    assert pref.json()["mandate_status"] == "not_configured"


def test_device_quota_and_revoke():
    sid, slug = create_shop("gamma")
    auth = owner_login(sid, slug, "gamma@example.com")
    enroll = client.post("/api/v2/owner/devices/enrollment", headers=auth)
    assert enroll.status_code == 200
    invite = enroll.json()["enrollment_code"]
    reg = client.post("/api/v2/devices/enroll", json={"invitation": invite, "display_name":"Desk Printer"})
    assert reg.status_code == 200, reg.text
    token = {"Authorization":"Bearer "+reg.json()["device_token"]}
    assert client.get("/api/v2/devices/me", headers=token).status_code == 200
    assert client.get("/api/v2/devices/queue", headers=token).json()["jobs"] == []
    assert client.post("/api/v2/devices/enroll", json={"invitation":invite, "display_name":"Another"}).status_code == 401
    assert client.post("/api/v2/owner/devices/enrollment", headers=auth).status_code == 409
    did = reg.json()["device_id"]
    assert client.post("/api/v2/owner/devices/"+did+"/revoke", headers=auth).status_code == 200
    assert client.get("/api/v2/devices/me", headers=token).status_code == 403

"""Compatibility tests: existing printing paths must remain untouched."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from same_site_gateway import build_gateway, check_legacy_route_conflicts, load_gateway_from_environment


def fake_apps():
    old_print = FastAPI()

    @old_print.get("/")
    def old_home():
        return {"source": "original-printing", "page": "home"}

    @old_print.post("/api/upload")
    def old_upload():
        return {"source": "original-printing", "uploaded": True}

    @old_print.post("/api/webhooks/cashfree")
    def old_payment():
        return {"source": "original-printing", "payment": "untouched"}

    cloud = FastAPI()

    @cloud.get("/")
    def cloud_home():
        return {"source": "enterprise", "page": "home"}

    @cloud.get("/health")
    def cloud_health():
        return {"healthy": True}

    @cloud.post("/api/webhooks/cashfree/license")
    def cloud_license_webhook():
        return {"source": "enterprise", "purpose": "license"}

    return old_print, cloud


def test_live_printing_routes_are_preserved():
    old_print, cloud = fake_apps()
    client = TestClient(build_gateway(old_print, cloud))
    assert client.get("/").json()["source"] == "original-printing"
    assert client.post("/api/upload").json() == {"source": "original-printing", "uploaded": True}
    assert client.post("/api/webhooks/cashfree").json()["source"] == "original-printing"
    assert client.get("/enterprise/").json()["source"] == "enterprise"
    assert client.get("/enterprise/health").json() == {"healthy": True}
    assert client.post("/enterprise/api/webhooks/cashfree/license").json() == {
        "source": "enterprise", "purpose": "license"
    }


def test_conflicts_are_refused():
    old_print, cloud = fake_apps()

    @old_print.get("/enterprise/admin")
    def collision():
        return {"not": "safe"}

    with pytest.raises(ValueError, match="reserved"):
        check_legacy_route_conflicts(old_print)
    with pytest.raises(ValueError, match="reserved"):
        build_gateway(old_print, cloud)
    with pytest.raises(ValueError, match="different"):
        build_gateway(old_print, old_print)


def test_gateway_requires_original_application(monkeypatch):
    monkeypatch.delenv("RAJ_LEGACY_ASGI", raising=False)
    with pytest.raises(RuntimeError, match="ORIGINAL PRINTING APPLICATION"):
        load_gateway_from_environment()


def test_enterprise_site_uses_prefix_aware_urls():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "static"
    for name in ("index.html", "shop.html", "owner.html", "marketplace.html"):
        html = (root / name).read_text(encoding="utf-8")
        assert "const RAJ_URL" in html
        assert "fetch(RAJ_URL(" in html or "fetch(RAJ_URL(path)" in html

"""RAJ Enterprise Cloud — Phase 1 multi-shop + Cashfree licence billing starter.
This is a staging scaffold, not a finished production-ready printing platform.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()
APP_ID = os.getenv("CASHFREE_APP_ID", "")
SECRET = os.getenv("CASHFREE_SECRET_KEY", "")
CF_ENV = os.getenv("CASHFREE_ENV", "sandbox").lower()
CF_VERSION = os.getenv("CASHFREE_API_VERSION", "2025-01-01")
BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./raj_enterprise_dev.db")
if CF_ENV not in ("sandbox", "production"):
    raise RuntimeError("CASHFREE_ENV must be sandbox or production")
CF_BASE = "https://sandbox.cashfree.com/pg" if CF_ENV == "sandbox" else "https://api.cashfree.com/pg"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(90), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(25), default="pending", nullable=False)
    theme: Mapped[str] = mapped_column(String(20), default="navy", nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

class Invoice(Base):
    __tablename__ = "license_invoices"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(30), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class License(Base):
    __tablename__ = "shop_licenses"
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_invoice_id: Mapped[str] = mapped_column(String(80), nullable=False)

Base.metadata.create_all(bind=engine)
app = FastAPI(title="RAJ Enterprise Cloud Pro - Phase 1", version="0.1.0")
# These are PROPOSED prices, not production commercial offers.
PLANS = {"starter": {"monthly": 199, "yearly": 1990, "printers": 1},
         "professional": {"monthly": 499, "yearly": 4990, "printers": 3},
         "business": {"monthly": 999, "yearly": 9990, "printers": 5}}

def db_session():
    with SessionLocal() as db:
        yield db

def require_admin(authorization: str | None = Header(default=None)):
    if not ADMIN_TOKEN or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Admin authentication required")
    if not secrets.compare_digest(authorization.removeprefix("Bearer "), ADMIN_TOKEN):
        raise HTTPException(403, "Access denied")
    return True

class Application(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=5, max_length=200)
    phone: str = Field(pattern=r"^[6-9][0-9]{9}$")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")

class Checkout(BaseModel):
    shop_id: str
    plan: str
    billing_cycle: str = "monthly"

@app.get("/")
def homepage():
    return FileResponse(Path(__file__).parent / "static" / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "service": "raj-enterprise", "payment_environment": CF_ENV}

@app.get("/api/plans")
def plans():
    return PLANS

@app.get("/api/shops")
def public_shops(db: Session = Depends(db_session)):
    shops = db.scalars(select(Shop).where(Shop.status == "active")).all()
    return [{"id": s.id, "name": s.name, "slug": s.slug, "theme": s.theme} for s in shops]

@app.post("/api/shop-applications", status_code=201)
def apply_shop(body: Application, db: Session = Depends(db_session)):
    if db.scalar(select(Shop).where(Shop.slug == body.slug)):
        raise HTTPException(409, "Shop URL is already reserved")
    shop = Shop(id=str(uuid4()), name=body.name.strip(), slug=body.slug,
                email=body.email.strip(), phone=body.phone, status="pending")
    db.add(shop)
    db.commit()
    return {"application_id": shop.id, "status": "pending", "message": "Application submitted for review"}

@app.get("/api/admin/shops", dependencies=[Depends(require_admin)])
def admin_shops(db: Session = Depends(db_session)):
    rows = db.scalars(select(Shop).order_by(Shop.name)).all()
    return [{"id": s.id, "name": s.name, "slug": s.slug, "status": s.status} for s in rows]

@app.post("/api/admin/shops/{shop_id}/approve", dependencies=[Depends(require_admin)])
def approve_shop(shop_id: str, db: Session = Depends(db_session)):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    if shop.status not in ("pending", "approved"):
        raise HTTPException(409, "Shop cannot be approved from current state")
    shop.status = "approved"  # Licensing required before public activation.
    db.commit()
    return {"id": shop.id, "status": shop.status}

def cashfree_headers():
    if not APP_ID or not SECRET:
        raise HTTPException(503, "Cashfree credentials are not configured")
    return {"x-client-id": APP_ID, "x-client-secret": SECRET,
            "x-api-version": CF_VERSION, "Content-Type": "application/json"}

async def cf_call(method: str, url: str, **kwargs):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, url, headers=cashfree_headers(), **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Payment provider request failed")

@app.post("/api/admin/licenses/checkout", dependencies=[Depends(require_admin)])
async def create_checkout(body: Checkout, db: Session = Depends(db_session)):
    shop = db.get(Shop, body.shop_id)
    if not shop or shop.status not in ("approved", "active"):
        raise HTTPException(409, "Shop is not approved")
    if body.plan not in PLANS or body.billing_cycle not in ("monthly", "yearly"):
        raise HTTPException(422, "Invalid plan or billing cycle")
    amount = PLANS[body.plan][body.billing_cycle]
    order_id = "rl_" + uuid4().hex
    invoice = Invoice(id=order_id, shop_id=shop.id, plan=body.plan,
                      billing_cycle=body.billing_cycle, amount=Decimal(amount), status="pending")
    db.add(invoice)
    db.commit()
    payload = {
        "order_id": order_id,
        "order_amount": amount,
        "order_currency": "INR",
        "customer_details": {"customer_id": shop.id, "customer_email": shop.email, "customer_phone": shop.phone},
        "order_meta": {"return_url": BASE_URL + "/?license_order=" + order_id,
                       "notify_url": BASE_URL + "/api/webhooks/cashfree/license"},
        "order_note": "RAJ Enterprise shop licence " + body.plan,
    }
    result = await cf_call("POST", CF_BASE + "/orders", json=payload)
    if not result.get("payment_session_id"):
        raise HTTPException(502, "Cashfree did not return a checkout session")
    return {"order_id": order_id, "payment_session_id": result["payment_session_id"],
            "environment": CF_ENV, "amount": amount, "currency": "INR"}

def activate_verified_order(db: Session, invoice: Invoice):
    """Idempotent local activation, only after Cashfree GET confirms PAID."""
    if invoice.status == "paid":
        return
    lock = db.scalar(select(Invoice).where(Invoice.id == invoice.id).with_for_update())
    if lock.status == "paid":
        return
    license_row = db.get(License, lock.shop_id)
    now = datetime.now(timezone.utc)
    prior = license_row.valid_until if license_row else None
    if prior and prior.tzinfo is None:
        prior = prior.replace(tzinfo=timezone.utc)
    start = max(now, prior) if prior else now
    end = start + relativedelta(months=1 if lock.billing_cycle == "monthly" else 12)
    if license_row:
        license_row.plan, license_row.valid_until, license_row.last_invoice_id = lock.plan, end, lock.id
    else:
        db.add(License(shop_id=lock.shop_id, plan=lock.plan, valid_until=end, last_invoice_id=lock.id))
    lock.status = "paid"
    shop = db.get(Shop, lock.shop_id)
    if shop.status == "approved":
        shop.status = "active"
    db.commit()

async def verify_and_activate(order_id: str, db: Session):
    inv = db.get(Invoice, order_id)
    if not inv:
        raise HTTPException(404, "Unknown licence invoice")
    result = await cf_call("GET", CF_BASE + "/orders/" + order_id)
    if (result.get("order_id") != inv.id or
        result.get("order_currency") != "INR" or
        Decimal(str(result.get("order_amount", -1))) != inv.amount):
        raise HTTPException(409, "Provider amount or invoice mismatch")
    if result.get("order_status") == "PAID":
        activate_verified_order(db, inv)
    return {"order_id": inv.id, "status": inv.status, "provider_status": result.get("order_status")}

@app.post("/api/webhooks/cashfree/license")
async def license_webhook(request: Request, db: Session = Depends(db_session)):
    # Cashfree signs timestamp + exact RAW request body. Never re-serialize JSON first.
    body = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")
    if not SECRET or not timestamp or not signature or not timestamp.isdigit():
        raise HTTPException(401, "Invalid webhook authentication")
    if abs(datetime.now(timezone.utc).timestamp() - int(timestamp)) > 600:
        raise HTTPException(401, "Expired webhook timestamp")
    expected = base64.b64encode(hmac.new(SECRET.encode(), timestamp.encode() + body,
                                        hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        event = await request.json()
        order_id = event["data"]["order"]["order_id"]
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "Malformed webhook")
    if not isinstance(order_id, str) or not re.fullmatch(r"rl_[a-f0-9]{32}", order_id):
        return {"received": True}  # Other event: no licence is activated.
    await verify_and_activate(order_id, db)  # Check actual provider state, not event claims.
    return {"received": True}

@app.get("/api/admin/licenses/{order_id}", dependencies=[Depends(require_admin)])
async def admin_license_status(order_id: str, db: Session = Depends(db_session)):
    return await verify_and_activate(order_id, db)

@app.get("/api/admin/shops/{shop_id}/license", dependencies=[Depends(require_admin)])
def license_status(shop_id: str, db: Session = Depends(db_session)):
    lic = db.get(License, shop_id)
    return {"shop_id": shop_id, "plan": lic.plan if lic else None,
            "valid_until": lic.valid_until.isoformat() if lic else None}

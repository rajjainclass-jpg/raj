"""RAJ Enterprise Phase 2: tenant-isolated shop accounts, branding, orders, devices and marketplace.
Staging only. A separate verified payment integration is needed for recurring mandates.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

import qrcode
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from main import Base, Shop, License, PLANS, db_session, require_admin, BASE_URL

router = APIRouter(prefix="/api/v2", tags=["Enterprise Phase 2"])
password_hash = PasswordHash.recommended()
UTC = timezone.utc


def now():
    return datetime.now(UTC)


def aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def digest(value: str):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OwnerInvite(Base):
    __tablename__ = "owner_invites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class ShopOwner(Base):
    __tablename__ = "shop_owners"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    password_digest: Mapped[str] = mapped_column(String(256))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class OwnerSession(Base):
    __tablename__ = "owner_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("shop_owners.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopAppearance(Base):
    __tablename__ = "shop_appearance"
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    headline: Mapped[str] = mapped_column(String(110), default="Print online. Collect locally.")
    description: Mapped[str] = mapped_column(String(400), default="Upload your document at our counter.")
    primary_color: Mapped[str] = mapped_column(String(7), default="#16375C")
    accent_color: Mapped[str] = mapped_column(String(7), default="#EAC46F")
    logo_url: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str] = mapped_column(String(90), default="")
    public_listing: Mapped[bool] = mapped_column(Boolean, default=True)


class ShopDomain(Base):
    __tablename__ = "shop_domains"
    hostname: Mapped[str] = mapped_column(String(253), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    verify_token: Mapped[str] = mapped_column(String(70))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class PrintOrder(Base):
    __tablename__ = "tenant_print_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    tracking_hash: Mapped[str] = mapped_column(String(64), unique=True)
    customer_name: Mapped[str] = mapped_column(String(90))
    pages: Mapped[int] = mapped_column(Integer)
    copies: Mapped[int] = mapped_column(Integer)
    color_mode: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(25), default="received")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PrinterInvite(Base):
    __tablename__ = "printer_invites"
    secret_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class RegisteredDevice(Base):
    __tablename__ = "registered_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(90))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingPreference(Base):
    __tablename__ = "billing_preferences"
    shop_id: Mapped[str] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    renewal_mode: Mapped[str] = mapped_column(String(25), default="manual")
    mandate_status: Mapped[str] = mapped_column(String(30), default="not_configured")
    provider_subscription_id: Mapped[str | None] = mapped_column(String(100))


class Registration(BaseModel):
    invitation: str
    password: str = Field(min_length=12, max_length=120)


class Login(BaseModel):
    shop_slug: str
    email: str
    password: str


class AppearanceInput(BaseModel):
    headline: str = Field(min_length=3, max_length=110)
    description: str = Field(max_length=400)
    primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: str | None = Field(default=None, max_length=500)
    city: str = Field(default="", max_length=90)
    public_listing: bool = True


class DomainInput(BaseModel):
    hostname: str = Field(min_length=4, max_length=253)


class OrderInput(BaseModel):
    customer_name: str = Field(min_length=2, max_length=90)
    pages: int = Field(ge=1, le=200)
    copies: int = Field(ge=1, le=100)
    color_mode: str = Field(pattern=r"^(bw|colour)$")
    note: str = Field(default="", max_length=300)


class TrackingRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class OrderUpdate(BaseModel):
    status: str = Field(pattern=r"^(printing|ready|collected|cancelled)$")


class PrinterName(BaseModel):
    display_name: str = Field(min_length=2, max_length=90)


class DeviceEnroll(BaseModel):
    invitation: str
    display_name: str = Field(min_length=2, max_length=90)


class BillingInput(BaseModel):
    renewal_mode: str = Field(pattern=r"^(manual|request_recurring)$")


def license_live(db, shop_id):
    shop = db.get(Shop, shop_id)
    lic = db.get(License, shop_id)
    return bool(shop and shop.status == "active" and lic and aware(lic.valid_until) > now())


def require_owner(authorization: str | None = Header(default=None), db: Session = Depends(db_session)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Shop owner authentication required")
    token = authorization[7:]
    session = db.get(OwnerSession, digest(token))
    if not session or aware(session.expires_at) <= now():
        raise HTTPException(401, "Invalid or expired session")
    owner = db.get(ShopOwner, session.owner_id)
    if not owner or owner.disabled:
        raise HTTPException(403, "Account disabled")
    return owner


def require_device(authorization: str | None = Header(default=None), db: Session = Depends(db_session)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Device authorization required")
    found = db.scalar(select(RegisteredDevice).where(RegisteredDevice.token_hash == digest(authorization[7:])))
    if not found or found.revoked or not license_live(db, found.shop_id):
        raise HTTPException(403, "Device not authorized or license inactive")
    found.last_seen = now()
    db.commit()
    return found


def summary(s, a):
    return {"id": s.id, "name": s.name, "slug": s.slug,
            "headline": a.headline if a else "Print online. Collect locally.",
            "description": a.description if a else "",
            "primary_color": a.primary_color if a else "#16375C",
            "accent_color": a.accent_color if a else "#EAC46F",
            "logo_url": a.logo_url if a else None,
            "city": a.city if a else ""}


@router.post("/admin/shops/{shop_id}/owner-invite", dependencies=[Depends(require_admin)])
def owner_invite(shop_id: str, db: Session = Depends(db_session)):
    shop = db.get(Shop, shop_id)
    if not shop or shop.status not in ("approved", "active"):
        raise HTTPException(409, "Shop must first be approved")
    token = secrets.token_urlsafe(32)
    db.add(OwnerInvite(id=str(uuid4()), shop_id=shop_id, secret_hash=digest(token),
                       expires_at=now() + timedelta(hours=24), used=False))
    db.commit()
    return {"invitation": token, "expires_in_hours": 24,
            "delivery": "Deliver privately to the verified shop contact; never post in a public URL"}


@router.post("/auth/register")
def register(body: Registration, db: Session = Depends(db_session)):
    invite = db.scalar(select(OwnerInvite).where(OwnerInvite.secret_hash == digest(body.invitation)).with_for_update())
    if not invite or invite.used or aware(invite.expires_at) <= now():
        raise HTTPException(400, "Invalid or expired invitation")
    shop = db.get(Shop, invite.shop_id)
    if not shop or shop.status not in ("approved", "active"):
        raise HTTPException(400, "Shop is unavailable")
    if db.scalar(select(ShopOwner).where(ShopOwner.shop_id == shop.id)):
        raise HTTPException(409, "Shop already has an owner account")
    owner = ShopOwner(id=str(uuid4()), shop_id=shop.id, email=shop.email.lower(),
                      password_digest=password_hash.hash(body.password))
    db.add(owner)
    invite.used = True
    db.commit()
    return {"created": True, "shop_slug": shop.slug}


@router.post("/auth/login")
def login(body: Login, db: Session = Depends(db_session)):
    shop = db.scalar(select(Shop).where(Shop.slug == body.shop_slug))
    owner = (db.scalar(select(ShopOwner).where(ShopOwner.shop_id == shop.id,
                                              ShopOwner.email == body.email.strip().lower()))
             if shop else None)
    # Same external error for invalid account and password; do not reveal account existence.
    if not owner or owner.disabled or not password_hash.verify(body.password, owner.password_digest):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_urlsafe(48)
    db.add(OwnerSession(token_hash=digest(token), owner_id=owner.id, expires_at=now()+timedelta(hours=8)))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": 28800}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), owner: ShopOwner = Depends(require_owner),
           db: Session = Depends(db_session)):
    session = db.get(OwnerSession, digest(authorization[7:]))
    if session:
        db.delete(session)
        db.commit()
    return {"logged_out": True}


@router.get("/owner/me")
def owner_me(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    s = db.get(Shop, owner.shop_id)
    lic = db.get(License, s.id)
    return {"shop_id": s.id, "name": s.name, "slug": s.slug, "status": s.status,
            "license_active": license_live(db, s.id),
            "license_plan": lic.plan if lic else None}


@router.put("/owner/appearance")
def set_appearance(body: AppearanceInput, owner: ShopOwner = Depends(require_owner),
                   db: Session = Depends(db_session)):
    if body.logo_url:
        parsed = urlparse(body.logo_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422, "Logo must be a public HTTPS image URL")
    row = db.get(ShopAppearance, owner.shop_id)
    if not row:
        row = ShopAppearance(shop_id=owner.shop_id)
        db.add(row)
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return {"saved": True}


@router.get("/shops/{slug}")
def public_shop(slug: str, db: Session = Depends(db_session)):
    s = db.scalar(select(Shop).where(Shop.slug == slug))
    if not s or not license_live(db, s.id):
        raise HTTPException(404, "Shop not available")
    return summary(s, db.get(ShopAppearance, s.id))


@router.get("/marketplace")
def marketplace(search: str = "", city: str = "", db: Session = Depends(db_session)):
    candidates = db.scalars(select(Shop).where(Shop.status == "active").limit(500)).all()
    entries = []
    for s in candidates:
        a = db.get(ShopAppearance, s.id)
        if not license_live(db, s.id) or (a and not a.public_listing):
            continue
        if search and search.casefold() not in s.name.casefold():
            continue
        if city and (not a or city.casefold() not in a.city.casefold()):
            continue
        entries.append(summary(s, a))
    return {"shops": entries[:100]}


@router.get("/shops/{slug}/qr.png")
def shop_qr(slug: str, db: Session = Depends(db_session)):
    s = db.scalar(select(Shop).where(Shop.slug == slug))
    if not s or not license_live(db, s.id):
        raise HTTPException(404, "Shop not available")
    image = qrcode.make(BASE_URL + "/s/" + s.slug)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png",
                             headers={"Cache-Control": "public, max-age=300"})


@router.post("/owner/domains")
def request_domain(body: DomainInput, owner: ShopOwner = Depends(require_owner),
                   db: Session = Depends(db_session)):
    host = body.hostname.lower().strip().rstrip(".")
    if (not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host)
            or host.endswith(".onrender.com")):
        raise HTTPException(422, "Invalid domain hostname")
    exists = db.get(ShopDomain, host)
    if exists and exists.shop_id != owner.shop_id:
        raise HTTPException(409, "Domain already claimed")
    if not exists:
        exists = ShopDomain(hostname=host, shop_id=owner.shop_id,
                            verify_token="raj-verification=" + secrets.token_hex(20), verified=False)
        db.add(exists)
        db.commit()
    return {"hostname": host, "txt_record": "_raj-enterprise." + host,
            "txt_value": exists.verify_token, "verified": exists.verified,
            "next": "Super Admin must verify domain ownership and provision HTTPS on Render"}


@router.get("/owner/domains")
def owner_domains(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    return [{"hostname": d.hostname, "verified": d.verified}
            for d in db.scalars(select(ShopDomain).where(ShopDomain.shop_id == owner.shop_id))]


@router.post("/shops/{slug}/orders", status_code=201)
def create_print_request(slug: str, body: OrderInput, db: Session = Depends(db_session)):
    s = db.scalar(select(Shop).where(Shop.slug == slug))
    if not s or not license_live(db, s.id):
        raise HTTPException(404, "Shop not accepting requests")
    token = secrets.token_urlsafe(32)
    order = PrintOrder(id=str(uuid4()), shop_id=s.id, tracking_hash=digest(token),
                       customer_name=body.customer_name.strip(), pages=body.pages,
                       copies=body.copies, color_mode=body.color_mode,
                       note=body.note, status="received")
    db.add(order)
    db.commit()
    return {"order_id": order.id, "tracking_token": token, "status": order.status,
            "document_upload": "not_enabled",
            "message": "Print request recorded. No document has been uploaded or paid for."}


@router.post("/shops/{slug}/orders/{order_id}/track")
def public_order_status(slug: str, order_id: str, body: TrackingRequest, db: Session = Depends(db_session)):
    s = db.scalar(select(Shop).where(Shop.slug == slug))
    order = db.get(PrintOrder, order_id)
    if not s or not order or order.shop_id != s.id or not secrets.compare_digest(order.tracking_hash, digest(body.token)):
        raise HTTPException(404, "Request not found")
    return {"order_id": order.id, "shop": s.name, "status": order.status, "document_uploaded": False}


@router.get("/owner/orders")
def owner_orders(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    orders = db.scalars(select(PrintOrder).where(PrintOrder.shop_id == owner.shop_id).order_by(PrintOrder.created_at.desc()).limit(100)).all()
    return [{"id": o.id, "status": o.status, "customer_name": o.customer_name,
             "pages": o.pages, "copies": o.copies, "color_mode": o.color_mode} for o in orders]


@router.patch("/owner/orders/{order_id}")
def update_order(order_id: str, body: OrderUpdate, owner: ShopOwner = Depends(require_owner),
                 db: Session = Depends(db_session)):
    order = db.get(PrintOrder, order_id)
    if not order or order.shop_id != owner.shop_id:
        raise HTTPException(404, "Order not found")
    allowed = {"received": {"printing", "cancelled"}, "printing": {"ready", "cancelled"},
               "ready": {"collected"}, "collected": set(), "cancelled": set()}
    if body.status not in allowed[order.status]:
        raise HTTPException(409, "Invalid order state transition")
    order.status = body.status
    db.commit()
    return {"id": order.id, "status": order.status}


@router.post("/owner/devices/enrollment")
def device_invite(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    if not license_live(db, owner.shop_id):
        raise HTTPException(403, "Active licence required")
    plan = db.get(License, owner.shop_id).plan
    limit = PLANS.get(plan, {}).get("printers", 0)
    active = db.scalar(select(func.count()).select_from(RegisteredDevice)
                       .where(RegisteredDevice.shop_id == owner.shop_id, RegisteredDevice.revoked == False))
    if active >= limit:
        raise HTTPException(409, "Printer device plan limit reached")
    token = secrets.token_urlsafe(32)
    db.add(PrinterInvite(secret_hash=digest(token), shop_id=owner.shop_id,
                         expires_at=now()+timedelta(minutes=20), used=False))
    db.commit()
    return {"enrollment_code": token, "expires_minutes": 20,
            "warning": "Use once; do not paste into public pages"}


@router.post("/devices/enroll")
def enroll_device(body: DeviceEnroll, db: Session = Depends(db_session)):
    invite = db.scalar(select(PrinterInvite).where(PrinterInvite.secret_hash == digest(body.invitation)).with_for_update())
    if not invite or invite.used or aware(invite.expires_at) <= now() or not license_live(db, invite.shop_id):
        raise HTTPException(401, "Invalid enrollment invitation")
    plan = db.get(License, invite.shop_id).plan
    limit = PLANS.get(plan, {}).get("printers", 0)
    active = db.scalar(select(func.count()).select_from(RegisteredDevice)
                       .where(RegisteredDevice.shop_id == invite.shop_id, RegisteredDevice.revoked == False))
    if active >= limit:
        raise HTTPException(409, "Device limit reached")
    token = secrets.token_urlsafe(48)
    dev = RegisteredDevice(id=str(uuid4()), shop_id=invite.shop_id,
                           display_name=body.display_name, token_hash=digest(token), revoked=False)
    db.add(dev)
    invite.used = True
    db.commit()
    return {"device_id": dev.id, "device_token": token, "token_type": "bearer",
            "warning": "Store securely; this token is shown only once"}


@router.get("/devices/me")
def device_me(device: RegisteredDevice = Depends(require_device)):
    return {"device_id": device.id, "shop_id": device.shop_id,
            "display_name": device.display_name, "authorized": True}


@router.get("/devices/queue")
def device_queue(device: RegisteredDevice = Depends(require_device), db: Session = Depends(db_session)):
    # Metadata-only preview; no untrusted document bytes or customer details are transmitted.
    orders = db.scalars(select(PrintOrder).where(
        PrintOrder.shop_id == device.shop_id, PrintOrder.status == "printing").limit(30)).all()
    return {"device_id": device.id, "jobs": [{"order_id": o.id, "pages": o.pages, "copies": o.copies,
                                              "color_mode": o.color_mode, "document_available": False}
                                             for o in orders]}


@router.get("/owner/devices")
def owner_devices(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    devices = db.scalars(select(RegisteredDevice).where(RegisteredDevice.shop_id == owner.shop_id)).all()
    return [{"id": d.id, "display_name": d.display_name, "revoked": d.revoked} for d in devices]


@router.post("/owner/devices/{device_id}/revoke")
def revoke_device(device_id: str, owner: ShopOwner = Depends(require_owner),
                  db: Session = Depends(db_session)):
    device = db.get(RegisteredDevice, device_id)
    if not device or device.shop_id != owner.shop_id:
        raise HTTPException(404, "Device not found")
    device.revoked = True
    db.commit()
    return {"revoked": True}


@router.put("/owner/billing/preference")
def billing_preference(body: BillingInput, owner: ShopOwner = Depends(require_owner),
                       db: Session = Depends(db_session)):
    row = db.get(BillingPreference, owner.shop_id)
    if not row:
        row = BillingPreference(shop_id=owner.shop_id)
        db.add(row)
    row.renewal_mode = body.renewal_mode
    # This records intent only. A Cashfree mandate has not been created or authorized.
    row.mandate_status = "not_configured"
    db.commit()
    return {"renewal_mode": row.renewal_mode, "mandate_status": row.mandate_status,
            "message": "Recurring billing is not enabled until verified Cashfree mandate integration is completed"}


@router.get("/owner/billing/preference")
def get_billing_preference(owner: ShopOwner = Depends(require_owner), db: Session = Depends(db_session)):
    row = db.get(BillingPreference, owner.shop_id)
    return {"renewal_mode": row.renewal_mode if row else "manual",
            "mandate_status": row.mandate_status if row else "not_configured"}


@router.post("/admin/domains/{hostname}/verify", dependencies=[Depends(require_admin)])
def verify_domain(hostname: str, db: Session = Depends(db_session)):
    # Only DNS TXT evidence is checked here; TLS and Render routing must still be provisioned.
    import dns.resolver
    domain = db.get(ShopDomain, hostname.lower().strip().rstrip("."))
    if not domain:
        raise HTTPException(404, "Domain request not found")
    name = "_raj-enterprise." + domain.hostname
    try:
        answers = dns.resolver.resolve(name, "TXT", lifetime=5)
        values = [b"".join(rr.strings).decode("utf-8", errors="ignore") for rr in answers]
    except (dns.exception.DNSException, OSError):
        raise HTTPException(409, "DNS verification record not found")
    if domain.verify_token not in values:
        raise HTTPException(409, "DNS record does not match")
    domain.verified = True
    db.commit()
    return {"hostname": domain.hostname, "verified": True,
            "next": "Provision custom domain and managed TLS in Render; routing is not automatic"}

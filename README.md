# RAJ Enterprise Cloud Pro — Phase 1

**Status: development staging only. Not live on Render.** This repository was previously empty. The existing `https://raj-computer-and-prints.onrender.com/` app has not been overwritten.

## Included

- Premium responsive landing page with a partner application form, indicative plans and approved-shop directory
- FastAPI + SQLAlchemy shop registry and manual whitelisting
- Super Admin Bearer authentication for approval and billing operations
- Starter ₹199, Professional ₹499, Business ₹999 per month (illustrative); annual rates in `main.py`
- Cashfree Payment Gateway *one-time* licence checkout for purchase/renewal (sandbox by default)
- Server-to-server Cashfree order-status verification and signed raw-body webhook verification
- Invoice-scoped, idempotent licence activation and expiry extension
- Render **staging** blueprint, environment template and test workflow

## Run locally

Use Python 3.12 or a compatible supported version.

```powershell
git clone https://github.com/rajjainclass-jpg/raj.git
cd raj
git checkout feature/enterprise-license-cashfree-phase1
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# EDIT .env locally: set ADMIN_API_TOKEN and Cashfree SANDBOX app credentials.
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. API docs: `/docs`.

## Payment operations

1. Create a partner application on the public page.
2. Super Admin approves via `/api/admin/shops/{shop_id}/approve`.
3. Super Admin creates a licence checkout via `POST /api/admin/licenses/checkout` with shop ID, plan and billing cycle.
4. The backend creates a Cashfree order with the amount computed **server-side** and returns `payment_session_id`.
5. Cashfree hosted JS checkout handles the payment. The webhook uses the raw body, Cashfree signature and timestamp; the server **also calls GET /pg/orders/{id}** before activation.
6. Only an order with matching ID, INR currency, matching amount and `PAID` status activates or renews the licence. Duplicate processing does not extend it twice.

Licence webhook (staging): `https://YOUR-STAGING-SERVICE.onrender.com/api/webhooks/cashfree/license`. Register it in the correct Cashfree environment, or use the per-order notify URL after confirming provider settings.

Cashfree official documentation: https://www.cashfree.com/docs/payments/overview

## Render setup — IMPORTANT

The supplied `render.yaml` creates a **separate staging web service** to avoid breaking the existing printing website. Set all required secrets in Render's dashboard, not in Git:
- `DATABASE_URL`: persistent PostgreSQL connection string (never ephemeral SQLite in production)
- `ADMIN_API_TOKEN`: strong random token
- `PUBLIC_BASE_URL`: full HTTPS staging URL
- `CASHFREE_ENV=sandbox`
- `CASHFREE_APP_ID`, `CASHFREE_SECRET_KEY`: **sandbox** credentials
- `CASHFREE_API_VERSION=2025-01-01`

Do not connect the new repository to an existing live Render service until its deployed branch and old FastAPI source have been inspected. This starter has **not** migrated your existing printing/orders system.

## Required work before production

- Proper shop-owner authentication, email/phone verification and MFA; admin token UI is **prototype only**
- Rate limits, CAPTCHA/anti-spam, validated contacts, strong authorization and audit logs
- Alembic migrations, row-level tenant isolation, concurrent billing idempotency and reconciliation jobs
- Recurring Cashfree Subscriptions mandate flow (separate from one-time licence checkout)
- Subscription cancellation, refunds, taxes, invoices, proration and chargeback policy
- Custom domains and domain ownership, tenant themes, approved device enrollment and print agent
- Private customer file storage, deletion policy and payment gateway compliance
- Load/security testing, monitoring, backup/restore and real merchant onboarding approval

**Security notice:** Any Cashfree keys previously pasted into chat or accidentally exposed should be rotated before production use. Never paste private keys into GitHub or frontend JavaScript. Commercial merchant responsibilities must be handled by an eligible adult or guardian.

## Existing website integration

Longer term, mount this module into the existing FastAPI project using separate route prefixes and payment intent identifiers (e.g. `license` vs `print_order`). Preserve the existing customer printing flow and its current payment webhook separately. Never send partner-shop settlement payments to an unrelated merchant without provider-approved arrangements.

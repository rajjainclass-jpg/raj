# Same Render URL — integration gate (do not deploy until audited)

**Requested public URL:** https://raj-computer-and-prints.onrender.com/

## Verified access available while preparing this branch

- GitHub repository: `rajjainclass-jpg/raj`, containing **new Enterprise development code**.
- Original printing source: **not accessible in the connected repository**; the PC-mounted project `E:\raj_computer_prints_v3` is not available while the shop computer is offline.
- Render dashboard/service configuration: **not connected or inspected**.
- The public URL could not be inspected programmatically during this session.

**Because of those missing inputs, this branch MUST NOT be selected as the original service's deploy branch or merged into an auto-deploy production branch.**

## Goal — preserve original printing service

| Path after approved integration | Owner |
| --- | --- |
| `/` | Existing RAJ Computer and Print homepage |
| `/api/upload` and existing print routes | Existing printing application |
| `/api/webhooks/cashfree` (and any other existing payment route) | Existing printing application |
| `/enterprise/` | New RAJ Enterprise SaaS homepage |
| `/enterprise/owner` | New shop-owner portal |
| `/enterprise/marketplace` | New public marketplace |
| `/enterprise/s/{slug}` | Individual partner shop |
| `/enterprise/api/v2/...` | New SaaS tenant APIs |
| `/enterprise/api/webhooks/cashfree/license` | New **licence-only** Cashfree webhook |

All partner licence checks and independent merchant payment orders must use the Enterprise namespace and purpose-specific record types. Existing customer-printing data, upload endpoints and payment webhooks are not changed by this gateway.

A future optional `/s/{slug}` shortcut can be added **only after** confirming no collision with existing paths; initially, unique QR codes should open `/enterprise/s/{slug}`.

## Safe integration deployment plan

1. **Obtain the exact existing deployed source** (GitHub repository and branch or original PC project). Do not assume this new empty-origin `raj` repository contains it.
2. **Take a backup** of database/storage and note the last known-good Render deploy, runtime, start command, branch and environment keys. Never copy secret values into logs.
3. Compare old FastAPI route table with reserved `/enterprise` namespace, and fix any collisions before proceeding. This adapter fails closed when it detects a reserved legacy route.
4. Merge code into one audited build. The existing printing app must be importable, for example `original_printing.main:app` (illustrative name — not yet present).
5. Keep Enterprise app importable as `main:app` in the combined build and use `gateway_entrypoint:app` as the ASGI entrypoint. Run `RAJ_LEGACY_ASGI=original_printing.main:app` (set to its real audited location).
6. Set `PUBLIC_BASE_URL=https://raj-computer-and-prints.onrender.com/enterprise` for Enterprise licence return URLs and scannable QR links.
7. Set **rotated** Cashfree sandbox credentials and register the **licence-only** callback at `https://raj-computer-and-prints.onrender.com/enterprise/api/webhooks/cashfree/license`. Existing print-payment callbacks must be preserved separately.
8. Use persistent PostgreSQL and proper migrations for the SaaS, alongside the legacy database. Never replace a production DB with the SaaS development SQLite database.
9. Run smoke tests against **staging with the same path layout**. Ensure the original `/`, uploads, print checkout, Cashfree print webhooks, data and order status work unchanged; verify new tenant isolation, licence payments, expired plans, printer revoke and customer privacy.
10. Disable automatic deploy on the production service during migration, and perform a reviewed release with rollback and monitoring prepared.

## Separate-staging versus same-production URL

The existing `render.yaml` creates a staging service (`raj-enterprise-staging`) that uses `main:app` and does **not** change the original URL. When the real legacy app becomes available and passes the gateway checks, the current public hostname can be preserved by modifying the **existing** Render service's deployment source and start command. The same address is retained because the existing service is retained.

**Do not set Render's production Start Command to `uvicorn main:app` from this repository.** That would serve only the new SaaS prototype and could interrupt existing printing routes.

### Staging commands (standalone new Enterprise prototype)

```powershell
py -3.12 -m pip install -r requirements-dev.txt
py -3.12 -m pytest -q
py -3.12 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### Combined deployment command (only after legacy source available and audited)

```bash
uvicorn gateway_entrypoint:app --host 0.0.0.0 --port $PORT
```

**Configuration needed for this future combined command:**

```env
RAJ_LEGACY_ASGI=original_printing.main:app
RAJ_ENTERPRISE_ASGI=main:app
PUBLIC_BASE_URL=https://raj-computer-and-prints.onrender.com/enterprise
DATABASE_URL=<private PostgreSQL URL>
CASHFREE_ENV=sandbox
CASHFREE_APP_ID=<rotated sandbox app id>
CASHFREE_SECRET_KEY=<rotated sandbox secret>
ADMIN_API_TOKEN=<strong private admin credential>
```

The actual original import target must be discovered from the deployed source; the example is not guaranteed to exist.

## Publishing hold criteria

- [ ] Original app source available and importable
- [ ] Render's existing service ID/repo/branch/start command confirmed
- [ ] Production backup and rollback path verified
- [ ] Owner-approved payment environment and fresh credentials configured privately
- [ ] Persistent database migrations reviewed
- [ ] Tests pass (both legacy and Enterprise)
- [ ] Cashfree sandbox checkouts validated end-to-end
- [ ] Account verification, MFA, rate limiting and tenant isolation production controls implemented
- [ ] Readiness signed off before existing Render service deployment

**Current status:** compatibility adapter + tests created. Production integration and publishing are blocked on access to the original app and Render configuration.

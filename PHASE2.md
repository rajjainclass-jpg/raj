# RAJ Enterprise Cloud — Ultra Pro Max Phase 2

## Scope implemented in this development branch

These are **staging capabilities** and must not be treated as production-ready without integration and security review.

| Feature | Current state |
| --- | --- |
| Shop owner accounts | Invite-only registration; Argon2 password hashing, 8-hour revocable token sessions |
| White-label branding | Configurable headline, description, logo URL, city, primary/accent colours, listing opt-in |
| Individual shop websites | Shared template at `/s/{slug}` with tenant configuration |
| Unique QR | Scannable PNG linking to `PUBLIC_BASE_URL/s/{slug}` |
| Custom domains | Request, reserved hostname and DNS TXT ownership verification; **TLS/proxy routing not implemented** |
| Marketplace | Search and city filter; only active, licensed, opted-in shops |
| Independent print orders | Tenant-scoped **metadata-only print requests** and private tracking tokens; **no document upload, actual print or payment** |
| Windows device licensing | Short-lived owner-generated enrollment code, device token, per-plan limits, revocation and metadata queue; **no auto printer interaction** |
| Recurring subscriptions | Owner opt-in preference stored; status `not_configured`; **no Cashfree mandate or automatic debit** |
| Licence checkout | Phase 1 Cashfree sandbox one-time payment order and verified activation |
| Admin | Phase 1 admin API + invitation and DNS verification endpoints |

**Known staged limitations:** no MFA, rate limiting, email confirmation, CSRF-reviewed production session architecture, S3 storage, malware scanning, full payment lifecycle, custom domain TLS automation, real print agent, high-concurrency licence idempotency or migration scripts. Avoid placing this staging build on a public live domain before resolving these.

## Endpoints

- `GET /owner` — owner portal
- `GET /s/{slug}` — independent shop website
- `POST /api/v2/admin/shops/{id}/owner-invite` — admin-only owner enrollment
- `POST /api/v2/auth/register` and `POST /api/v2/auth/login`
- `GET /api/v2/owner/me`
- `PUT /api/v2/owner/appearance`
- `GET /api/v2/marketplace` and `GET /api/v2/shops/{slug}`
- `GET /api/v2/shops/{slug}/qr.png`
- `POST /api/v2/owner/domains`, `GET /api/v2/owner/domains`
- `POST /api/v2/admin/domains/{hostname}/verify` — check DNS TXT record
- `POST /api/v2/shops/{slug}/orders` — metadata-only request
- `POST /api/v2/shops/{slug}/orders/{id}/track with JSON body containing the private token` — status; do not share token
- `GET /api/v2/owner/orders`, `PATCH /api/v2/owner/orders/{id}`
- `POST /api/v2/owner/devices/enrollment`, `POST /api/v2/devices/enroll`
- `GET /api/v2/devices/me`, `GET /api/v2/devices/queue`
- `GET /api/v2/owner/devices`, `POST /api/v2/owner/devices/{id}/revoke`
- `GET /api/v2/owner/billing/preference`, `PUT /api/v2/owner/billing/preference`

## Onboard a pilot

1. Start staging with **Cashfree sandbox** and persistent PostgreSQL; do not overwrite the current Render web service.
2. Use the Phase 1 public partner form to request a shop.
3. Super Admin approves shop, then calls `POST /api/v2/admin/shops/{id}/owner-invite` using an admin Bearer credential.
4. Deliver the returned one-time invitation privately to the approved shop owner.
5. Owner visits `/owner`, registers with invitation and password, and signs in using shop slug + registered email.
6. Owner selects colours, headline and logo. Changes appear at `/s/{slug}` once the shop has an active **verified licence**.
7. Super Admin uses Phase 1 **sandbox** licence checkout and verifies provider order status, which activates the shop.
8. Owner registers a printer device with a one-time code, then can revoke access.
9. Public customers can submit metadata-only print requests; no files are uploaded or payments taken in this phase.

## Cashfree recurring billing

Cashfree's distinct Subscriptions product supports hosted subscription checkout and recurring mandates. This branch **does not** fabricate successful recurring charges or update a licence based on an unverified `subscription_id`. The staged API records a preference only until a Cashfree sandbox account is provisioned for Subscriptions and all of the following are tested:

- merchant eligibility and subscription API version; authenticated create-subscription response
- customer opt-in and bank mandate authorization
- signed recurring payment webhooks and server-side reconciliation
- unique invoice or charge identifiers and idempotent per-cycle licence extension
- failed debits, notifications, cancellation and refunds
- RBI/Cashfree pre-debit notice and other required recurring mandate obligations

Official guide: https://www.cashfree.com/devstudio/preview/subs/web/checkout

## Hosting and migration

`render.yaml` deliberately defines **staging**. Keep the original printing service unaffected. Phase 2 introduces additional tables via `Base.metadata.create_all` for development; production requires Alembic migrations, PostgreSQL, backups and tenant isolation tests. Custom domains need a Render-approved hostname, DNS ownership, managed HTTPS certificate, and host-to-tenant routing before they work end-to-end.

Use Python 3.12 with `pip install -r requirements-dev.txt`, then run `python -m pytest -q`.

### Security reminders
The previous Cashfree secret shared in chat must be rotated, never committed. Licence ownership/financial responsibility must be handled by an eligible adult/guardian and authorized merchant account.

## Windows agent staging pilot

After the owner generates a single-use device enrollment code in `/owner`, run on the registered shop PC:

```powershell
py -3.12 agent_windows.py --server https://YOUR-STAGING-SERVICE.onrender.com --enroll "Epson Print Desk"
```

Then use the returned device credential with:

```powershell
py -3.12 agent_windows.py --server https://YOUR-STAGING-SERVICE.onrender.com --poll
```

This agent displays licensed queue **metadata only** and does **not** download documents or print files. Device credentials must be stored securely; this proof-of-concept stores nothing on disk.

Browse `/marketplace` to search approved public partner shops.

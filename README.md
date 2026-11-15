# RAJ Enterprise Cloud Pro

Hybrid white-label multi-shop printing SaaS.

## Status
Phase 1 development starter. **Not deployed to Render.** Existing printing service is not modified.

## Deployment principle
Keep the existing FastAPI application and its print-order endpoints working. Integrate the multi-tenant licence service after verifying compatibility, testing with Cashfree sandbox, and configuring a persistent PostgreSQL database.

## Safety
Never commit Cashfree credentials, production keys, or customer documents. Payments must be verified server-side. Merchant onboarding and commercial operations should be handled by an eligible adult/guardian.

# Raj Kirana browser checkout

Public static checkout frontend for the Customer APK. Payment sessions and amounts originate from the authenticated Supabase service; merchant credentials stay in Supabase Vault. The frontend receives an order-scoped session in a URL fragment and removes that fragment before checkout. It does not persist sessions, collect card information, mark orders paid, or contain API keys.

Deploy the `public` directory as a Render static site. Approve the deployed HTTPS domain in the Cashfree merchant dashboard before Live use. The Android app opens this page in a normal browser, and verifies the existing order on return. Cashfree's official JavaScript SDK handles the payment UI.

This code belongs to the `raj-kirana-browser-checkout` branch in the owner's repository. The Android source archive references this repository rather than duplicating its source.

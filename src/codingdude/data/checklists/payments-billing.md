# Payments & billing checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-payments-billing-engineer.md
Use when: building any payment, subscription, or billing integration (Stripe/Adyen/Braintree/PayPal style).

## Checklist
- [ ] Card data never touches your servers: hosted fields/SDK tokenization only (SAQ A). A PAN reaching your backend = redesign.
- [ ] Every money mutation (charge, refund, subscription change) carries an idempotency key derived from the business operation (e.g. `order-{id}-attempt-{n}`), not a per-request random UUID.
- [ ] Fulfillment triggers on the processor webhook (`payment_intent.succeeded` or equivalent), never on the browser redirect back to the success page.
- [ ] Webhook handlers: verify signature against the RAW body, deduplicate by persisting event IDs, return 2xx fast and queue heavy work (avoid PSP retry storms).
- [ ] Webhook handlers never trust event order — re-fetch current object state instead of applying deltas.
- [ ] Money stored as integers in minor units + ISO 4217 currency code; floats banned; zero-decimal currencies (JPY) handled explicitly.
- [ ] PSP objects linked back to domain objects via metadata (order_id etc.).
- [ ] Subscription lifecycle is an explicit state machine (trialing/active/past_due/canceled/incomplete), including: grace period + dunning on failed renewal, access revocation after dunning exhaustion, proration on mid-cycle plan changes.
- [ ] All unhappy states modeled and tested: `requires_action` (3DS), processing, partial refunds, disputes, failed retries.
- [ ] Failure-path tests use the PSP's test catalog: declines, insufficient funds, 3DS challenges, webhook replays, duplicate + out-of-order deliveries, mid-flow abandonment. Success-card-only = untested.
- [ ] Daily automated payout-vs-ledger reconciliation with drift alert; any nonzero drift is an incident.
- [ ] Dispute handling: evidence deadline monitor + evidence assembly (order/shipping/session data); dispute rate watched (<0.1% target).
- [ ] Operational runbook exists: refund procedure, dispute checklist, dunning schedule, PSP-outage behavior.
- [ ] Multi-currency (if applicable): presentment vs settlement separation, FX timing, rounding per ISO 4217 exponent; local payment methods' async confirmations handled.

## Failure modes
- Double charges from client retries without idempotency keys.
- Fulfilling on redirect while the webhook is still pending (or after tab closed).
- "Log-and-ignore" of 3DS/dispute/dunning states, producing silent revenue loss.
- Storing card data "temporarily" → whole platform lands in SAQ D / full PCI audit.
- Reconciliation break left unfound for days because it wasn't automated daily.

## Rejected
- Persona voice, PSP war stories, dunning-revenue metrics as identity. Kept the mechanics.

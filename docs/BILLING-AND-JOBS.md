# Castle usage, credits and resumable tasks

This release is for local/private testing. Defaults: free deterministic charts,
a prewritten fictional hearing, BYOK AI, zero hosted budgets, disabled payments.
Opening a page does not make model calls. Tables are added to the existing SQLite
database without rewriting cases. Back up the database before upgrading.

## Visitor access

| Mode | Cost / behavior |
|---|---|
| BYOK | No Castle account required. Key stays in page memory and the running server task; never persisted or replaced with the operator Key. |
| Trial | Account can claim 5 points once, if the operator enables a funded budget. Select exactly two rooms: 2 points each plus 1 for Tribunal. No follow-up or AI extraction. |
| Paid | Hosted Flash: report 2, Tribunal 1, answer 1, rebuttal 1, hearing summary 1, AI extraction 2. |
| Test payment | Separate sandbox points; cannot call real AI. |

Thirty points cover seven reports, Tribunal and one seven-room hearing. Fifteen
cover a seven-room hearing. Retail prices are not set. Failed steps refund points;
completed content remains accessible. Partial success is charged only for completed
steps. Same-configuration results are reused. Actual retry costs are accounted for
separately, even when visitor points are refunded.

Accounts use salted scrypt password hashes and expiring, revocable hashed session
tokens. Session tokens and case passports live in the current tab's sessionStorage;
API Keys do not. The private-test account system has no self-service password reset
yet. Keep credentials in a password manager.

## Jobs and API changes

`POST /cases/{id}/reports` and `/debates` now return **202 + a task**, not the final
report. Send optional JSON `systems` to choose participants. Poll `GET /cases/{id}`
with `X-Case-Token` for jobs and completed results; the UI waits 2.5 seconds between
successful requests, with a 15-second request deadline and up to 30-second error
backoff. Requests do not overlap, and reconnecting clears the connection warning.
Each report, answer, rebuttal and summary is saved independently. Closing a tab
does not cancel execution. Downstream stages wait for all selected witnesses.

### Stop without losing paid results

`POST /cases/{id}/jobs/{job_id}/stop` (case token required, no model Key required)
requests a cooperative stop. The task enters `stopping`: no new provider requests
or automatic retries are sent, including calls waiting for a concurrency slot.
Already-dispatched requests finish normally, save successful output, and settle
their usage/points. They cannot be recalled and may still incur provider charges.
Unsent or failed steps refund reserved visitor points. Unknown upstream failures
still retain the conservative provider cost estimate; stopping cannot erase costs.

Once in-flight work settles, unfinished steps/task become `cancelled` (shown as
已停止). If everything has already finished, the task remains `completed`.
Resume using the existing retry endpoint and original payer; completed steps are
reused. Repeated stops are idempotent. Facts/deletion/new case tasks remain locked
while `stopping`, and a server restart preserves the stop intention rather than
automatically dispatching more work. This control applies to report/hearing jobs,
not synchronous file extraction.

Send `X-Payment-Mode: byok|trial|paid`. BYOK needs `X-DeepSeek-Key`; hosted modes
need `Authorization: Bearer <account session>`. Hosted models are fixed to Flash.
Keys never fall back from BYOK to the server configuration.

After restart, jobs are `interrupted`. Resume through
`POST /cases/{id}/jobs/{job_id}/retry` with the original mode/account and a fresh
BYOK Key when applicable. Secrets are never saved to resume automatically. Completed
responses are cached in the same transaction as point settlement: a crash between
settlement and publication does not charge again. Duplicate submissions return the
existing task. Adding more chambers reuses matching completed reports.

Tasks bind to a facts revision, model, Skill content, participants, question and
payer. Fact edits during running jobs are blocked. Later edits archive old hearings
and invalidate current reports. Earlier hearings remain marked in Markdown exports.
`DELETE /cases/{id}` removes the case, jobs and cached response text; accounting
metadata stays for reconciliation. Ending a hearing only exits the case.

Run **one API worker per database**. A Unix file lock enforces this; SQLite and
in-process tasks are not a distributed queue. Restart recovery requires the visitor
to resubmit credentials. Completed steps remain safe across disconnection/restart.

## Operator budgets

Use `backend/.env.example` and explicitly load it locally:

```bash
cd backend
.venv/bin/uvicorn app.main:app --env-file .env --port 8000
```

`CASTLE_FREE_BUDGET_USD=0` and `CASTLE_PAID_BUDGET_USD=0` disable hosted calls even
with a server Key. These are **cumulative lifetime spending ceilings**, not funding
sources or monthly allowances. Increase only against revenue/sponsorship or an
intentional operator budget. A database restore can roll back the ledger; reconcile
with the provider before enabling hosted calls after restoring an old backup.

Before each upstream attempt, SQLite atomically checks and reserves a conservative
cost estimate, including retries. Visitor points reserve once per logical step.
At most two upstream attempts run; global concurrency defaults to three. Auth errors
are not retried. An unknown timeout keeps the full provider cost reserve, while
unfinished visitor points are refunded. On restart, unknown in-flight costs remain
reserved as expenditure and unfinished point reservations are refunded.

Successful calls store token counts, cache hits, latency and estimated cost; no
prompts or Keys enter expenditure tables. Job response text is cached for recovery
and removed on case deletion; standalone extraction has no accounting text cache.

Rates are conservative peak estimates checked 2026-09-22 against
[DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/). Input reserves
use UTF-8 bytes plus framing headroom; output uses `max_tokens`. Missing usage keeps
the full reserve. Update environment rates when prices change. Estimates are not
supplier invoices or a guarantee against price changes. Reconcile periodically.
Hosting, payment fees, refunds and support are additional costs.

Local-only operator commands, from the repository root:

```bash
backend/.venv/bin/python -m backend.app.admin costs
backend/.venv/bin/python -m backend.app.admin grant USERNAME 30 --reason 'Funded private test'
```

Granting points does not fund the provider or raise a budget. There is no public
grant endpoint. Subscriptions and recurring trial allowances are not enabled.

## Testing payments

Stripe hosted Checkout is the first test adapter. It accepts **test keys only**
and rejects live events. No live credentials, products or charges were created.
Setting `CASTLE_PAYMENT_MODE=live` does not enable real collection.

1. Create two one-time test Prices in your own Stripe sandbox; put IDs in
   `STRIPE_PRICE_DOSSIER` and `STRIPE_PRICE_HEARING`.
2. Set `CASTLE_PAYMENT_MODE=test`, `STRIPE_SECRET_KEY` (test), and
   `CASTLE_PUBLIC_URL` to the frontend URL. Model budgets may remain zero.
3. Forward test events: `stripe listen --forward-to localhost:8000/billing/webhook`.
4. Set its signing secret in `STRIPE_WEBHOOK_SECRET`, restart, log in and test a pack.
5. Refresh account balance; only sandbox points increase. Replay must not add points.

Prices and point counts come from the server, never the browser. Webhooks verify
raw-body HMAC signatures, timestamp tolerance, test mode, session/order match and
paid status. Both event IDs and order fulfillment are idempotent. Async successful
payments are supported; redirect URLs never credit a wallet. References:
[Checkout](https://docs.stripe.com/api/checkout/sessions/create),
[signature verification](https://docs.stripe.com/webhooks/signature).

Before live collection, select the merchant country/entity and provider, measure
representative costs, set prices/margins, add refund/dispute handling and account
recovery, and implement the live adapter. Subscription design should follow actual
repeat usage. Tests use synthetic provider responses and signed synthetic events;
they spend no API or payment money.

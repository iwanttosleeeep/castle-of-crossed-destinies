# Boundary regression and cost probes

## What this validates

The suite combines existing reference-chart comparisons with **synthetic boundary
and consistency checks**. Consistency tests do not independently establish the
correctness of every placement, tradition, ephemeris or date. No new personal
reports are used by this suite or the cost probe.

Run from the repository root:

```bash
npm --prefix engines ci
npm --prefix engines test
backend/.venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
```

Added coverage:

- All seven adapters: 1900/2099 support limits, a century leap day, both halves of
  a Chinese lunar leap month, longitude edges, northern/southern polar exclusions.
- BaZi / Zi Wei: 23:00 day rollover across a year boundary, no double date advance,
  and no leaked global convention settings when alternating calculations.
- Western / Jyotish: polar exclusions retain planet data but omit unvalidated axes.
- Jyotish: all 27 exact nakshatra boundaries, either side of each boundary, and
  equivalent 0° / ±360° / ±720° longitudes.
- Human Design: all 384 gate/line cells and both sides of every cell boundary.
- Numerology: separators, vowel-only and consonant-only names; missing components
  stay absent rather than becoming invented zero values.
- Dreamspell: 800 days across leap/year/Kin-cycle boundaries, with February 29
  outside the regular count under the existing disclosed convention.
- Civil time: 30-minute DST gaps/folds, a skipped civil date, quarter-hour offsets,
  and date-only systems that must not invent a birth instant.

The Jyotish boundary tests found and fixed an arithmetic bug: independently taking
floating-point modulo and division could select a new period's lord but the old
period's nearly exhausted balance. One normalized sector now supplies both values.
Numerical snapping is limited to 1e-12 of a sector, not an astrological orb.
The adapter provenance is now `castle-3`. Saved cases are **not** silently
recomputed or overwritten; generate a new case to use the changed adapter.

## Offline cost probe (default; no API calls)

The probe exercises the production job/gateway code using **only a synthetic
2000-01-01 birth fixture**. It uses a disposable database, not `CASTLE_DB_PATH`,
and removes that database at exit. It does not alter website accounts or budgets.

```bash
backend/.venv/bin/python -m backend.app.benchmark --scenario trial
backend/.venv/bin/python -m backend.app.benchmark --scenario full
backend/.venv/bin/python -m backend.app.benchmark --scenario full-hearing
```

Even if website/provider keys exist in the environment, these commands replace
the provider transport with synthetic output. Downstream prompts contain simulated
text of the lengths requested by the prompts. They do **not** measure real model
tokens, latency, caching, quality, retry probability, or average cost.

Illustrative offline results on 2026-09-23 using default peak-rate estimates:

| Scenario | Calls, before retries | Flash reserve sum (USD) | Pro reserve sum (USD) |
|---|---:|---:|---:|
| Two rooms + Tribunal | 3 | 0.015579 | 0.058773 |
| Seven rooms + Tribunal | 8 | 0.050297 | 0.194362 |
| Seven rooms + Tribunal + one seven-room hearing | 23 | 0.144141 | 0.580596 |

These are **illustrative dispatch-reserve sums, not measured costs, guaranteed
maximum bills, or recommended prices**. The input estimator conservatively uses
UTF-8 bytes and the output reservation uses max_tokens. Different model output,
retries, cache use or rates change the result. A probe can use
`--model deepseek-v4-pro`; Flash is default.

## Optional real sample (costs money)

Run the CLI in a **separate local terminal process**, not inside the web server.
Live mode requires both `--live` and an explicit `--max-usd` from 0.000001 to 5.
The dedicated key must be in `CASTLE_BENCHMARK_KEY`; the tool never falls back to
`DEEPSEEK_API_KEY` or reads a user's web session. Do not paste keys into chat or
commit them. For macOS zsh, use a hidden input (the key is not in shell history):

```zsh
read -rs 'CASTLE_BENCHMARK_KEY?Benchmark Key (hidden): '
export CASTLE_BENCHMARK_KEY
echo
backend/.venv/bin/python -m backend.app.benchmark \
  --live --scenario trial --samples 1 --max-usd 0.05
unset CASTLE_BENCHMARK_KEY
```

This explicitly permits real charges for one synthetic two-room sample, subject
to a 0.05 USD **estimated dispatch** ceiling. If a full conservative reservation
cannot fit, the call is refused before sending; a positive balance alone does not
guarantee completion. A price change can invalidate the estimate, so verify rates
before running. No one has run a real sample as part of this implementation.

The real-mode JSON includes per-attempt prompt/completion/cache tokens when
available, elapsed time, outcome, estimated cost, sample number, model/rates,
and engine/Skill version hashes. It never includes the key, prompt, or report
body. Unknown usage retains the conservative reserve and is explicitly marked;
it is not fabricated as zero tokens. Costs are peak-rate estimates, **not provider
invoices**. Repeated samples use new jobs rather than cached responses. A failed
sample stops subsequent samples; exit status 2 means incomplete work.

The current rates were checked against [DeepSeek's official pricing](https://api-docs.deepseek.com/quick_start/pricing/)
on 2026-09-23. Peak rates remain Flash 0.30 / 0.006 / 1.20 USD per million
uncached-input / cached-input / output tokens and Pro 1.32 / 0.044 / 3.96.
Environment overrides are shared with the production meter. Off-peak discounts
can make the supplier bill lower; don't treat a discount as a permanent margin.

## Before setting retail prices

1. Collect varied, consented or synthetic dossier lengths, not just this fixture.
2. Measure successful and failed attempts separately, including retries and cache
   hits. Keep incomplete sample costs in the operating-cost total.
3. Collect at least 20 complete samples before reporting a sample P95; even then,
   it is a descriptive sample statistic, not a stable population guarantee. The
   tool returns null below that count and for all offline probes.
4. Reconcile estimated costs against provider usage/billing. Add hosting, fees,
   taxes, refunds and support before deciding funding or prices.

No free allocation, subscriptions, retail price or live payment collection is
enabled by these tests or this tool.

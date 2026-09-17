# Buy or Wait?

**A deterministic personal-finance affordability engine that answers: "Can I safely afford this, and if not, what would make it safe?"**

![status](https://img.shields.io/badge/backend-deterministic%20Python-3ddc97) ![status](https://img.shields.io/badge/frontend-React%20%2B%20Vite-f2c14e) ![status](https://img.shields.io/badge/LLM%20calls%20at%20runtime-0-e8514c)

---

## 1. Problem

Most "can I afford this?" tools either check today's balance in isolation (ignoring rent, payday, and pending bills that are about to land) or hand the whole decision to an opaque model. Neither tells you *why* an expense is safe, *when* it becomes safe if it isn't yet, or *what specifically* you'd need to change to make it safe.

## 2. Solution

Buy or Wait? simulates a user's cash flow **90 days forward** from today — recurring income, recurring bills, pending/scheduled payments, and a conservative estimate of everyday essential spending — and finds the largest amount that can be paid **right now** without the projected balance ever dropping below a protected minimum. If a full payment isn't safe today, it looks for a safe installment plan, a two-payment partial plan, a later safe date, or — as a last resort — up to three flexible spending cuts (never touching protected categories) that would make paying today safe. Every recommendation is independently re-validated against the full 90-day forecast before it's shown.

## 3. Key features

- **Deterministic financial engine** — no LLM in the decision loop; every number is arithmetic over the user's own data.
- **90-day cash-flow simulation** with recurring-series detection (calendar-month aligned, so payday/billing dates don't drift) and continuous (not lumpy) essential-spending forecasting.
- **Five payment methods** ranked by the same tie-break rules every time: deadline compliance → no spending changes needed → lowest total cost → earliest start → fewest payments.
- **Message & image evidence parsing** — bilingual (EN/ID) regex extraction of salary/rent changes and pending/settled signals from free-text messages; receipt/payslip amounts resolved from a gitignored evidence sidecar (see §8) so no dataset-specific figures are ever committed.
- **What-if scenario analysis** — select real, eligible flexible-spending cuts (streaming, gym, dining, etc.) and get back a fully recalculated affordability decision from `POST /api/what-if`. This runs the *same engine pipeline* as `/api/decision` (`Pipeline.process_with_forced_changes`, see §13) — there is no parallel affordability logic in the frontend. Every number shown (safe-to-pay before/after, status, recommended plan) comes from that response.
- **A "Financial Control Room" UI** — a decision-first interface (not a generic card dashboard): a central affordability gauge, a composed signal strip, an SVG 90-day timeline, a payment-plan timeline, a what-if scenario panel, and a structured decision trail.
- **Synthetic demo data** — four fictional users you can try immediately, with no private data required.

## 4. Architecture

```
buy-or-wait/
├── backend/
│   ├── engine/                 # the financial decision engine (stdlib only)
│   │   ├── data_loader.py      #   CSV loading, currency conversion, normalization
│   │   ├── messages.py         #   evidence extraction from free text
│   │   ├── image_evidence.py   #   amount resolution for blank rows
│   │   ├── timeline.py         #   forward cash-flow construction
│   │   ├── forecast.py         #   90-day simulation + safety primitives
│   │   ├── payment_plans.py    #   candidate generation and ranking
│   │   ├── decide.py           #   output row + explanation rendering
│   │   └── pipeline.py         #   orchestration
│   ├── api.py                  # thin Flask API — no financial logic duplicated here
│   ├── main.py                 # CLI batch runner (same engine, CSV in/out)
│   ├── evaluation/             # structural + safety validator for generated output
│   ├── demo_data/              # synthetic CSVs + generator script
│   └── requirements.txt
├── frontend/                   # React + Vite "Financial Control Room" UI
├── docs/
│   ├── architecture.md         # the full request → recommendation pipeline
│   └── financial-logic.md      # every financial rule, its rationale and its test
├── examples/
│   └── simple_household/       # 15-event synthetic example you can trace by hand
├── tests/                      # pytest suite (synthetic fixtures only)
├── local_evidence/             # gitignored: human-verified image transcriptions
├── .gitignore
└── README.md
```

The dependency direction is strictly inward: `frontend → api → engine`, and `main.py → engine`. Nothing in `engine/` imports from `api.py`, and the engine requires nothing beyond the Python standard library (`pytesseract`/`Pillow` are optional, imported lazily only inside the OCR fallback) — which is why the whole decision engine is testable without Flask or any other dependency installed.

**Further reading:** [`docs/architecture.md`](docs/architecture.md) for the end-to-end pipeline and the design decisions behind it; [`docs/financial-logic.md`](docs/financial-logic.md) for a rule-by-rule reference; [`examples/simple_household/`](examples/simple_household/) for a worked example.

The frontend never computes a recommendation — it only renders whatever `backend/api.py` returns, which in turn only calls `backend/engine/*`. This includes the what-if scenario panel: it sends the user's selected changes to `POST /api/what-if` and displays exactly what comes back, with no client-side affordability math of its own (see §13 for the endpoint and §3 for the feature).

## 5. Financial decision methodology

1. **Starting point.** `financial_profiles.current_available_balance` is treated as the balance *as of* the request/decision date. Historical data is used only to detect patterns, never re-summed into the balance.
2. **Forward cash flow** is built from three sources:
   - Explicit future rows: debits are always reserved; credits only count once `scheduled` (confirmed) — pending credits, bonuses, refunds, and windfalls are excluded until settled.
   - Recurring series (rent, utilities, salary, subscriptions, etc.) detected from history and projected forward calendar-month-aligned, so a payday on the 15th stays on the 15th.
   - Variable essential spending (groceries, transport, dining, healthcare, shopping) is spread as a continuous daily debit at the recent historical average, rather than one misleading lump sum per month.
3. **Safety check.** The full day-by-day balance trace must stay at or above `minimum_balance_to_keep` for the entire 90-day window.
4. **`amount_safe_to_pay` and `earliest_date_for_full_payment`** are computed once from this *base* forecast, before any spending changes — they describe raw capacity, independent of which plan is ultimately recommended.

## 6. 90-day forecast explanation

See the `/api/forecast/<user_id>` endpoint and the Timeline component: it returns the running daily balance for the next 90 days (a "checkpoint" at every date something changes), plus the lowest point the balance is ever projected to reach. The frontend timeline plots this line, marks the protected minimum, and highlights the lowest point so it's visually obvious *why* a decision is or isn't safe.

## 7. Payment-plan logic

Five candidate types are evaluated per request: full payment today, full payment today enabled by spending changes, each supplied installment option, a two-payment partial plan, and waiting until the earliest safe date. Every candidate is independently re-simulated against the full 90-day forecast (not just checked at its first payment) before being considered eligible. Eligible candidates are ranked by: (1) completes by the deadline, (2) needs no spending changes, (3) lowest total amount paid, (4) starts earliest, (5) fewest payments, (6) lowest payment-option id as a final tie-break.

## 8. Message/image evidence handling

Messages and images are treated as **untrusted evidence**, not instructions — nothing in their text can override the financial safety rules. Only concrete facts stated plainly are extracted:
- A new salary/rent figure and its effective date (falling back to the message's `sent_at` date if no explicit date is given in the text).
- A contract/income stream ending.
- A specific transaction being flagged pending/unsettled or an internal self-transfer (net-zero).

Some financial events carry a blank `amount` — the figure exists only on a linked receipt, payslip or invoice image. `backend/engine/image_evidence.py` resolves these in a fixed order:

1. **An evidence sidecar** — a JSON file mapping `event_id` to a human-verified amount, optionally with the currency and the exact document field it was read from, so every transcription is auditable. It is looked up at `$BUY_OR_WAIT_IMAGE_EVIDENCE`, then `<dataset_dir>/image_evidence.json`, then `local_evidence/image_evidence.json`.
2. **OCR fallback** — `pytesseract` + `Pillow`, preferring grand-total-style labels, for images with no sidecar entry.
3. **A hard error** — `EvidenceResolutionError`.

A blank amount is **never** treated as zero: a vanished debit understates the drain and could make an unsafe payment look safe, which is exactly the failure this system exists to prevent. A currency declared in the sidecar is checked against the event row, so a transcription slip raises rather than silently converting.

The sidecar lives **outside version control** (see `.gitignore`), so dataset-specific figures are never committed — the engine ships as general logic, not as a lookup table of answers.

## 9. Tech stack

- **Backend:** Python 3, Flask, Flask-CORS, gunicorn (production WSGI server — see §17). No database — the demo runs entirely from CSVs, in memory.
- **Frontend:** React 18 + Vite, plain CSS (no UI framework, no charting library — the gauge and timeline are hand-built SVG).
- **Tests:** pytest, synthetic fixtures only.
- **No paid APIs, no API keys, no GPU, no Docker, no cloud infrastructure required.**

## 10. Local setup

```bash
git clone <this-repo>
cd buy-or-wait-portfolio
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
```

## 11. Running the backend

```bash
python3 backend/api.py
# Serves http://127.0.0.1:5001, seeded with the synthetic demo dataset.
```

This runs Flask's built-in dev server, which is fine for local use. In production,
run it behind `gunicorn` instead (already in `backend/requirements.txt`):

```bash
cd backend
gunicorn -w 2 -b 0.0.0.0:$PORT api:app
```

This is the exact command used in the Render deployment steps in §17. It reads
three optional environment variables:

| variable | default | purpose |
|---|---|---|
| `PORT` | `5001` | port the API listens on (most PaaS providers set this for you) |
| `FLASK_DEBUG` | `0` | set to `1` to enable the interactive debugger/auto-reload locally; never set this in production |
| `ALLOWED_ORIGINS` | `*` (any origin) | comma-separated list of exact origins allowed to call the API cross-origin, e.g. `https://buy-or-wait.vercel.app`. Leave unset for local development and for a quick deploy; set it once your frontend has a stable URL (see §17 Part C) |

## 11b. Running the batch CLI

The engine also runs headlessly over a requests CSV, producing an output CSV in the exact challenge schema. With no arguments it runs against the bundled synthetic demo data, so it works out of the box:

```bash
python3 backend/main.py
```

Against any other dataset directory:

```bash
python3 backend/main.py \
  --requests  path/to/requests.csv \
  --out       output.csv \
  --dataset-dir path/to/dataset
```

| flag | default | purpose |
|---|---|---|
| `--requests` | `backend/demo_data/requests.csv` | requests CSV to process |
| `--out` | `demo_output.csv` | where to write the output CSV |
| `--dataset-dir` | `backend/demo_data` | directory holding the profile/event/rate CSVs |

Then validate whatever it produced:

```bash
python3 backend/evaluation/main.py --dataset-dir path/to/dataset --output output.csv
```

### Worked example

A small, fully synthetic example lives in `examples/simple_household/` — one user, 15 events, hand-traceable:

```bash
python3 backend/main.py \
  --dataset-dir examples/simple_household \
  --requests    examples/simple_household/requests.csv \
  --out         /tmp/example_output.csv
```

It produces a two-leg partial payment whose second leg lands exactly on payday — a date derived from the forecast, not chosen. See [`examples/simple_household/README.md`](examples/simple_household/README.md) for the walkthrough, including what changes when the pending refund is marked settled.

## 12. Running the frontend

```bash
cd frontend
npm run dev
# Opens http://127.0.0.1:5173 — proxies /api to the Flask server above.
```

With both running, open the frontend, pick a demo user, and try an expense.

When the frontend and backend are deployed to **different** hosts (see §17 Deployment), set `VITE_API_BASE_URL` (copy `frontend/.env.example` to `frontend/.env`) to the deployed backend's full API URL before running `npm run build`. Locally you can leave it unset — Vite's dev proxy handles `/api` for you.

## 13. API overview

All endpoints are served by `backend/api.py` and return JSON. None of them accept or require an API key.

| method | path | purpose |
|---|---|---|
| `GET` | `/api/health` | liveness check + demo anchor date + user count |
| `GET` | `/api/users` | list of demo user ids |
| `GET` | `/api/profile/<user_id>` | financial profile (balance, protected minimum, income, categories) |
| `GET` | `/api/forecast/<user_id>` | 90-day daily balance projection + lowest point |
| `POST` | `/api/decision` | submit a purchase (`user_id`, `item`, `amount`, `currency`, `days_until_needed`, `allows_partial_payment`) and get back the real engine's affordability decision, payment plan, and decision trail |
| `POST` | `/api/what-if` | same fields as `/api/decision`, plus `changes`: a list of `{"category": "...", "action": "stop"|"reduce"}`. Returns `baseline` (no changes), `scenario` (changes applied), `applied_changes` (which of the requested changes were actually eligible, with the real event and amount freed), and `comparison` (before/after safe-to-pay, status, method, and their numeric difference — computed server-side) |
| `GET` | `/api/history` | every decision made this server session, most recent first (what-if calls are never recorded here — they're hypothetical, not decisions) |
| `GET` | `/api/history/<id>` | a single past decision by id |

Every `POST /api/decision` and `POST /api/what-if` call runs the full pipeline (`backend/engine/pipeline.py`) against the user's real demo data — there is no cached or scripted response. `/api/what-if` does not duplicate the decision algorithm: it calls `Pipeline.process_with_forced_changes`, which applies the requested changes to the timeline *before* the forecast is built, then runs the identical candidate-generation → safety-validation → ranking path as a plain decision. A category the user selects that has no matching real event in their timeline (e.g. a "reducible" category with no anchored event, only synthesized daily spend) is silently excluded from `applied_changes` rather than fabricated.

### What-if example

```bash
curl -X POST http://localhost:5001/api/what-if \
  -H 'Content-Type: application/json' \
  -d '{
        "user_id": "demo_sam", "item": "Bike repair", "amount": 550, "currency": "USD",
        "days_until_needed": 30, "allows_partial_payment": true,
        "changes": [{"category": "gym", "action": "stop"}]
      }'
```

returns (abridged) something like:

```json
{
  "applied_changes": [{"category": "gym", "kind": "stop", "event_id": "demo_event_104", "freed_amount": 135.0}],
  "comparison": {
    "amount_safe_to_pay_before": 496.88, "amount_safe_to_pay_after": 513.61,
    "difference": 16.72, "changed": false,
    "affordability_status_before": "affordable_later", "affordability_status_after": "affordable_later",
    "recommended_payment_method_before": "wait", "recommended_payment_method_after": "wait"
  }
}
```

Note that a cut doesn't always flip the recommendation — here it raises headroom by 16.72 but the gym payment happens to fall *after* the forecast's tightest point, so it isn't enough to change the plan. That's the engine being honest, not the feature failing: `comparison.changed` tells the frontend exactly when the recommendation itself moved, separately from the numeric difference.

## 14. Synthetic demo usage

Four fictional users ship with the repo (`backend/demo_data/`), generated by `backend/demo_data/generate_demo_data.py` — none of the numbers come from any private dataset:

| user | currency | balance | protected minimum | notable trait |
|---|---|---|---|---|
| `demo_alex` | USD | 6,200 | 1,500 | comfortable — most purchases are `BUY NOW` |
| `demo_sam` | USD | 1,850 | 900 | tight budget — often needs to `WAIT` |
| `demo_jordan` | EUR | 980 | 700 | close to minimum — good for `DON'T PROCEED` / cross-currency demos |
| `demo_priya` | USD | 1,200 | 600 | biweekly paycheck — good for `BUY WITH PLAN` (partial-payment) demos |

The seeded history already contains one example of each of the four affordability outcomes, computed by the real engine (not scripted): `demo_alex`'s $900 laptop is `BUY NOW`, `demo_sam`'s $650 dental bill is `WAIT`, `demo_jordan`'s €500 flight is `DON'T PROCEED`, and `demo_priya`'s $900 e-bike is `BUY WITH PLAN` (a two-payment partial plan). Try your own amounts for any user from the "Decide" tab — every result is recalculated live by `backend/engine/`.

## 15. Testing

```bash
python3 -m pytest tests/ -v
```

118 tests cover: safe-amount calculation, minimum-balance protection, recurring income/expense projection, pending vs. settled payments, cancelled/unrealized exclusion, installment safety and duration limits, delayed payment, flexible spending-change search (including protected-category and minimum-allowed-amount respect), message-derived salary/rent evidence (including the "no explicit date" fallback and pending-bonus exclusion), image-evidence resolution (sidecar, bare-number entries, currency-mismatch rejection, never-default-to-zero, and end-to-end blank-amount loading), currency conversion (direct and inverse), calendar-month edge cases (end-of-month clamping, leap years, year boundaries, rent-date drift), continuous essential-spend forecasting, cumulative multi-leg drain, pipeline determinism, the output validator itself, and API-level invalid-input handling — all against synthetic fixtures, never the private challenge data.

The engine depends only on the standard library; the API tests skip automatically if Flask is not installed, so the suite runs anywhere.

The what-if feature specifically is covered at two levels: `tests/test_what_if.py` exercises the engine primitives directly (`changes_for_category_actions`, `Pipeline.process_with_forced_changes`) with synthetic fixtures proving a purchase can flip from `not_affordable` to `affordable_with_plan`, that a user's specific category choice is honoured over whatever the automatic search would have picked on its own, and that forced changes correctly merge with any further automatic search on top; `tests/test_api.py` covers the HTTP layer — malformed `changes` payloads, unrecognized categories, cross-currency scenarios, and confirming what-if never writes to decision history.

## 16. Evaluation methodology

`backend/evaluation/main.py` validates any generated output CSV against its requests CSV in two passes. Neither pass compares against expected labels — the validator re-derives correctness independently, so it is just as usable on unseen data.

**Pass 1 — structure and coherence.** Schema/header match, duplicate or missing request IDs, unexpected IDs, enum validity, real calendar dates, well-formed `payment_plan` and `spending_changes_needed` strings, payment totals matching the requested amount, and cross-field coherence: `not_recommended` must carry no plan and must pair with `not_affordable`; `partial_payment` needs exactly two legs and `installments` at least two; plan dates must be chronological, positive, and never before the request date; `affordable_now` cannot simultaneously require spending changes; at most three changes.

**Pass 2 — safety re-simulation.** Every recommended plan is replayed against a *freshly rebuilt* 90-day forecast, with the row's own claimed spending changes applied, and rejected if the balance ever breaches the user's minimum. Installment spans are checked against `max_installment_months`, and recommended methods against what the user actually accepts.

```bash
python3 backend/evaluation/main.py                 # structure + safety
python3 backend/evaluation/main.py --skip-safety   # structure only
```

The safety pass is tested against deliberately corrupted output: forcing every demo request to full payment on the request date is correctly rejected for breaching the minimum balance.

## 17. Deployment

This project deploys to entirely free tiers, no credit card required. Frontend and
backend deploy as two separate services. Follow both parts in order — the backend
first, since the frontend needs its URL.

### Part A — Deploy the backend (Render)

1. Push this repository to GitHub (see §7 for exactly what to commit).
2. Go to [render.com](https://render.com), sign up (free, no card required), and click
   **New +** → **Web Service**.
3. Connect your GitHub repository.
4. Fill in these exact fields:

   | Field | Value |
   |---|---|
   | **Root Directory** | `backend` |
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn -w 2 -b 0.0.0.0:$PORT api:app` |
   | **Instance Type** | Free |

5. You do not need to set a `PORT` environment variable — Render sets it
   automatically, and the start command above reads it.
6. Click **Create Web Service**. Wait for the build to finish (a couple of minutes).
7. Once live, copy the URL Render gives you, e.g. `https://buy-or-wait-api.onrender.com`.
   Test it by opening `https://buy-or-wait-api.onrender.com/api/health` in a browser —
   you should see `{"status": "ok", ...}`.

No database, no API keys, and no paid add-ons are needed — the demo dataset ships in
the repo and loads from CSV at process start.

*(Render's free tier sleeps a service after 15 minutes of inactivity; the first
request after a sleep takes 30–60 seconds to wake it up. This is a free-tier
limitation, not a bug in the app.)*

### Part B — Deploy the frontend (Vercel)

1. Go to [vercel.com](https://vercel.com), sign up (free, no card required), and click
   **Add New** → **Project**.
2. Import the same GitHub repository.
3. Fill in these exact fields:

   | Field | Value |
   |---|---|
   | **Root Directory** | `frontend` |
   | **Framework Preset** | Vite |
   | **Build Command** | `npm run build` |
   | **Output Directory** | `dist` |

4. Before deploying, add one **Environment Variable**:

   | Name | Value |
   |---|---|
   | `VITE_API_BASE_URL` | the backend URL from Part A, step 7, with `/api` on the end — e.g. `https://buy-or-wait-api.onrender.com/api` |

5. Click **Deploy**. Wait for the build to finish.
6. Open the URL Vercel gives you — the app should load, list the four demo users,
   and let you submit a purchase and see a real recommendation.

(Netlify works identically: Root directory `frontend`, build command `npm run
build`, publish directory `dist`, and the same `VITE_API_BASE_URL` environment
variable, set under Site settings → Environment variables.)

### Part C — Lock down CORS (optional but recommended)

By default the backend accepts requests from any origin (`ALLOWED_ORIGINS` is
unset), so Part B works with zero extra configuration. Once your frontend is live,
you can optionally restrict the backend to only that origin:

1. In Render, open your backend service → **Environment** tab.
2. Add environment variable `ALLOWED_ORIGINS` = your Vercel/Netlify URL exactly as
   shown in the browser (e.g. `https://buy-or-wait.vercel.app`, no trailing slash).
   Multiple origins can be comma-separated.
3. Render redeploys automatically. Your frontend continues to work; requests from
   any other origin are now rejected by the browser's CORS check.

This step is optional because nothing sensitive is exchanged over this API (no
login, no secrets, no user data beyond the synthetic demo) — skip it if you'd
rather keep the zero-configuration default.

### Running everything locally instead

If you just want to try it without deploying anywhere, skip both parts above and
follow §10 (backend) and §12 (frontend) — no environment variables are needed for
local use.

## 18. Free-tier architecture

Every piece of this project was deliberately chosen to require $0 and no credit card:

- **No paid AI API.** The "intelligence" is `backend/engine/` — deterministic Python arithmetic over the user's own data, not a call to OpenAI/Anthropic/Gemini or any other paid model.
- **No database.** The demo reads synthetic CSVs into memory at startup; decision history lives in the Flask process's memory for the session. This removes an entire category of paid infrastructure (managed Postgres, Mongo Atlas, etc.) at the cost of history not surviving a restart — an explicit, documented trade-off (see §20 Limitations).
- **No paid hosting requirement.** Static frontend hosts (Vercel/Netlify/GitHub Pages) and small Python-service hosts (Render/Railway/Fly.io) all offer tiers that comfortably fit this app's footprint.
- **No build-time or runtime secrets.** There is nothing to rotate, leak, or pay for — `grep -ri "api[_-]key\|secret"` across the repo returns nothing but this sentence.

## 19. Design decisions

- **"Financial Control Room," not a SaaS dashboard.** The UI is built around one central decision (the affordability gauge) with a supporting signal strip, payment-plan timeline, and decision trail — deliberately avoiding a generic sidebar-plus-cards template, gradient hero sections, or decorative charts that don't map to real numbers.
- **Monospace for numbers and labels, sans-serif for prose.** IBM Plex Mono is used for anything numeric or system-like (amounts, dates, status pills, tab labels); Inter is used for sentences (the decision explanation, the what-if scenario copy) — a common fintech-terminal convention that keeps dense numeric UI legible.
- **Dark, low-chroma palette with one accent color.** A single green (`--accent`) means "safe/positive" everywhere it appears (gauge fill, buy-now pill, CTA button); amber/orange/red are reserved for degrees of caution — so color always carries the same meaning across every screen.
- **No fake interactivity.** Every control that looks interactive (the what-if scenario chips and Recalculate button, the history filters, the payment-plan steps) is wired to a real backend call or genuine client-side derived state — nothing is a static mockup, and nothing labeled "preview" silently does less than it appears to. Anything that couldn't be made genuinely functional within scope was removed rather than left as a decorative stub.

## 20. Limitations

- The engine is a best-effort deterministic reconstruction validated against a small labelled sample of the original challenge data; exact-cent numeric precision on unseen data is not guaranteed, though the categorical decision (buy now / with a plan / wait / don't proceed) and safety invariants are.
- Message parsing is regex/keyword-based over two languages (English, Indonesian) matching the patterns seen during development — it will not generalize to arbitrary free text or other languages without extending the keyword lists.
- The demo API keeps decision history in memory only (resets on restart) — there's no database, by design, to stay dependency-free.
- What-if can only offer categories that are (a) in the user's `flexible_stop_categories`/`flexible_reduce_categories` and (b) anchored to a real, dated event in that user's timeline. A category like "dining" that's only ever synthesized as continuous daily essential spend (no single event_id to attach a cut to) won't appear as a selectable option, even if the profile lists it as reducible.
- What-if applies exactly the changes the user selects, with no cap — unlike the automatic search behind a plain decision, which stops at 3 changes by design (see `docs/financial-logic.md` §13). A resulting `spending_changes_needed` *display string* elsewhere in the system still truncates at 3 for CSV-schema compatibility, but `/api/what-if`'s own `applied_changes` field is never truncated.

## 21. Future improvements

- Persist demo history to a local SQLite file (still zero external dependencies) instead of in-memory state.
- Extend message-evidence parsing to more languages/patterns.
- Add a "compare two expenses" view.
- Add CSV/JSON export from the History screen.
- Let what-if scenarios be saved and compared side by side (currently only one scenario is live at a time).

## 22. Screenshots

_Add screenshots here after running the app locally:_

- `docs/screenshot-decide.png` — the main decision screen with the gauge, timeline, and decision trail
- `docs/screenshot-plan.png` — a payment-plan-in-progress view
- `docs/screenshot-profile.png` — the financial profile view
- `docs/screenshot-history.png` — the history view

## 23. License / usage note

This is a personal portfolio project built to demonstrate a financial-decision engine and full-stack integration. It uses only synthetic, invented demo data — see `backend/demo_data/generate_demo_data.py`. It is not financial advice and is not affiliated with any bank, employer, or the original hackathon that inspired the underlying engine.

## 24. Honesty note on origin

This project's financial engine (`backend/engine/`) began as a solution to a private hackathon dataset ("HackerRank Orchestrate", September 2026). That dataset is **not** included in this repository — it is excluded by `.gitignore` and was only ever used locally for evaluation (see §16 Evaluation methodology). Everything committed here — the demo data, the API, the frontend, and the tests — is original work built specifically for this portfolio version, using only synthetic data.

## 25. No LLM/VLM at runtime

To be explicit, since this matters for anyone reviewing the code: **the running application makes zero calls to any LLM or vision model.** `backend/engine/` is deterministic Python — arithmetic, date logic, and regex — and `backend/api.py` calls nothing but that engine. The only place a multimodal model was ever used was during original development, to transcribe a set of static receipt images once. Those transcriptions are data, not code: they live in a gitignored evidence sidecar outside this repository, and `image_evidence.py` ships only the general resolution logic (sidecar lookup → optional local OCR → hard error). No model is called at request time, and no dataset-specific amounts are committed.

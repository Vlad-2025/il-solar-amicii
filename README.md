# Asistent Prosumator (Prosumer Bill & Solar Assistant)

Hosted web app for Romanian household prosumers. It explains electricity bills line by line, checks them
against the user's own inverter data, predicts solar production and consumption for their exact roof, and
pushes a personalised note to their phone when the compensation rules change.

Built for AI Validation Bootcamp, Challenge 1. Interface in Romanian; code and docs in English.

## Run it

```bash
./install.sh                         # Ubuntu/Debian/Fedora/Arch: system packages, Tesseract + Romanian, venv
source .venv/bin/activate
streamlit run app/Home.py            # http://localhost:8501
```

No configuration is needed locally: without `DATABASE_URL` the app uses SQLite in `data/app.db`, and on first
start it creates a **demo account** with a year of data and trained models (about 30 seconds).
Click **"Intră în contul demo"** or log in as `demo@prosumer.demo` / `demo1234`.

With Docker instead (Postgres + app, mirrors production):

```bash
docker compose up -d                 # http://localhost:8501
```

## What is where

| Folder | What it does |
| --- | --- |
| `app/` | Streamlit UI. `Home.py` is the entry point and router; one file per page in `app/pages/`. |
| `engine/` | Forecasts. `weather.py` (Open-Meteo), `solar.py` (pvlib physics), `calibrate.py` (learned correction + P10/P90), `load.py` (consumption), `combine.py` (battery, export/import, month estimate), `pvgis.py`, `pipeline.py` (end to end). |
| `bills/` | Bill parsing. `parse.py` runs: detect → `pdf_text.py` or `ocr.py` → `suppliers/` → `validate.py`. `check.py` compares with inverter data, `complaint.py` drafts the request to the supplier. |
| `rules/` | `versions/*.yaml` one file per rule version; `compensation.py` (monthly quantity compensation); `explain.py` (Romanian explanations, change notes). `staged/` holds the DEMO rule for the stage demo. |
| `ingest/` | Inverter exports: `detect.py` (read CSV/XLSX/JSON, guess columns), `normalize.py` (hourly UTC kWh), `mappers/` (known formats), `demo.py` (synthetic demo household). |
| `alerts/` | `ntfy.py` push, `rules_publish.py` (publish a rule, personalised notes per user). |
| `billing/` | Stripe Checkout, test mode only. |
| `db/` | `models.py` (tables), `repo.py` (queries), `client.py` (SQLite or Postgres), `seed.py` (demo account), `schema.sql` (generated). |
| `jobs/` | Scheduled jobs run by GitHub Actions: `refresh_forecasts.py`, `rule_alerts.py`, `anre_watch.py`. |
| `scripts/` | `make_demo_bill.py`, `make_demo_data.py`, `seed_demo.py`, `dump_schema.py`. |
| `data/demo/` | Demo bill (PDF + phone photo) from a fictional supplier, demo inverter export (CSV). |

`engine/`, `bills/`, `rules/`, `ingest/` never import Streamlit, so a FastAPI backend for the Expo app can wrap them unchanged.

## Deploy (all free tiers)

1. **Supabase**: create a project. Copy *Project settings → Database → Connection string → Session pooler*
   (IPv4; the direct connection is IPv6-only and won't work from Streamlit Cloud or GitHub Actions).
   Tables are created by the app on first start; or paste `db/schema.sql` into the SQL editor.
2. **Stripe** (stay in test mode): create product "Premium" with a recurring monthly price in RON; copy the
   price ID (`price_...`) and the test secret key (`sk_test_...`).
3. **Streamlit Community Cloud**: New app → this repo, branch `main`, main file `app/Home.py`.
   Paste the secrets from `.streamlit/secrets.toml.example` (at least `DATABASE_URL`, `APP_URL`, `APP_SECRET`,
   `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`). `packages.txt` installs Tesseract with Romanian.
4. **GitHub Actions**: `gh secret set DATABASE_URL` (same pooler string), `gh secret set TEAM_NTFY_TOPIC`,
   and `gh variable set APP_URL`, `gh variable set ANRE_WATCH_URL` (the ANRE prosumer page to watch).
5. Fallback host if Streamlit Cloud runs out of memory: Hugging Face Spaces, Docker SDK, using `Dockerfile`.

## Scheduled jobs

| Workflow | When | What |
| --- | --- | --- |
| `forecasts.yml` | daily 03:17 UTC | 7-day forecast for every site; retrains models older than 7 days on Mondays |
| `rules.yml` | push to `rules/versions/**` on main | loads new rule versions, pushes a personalised ntfy note to each affected user |
| `anre.yml` | daily | hashes the ANRE page, alerts the team on change (a human writes the new rule) |
| `ci.yml` | every push | ruff + pytest |

Adding a rule version: copy the newest file in `rules/versions/`, change `id`, `version`, `effective_from`,
`params`, `summary_ro`, set `source_url`, open a PR, merge. Users get their note within minutes.

## Demo script (3 minutes)

1. Open the hosted URL, click **Intră în contul demo** (Bucharest, 6 kWp, 5 kWh battery, a year of data).
2. **Facturi** → upload `data/demo/factura_demo_2026-09.pdf` (or the phone photo). Confirm: every line gets a
   plain explanation, the energy balance appears, and the "why isn't my bill zero" note.
3. **Abonament** → subscribe with test card 4242 4242 4242 4242 (or the demo unlock if Stripe isn't configured).
   Back on **Facturi**: "delivered energy differs from your inverter by −11.5%, worth checking", plus the
   pre-filled request to the supplier.
4. **Prognoză** → next 7 days for that roof with the uncertainty band, consumption, and the predicted bill for
   this month; accuracy versus "physics only" and "same hour yesterday".
5. **Reguli & alerte** → subscribe the phone to the ntfy topic, press **Simulează o schimbare de lege (DEMO)**:
   the phone buzzes with a personalised note.

Before the pitch: open the URL once (free hosts sleep), and run `python scripts/make_demo_data.py` on a machine
with internet so the downloadable demo export uses real Bucharest weather.

## Tests

```bash
pytest -q
```

## Known limits and open questions

- **Compensation details are unverified**: how long surplus kWh stay valid and whether network tariffs apply to
  compensated kWh. Checks say "worth checking" and every rule file has `verified: false` until someone reads the
  law text and the ANRE methodology.
- **Supplier templates**: only the generic extractor and the fictional demo supplier exist. Collect one real bill
  per supplier the interviewees use and add a template in `bills/suppliers/`.
- **Inverter formats**: only the demo format is recognised automatically; others go through manual column mapping.
  Add a detector in `ingest/mappers/` from each real export you collect.
- **Demo data is synthetic** (a modelled Bucharest house). Replace it with OPSD household data or real exports.
- **Typical consumption profile** in `engine/load.py` is a placeholder until replaced by a measured one.
- **Weather accuracy bounds the forecast**: good for 1–2 days, weaker by day 5–7. Open-Meteo's free API is
  non-commercial; a real launch needs their paid plan.
- **Auth** is a simple email + password table (PBKDF2). Use Supabase Auth before handling real users at scale.

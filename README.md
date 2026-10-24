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
| `api/` | FastAPI service for the mobile app (`uvicorn api.main:app`); same database and domain code as the web app. |
| `mobile/` | Android app (Expo SDK 58, TypeScript). See `mobile/README.md`. |
| `app/` | Streamlit UI. `Home.py` is the entry point and router; one file per page in `app/pages/`. |
| `engine/` | Forecasts. `weather.py` (Open-Meteo), `solar.py` (pvlib physics), `calibrate.py` (learned correction + P10/P90), `load.py` (consumption), `combine.py` (battery, export/import, month estimate), `pvgis.py`, `pipeline.py` (end to end). System planner: `profiles.py` (Romanian standard household load profiles, `data/psc_*.csv`), `devices.py` (device catalogue and hourly device load), `demand.py` (yearly baseline), `planner.py` (sizing + payback), `plan_service.py` (loads a site's data, caches the result). |
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

## System planner (Plan sistem)

Web page **Plan sistem** and mobile screen **Plan sistem** (premium). The user lists the devices they have or plan
to buy (catalogue of 15: fridge, washer, boiler, AC, heat pump, EV, …). The planner says how many panels and
battery modules to add, or what to install from zero when the profile says 0 kWp, and when that pays back.

**Objective.** Maximum efficiency means using all the solar energy at home, storing the excess and minimising
what is bought from **and** sold to the grid. The planner tries every combination of panels added
(0…`max_panels`) × battery modules added (0…`max_battery_modules`) on an hourly simulation of the last
365 days, and picks the one with the lowest *bought + sold* energy. A combination only counts if:

- its last panel lowers bought + sold (a panel that mostly gets exported is not added);
- its last battery module lowers bought + sold **and** cycles at least `min_cycles` (150) full cycles a year,
  so it isn't sitting mostly empty.

Ties go to the smaller system. The result lists the neighbours (±1 panel, ±1 module) and why it stopped.

**Demand baseline**, best source first, always labelled on screen:

1. the household's own inverter data for a full year (≥ 90 % of the last 365 days);
2. own data for at least 14 days, scaled with the standard profile to a year;
3. the yearly kWh the user typed in;
4. confirmed bills (only without panels: with panels the bill shows only the grid part);
5. the monthly consumption from the profile × 12;
6. 2,400 kWh/year, labelled as an assumption.

Or *devices only*: the baseline is built from the device list plus 50 W standby. The hourly shape comes from
the **standard household load profiles (PSC)** of Distribuție Energie Electrică România, measured in 2019, urban
and rural, working/non-working days, cold/warm season
([urban](https://distributie-energie.ro/wp-content/uploads/2024/08/Profil-specific-de-consum-PSC-tip-Casnic-Zona-Urban.pdf),
[rural](https://distributie-energie.ro/wp-content/uploads/2024/08/Profil-specific-de-consum-PSC-tip-Casnic-Zona-Rurala.pdf)).
The "day-time user" and "night-time user" profiles reshape that curve (×1.4 or ×0.6 for 08–16 h). They are
assumptions, not measured profiles, and the app says so.

**Production** uses the last 365 days of weather for the site with the forecast model (physics + learned
correction), calibrated to the inverter's real production when there is any. Without internet access the
planner falls back to a clear-sky model and says so.

**Money.** These are the starting prices, VAT included. Every one is editable and should be replaced with an
installer's quote:

| Item | Price |
| --- | --- |
| Panels | 4,500 lei/kWp |
| Battery | 1,200 lei/kWh + 2,000 lei installation |
| Hybrid inverter | 5,500 lei when added to an existing system, 3,500 lei extra for a new one |

The panel price puts a new 5 kWp system at about 26,000 lei, at the low end of the 25,000–35,000 lei turnkey
range [reported in March 2026](https://playtech.ro/2026/cat-costa-sa-instalezi-panouri-solare-pentru-o-casa-de-100-mp-simulare-de-preturi/).

**Casa Verde Baterii** is optional: 75 % of eligible costs, at most 15,000 lei, eligible costs capped at
1,500 lei/kWh, minimum 10 kWh of storage. Existing prosumers may apply. The guide was signed 11 Sep 2026 and
enrolment dates are not yet announced
([alba24](https://alba24.ro/ghidul-pentru-baterii-a-fost-semnat-cine-poate-primi-bani-si-cum-se-face-punctajul-cand-incep-inscrierile-la-afm-1157555.html)).

The savings come from bills recomputed month by month with the compensation rule in force, plus:

- 0.5 %/year panel degradation;
- battery replacement after min(15, 6000 ÷ cycles per year) years;
- a 25-year horizon.

Because the quantity-compensation rule is time-limited, payback is shown under three scenarios:

| Scenario | What it assumes |
| --- | --- |
| Current | Current rules continue |
| Partial | After 2030, exported kWh are worth 30 % (editable) |
| None | After 2030, exported kWh are worth nothing |

Batteries usually only pay off in the last two. The planner also shows the payback of the system the user
already has (if they enter its cost), and suggests moving flexible devices (washer, dishwasher, EV charging) to
the sunniest hours.

**API:**

| Endpoint | What it does |
| --- | --- |
| `GET /plan/catalog` | Device catalogue |
| `GET /plan/settings`, `PUT /plan/settings` | Planner settings |
| `GET /devices`, `POST /devices`, `PUT /devices/{id}`, `DELETE /devices/{id}` | The user's devices |
| `POST /plan?force=` | Runs the planner; results are cached for 15 minutes |

**Tables:** `devices`, `plan_settings`.

## Mobile app

`mobile/` is an Expo app (Scan bill, Forecast, Alerts, Account) talking to the FastAPI service in `api/`.
Run the API with `pip install -r requirements-api.txt && uvicorn api.main:app --host 0.0.0.0 --port 8000`,
then `cd mobile && npm install && npx expo start` and open it in Expo Go. Deploy the API to Hugging Face
Spaces with `Dockerfile.api`, and build an APK with `npx eas-cli build -p android --profile preview`.
Details in `mobile/README.md`.

## Scheduled jobs

| Workflow | When | What |
| --- | --- | --- |
| `forecasts.yml` | daily 03:17 UTC | 7-day forecast for every site; retrains models older than 7 days on Mondays |
| `rules.yml` | push to `rules/versions/**` on main | loads new rule versions, pushes a personalised ntfy note to each affected user |
| `anre.yml` | daily | hashes the ANRE page, alerts the team on change (a human writes the new rule) |
| `ci.yml` | every push | ruff + pytest; mobile typecheck, lint, tests |

Adding a rule version: copy the newest file in `rules/versions/`, change `id`, `version`, `effective_from`,
`params`, `summary_ro`, set `source_url`, open a PR, merge. Users get their note within minutes.

## Demo script (3 minutes)

1. Open the hosted URL, click **Intră în contul demo** (Bucharest, 6 kWp, 5 kWh battery, a year of data).
2. **Facturi** → upload `data/demo/factura_demo_2026-09.pdf` (or the phone photo). Confirm: every line gets a
   plain explanation, the energy balance appears, and the "why isn't my bill zero" note.
3. **Abonament** → subscribe with test card 4242 4242 4242 4242 (or the demo unlock if Stripe isn't configured).
   Back on **Facturi**: "delivered energy differs from your inverter by about −11%, worth checking", plus the
   pre-filled request to the supplier.
4. **Prognoză** → next 7 days for that roof with the uncertainty band, consumption, and the predicted bill for
   this month; accuracy versus "physics only" and "same hour yesterday".
5. **Reguli & alerte** → subscribe the phone to the ntfy topic, press **Simulează o schimbare de lege (DEMO)**:
   the phone buzzes with a personalised note.
6. **Plan sistem** → add an electric car from the catalogue: the planner recommends battery modules to soak up
   the summer surplus, suggests charging the car at midday, and shows payback under the three scenarios.

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
- **Typical consumption profile** in `engine/load.py` (forecast) is a placeholder; the planner already uses the
  measured PSC profiles and could replace it.
- **Planner limits**:
  - The day/night user profiles are assumptions.
  - There is no sourced national or regional yearly average, so the last fallback (2,400 kWh) is labelled as an
    assumption.
  - The post-2030 export value is unknown, which is why there are three scenarios.
  - Prices are rough market levels.
  - Roof area, shading, panel orientation beyond the profile's, and grid-connection limits are not modelled.
    `max_panels` is the only roof constraint.
  - Battery power limits are simplified (0.5 C), and the efficiency is one round-trip figure.
- **Weather accuracy bounds the forecast**: good for 1–2 days, weaker by day 5–7. Open-Meteo's free API is
  non-commercial; a real launch needs their paid plan.
- **Auth** is a simple email + password table (PBKDF2). Use Supabase Auth before handling real users at scale.

# Asistent Prosumator: Android app (Expo)

Expo SDK 58, React Native 0.88, TypeScript, Expo Router. Romanian interface. Talks to the FastAPI service in
`../api`, which wraps the same `engine/`, `bills/` and `rules/` code and the same database as the web app.

| Tab | What it does |
| --- | --- |
| Acasă | 7-day production, last bill, last alert |
| Factură | Photograph a bill (camera, full resolution), pick a photo, or upload a PDF; list of saved bills |
| Prognoză | Premium: hourly production + consumption chart, daily table, this month's estimated bill, accuracy |
| Alerte | Subscribe to the ntfy topic, test push, DEMO law change, current rule, personal change note, history |
| Cont | Plan and Stripe test checkout, inverter export upload + training, profile, server address, logout |

Plus: login / demo account, onboarding with the phone's GPS location, bill review (correct low-confidence
lines), bill explanations, inverter check with an adjustable threshold, and the request to the supplier shared
through any app (e-mail, WhatsApp).

**Plan sistem** (from the Acasă card or Cont) is the system planner:

- the user adds devices from the catalogue or by hand;
- it shows how many panels and battery modules to add (or what to install with 0 kWp);
- monthly bought/sold energy before and after;
- the neighbouring options it rejected and why;
- when to run flexible devices;
- payback under the three post-2030 scenarios;
- what the result is based on.

Its settings are editable: area, usage profile, prices, module size, roof limit and Casa Verde Baterii. How
the planner decides is in the main `README.md`, section "System planner".

Every native module used ships in **Expo Go**, so no development build is needed to try it.

## Run it

```bash
# 1. the API, from the repo root (same database as the web app)
pip install -r requirements-api.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000        # docs: http://localhost:8000/docs

# 2. the app
cd mobile
npm install
cp .env.example .env          # set EXPO_PUBLIC_API_URL=http://<your-laptop-LAN-IP>:8000
npx expo start                # scan the QR code with Expo Go on the Android phone (same Wi-Fi)
```

The server address can also be changed inside the app: **Cont → Server**.
Log in with **Intră în contul demo**.

## Ship an APK to the judges

Deploy the API first (below), set `extra.apiUrl` in `app.json` (or `EXPO_PUBLIC_API_URL`) to its HTTPS URL, then:

```bash
npx eas-cli@latest login
npx eas-cli@latest build --platform android --profile preview     # free tier, ~15 min, gives an APK link
```

Or locally with Android SDK + JDK 17 (`../install.sh --android-sdk`):

```bash
npx expo run:android --variant release
adb install android/app/build/outputs/apk/release/app-release.apk
```

Release builds block plain `http://` URLs; use the HTTPS API for the APK and plain HTTP only with Expo Go.

## Deploy the API (Hugging Face Spaces, free)

1. Create a Space → SDK **Docker**. Push this repo to it with `Dockerfile.api` renamed to `Dockerfile`
   (or keep a separate Space repo with just that rename).
2. Space settings → secrets: `DATABASE_URL` (the same Supabase pooler string as the web app), `APP_SECRET`,
   `API_URL=https://<user>-<space>.hf.space`, and, for payments, `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID`.
   Set `SEED_DEMO=0` if the web app already seeds the demo account in the same database.
3. Check `https://<user>-<space>.hf.space/health`.

## How payments return to the app

`Cont → Abonează-te` asks the API for a Stripe Checkout URL and opens it with
`WebBrowser.openAuthSessionAsync`. Stripe redirects to `API_URL/stripe/return`, which verifies the session with
Stripe, marks the user Premium and redirects to `prosumer://cont?status=ok` (or `exp://…/--/cont` in Expo Go),
which closes the browser. Without Stripe keys the demo account gets an "Activează Premium pentru demo" button.

## Checks

```bash
npm run typecheck              # tsc
npm run lint                   # eslint (expo config, incl. React Compiler rules)
npm test                       # unit tests for Romanian number/date formatting and parsing
API_URL=http://localhost:8000 node scripts/contract-check.mjs   # every field the screens read, against a live API
npx expo export --platform android                              # proves the bundle builds
```

## Layout

```
src/app/            screens (Expo Router): _layout.tsx, login.tsx, profil.tsx, plan.tsx, bill/[id].tsx, (tabs)/…
src/components/     ui.tsx (cards, buttons, notices), charts.tsx (react-native-svg)
src/lib/            api.ts (client + token), session.tsx, storage.ts (SecureStore), format.ts, types.ts
scripts/            contract-check.mjs
```

Push notifications use the ntfy app (no Firebase setup); Expo push can replace it later.

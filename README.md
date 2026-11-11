# SitePay

**From site day → proof → approved pay → PayPal payout.**
Day labourers check in and send work photos on WhatsApp. The supervisor sees a
Hajri-style register (P / A / H / OT / advances) with an AI summary of each photo,
approves the period, and pays the whole crew in one **PayPal Payouts** batch.
Each worker then gets a pay note on WhatsApp.

Built on the Avalio stack (FastAPI + MongoDB + WhatsApp Cloud API + Vite/React);
see [DayLabor_Payroll_PayPal_Solution.md](DayLabor_Payroll_PayPal_Solution.md) for the product brief.

```
backend/     FastAPI: WhatsApp webhook, supervisor API, PayPal client, wage math
dashboard/   React + AG Grid: sign-up/login, register, evidence, pay runs, WhatsApp simulator
```

## Run it (zero setup, about 2 minutes)

```bash
# 1. API
cd backend
pip install -r requirements.txt
cp .env.example .env            # defaults: in-memory DB, PayPal simulated, AI off
uvicorn app:app --port 5001

# 2. Dashboard (new terminal)
cd dashboard
npm install
npm run dev                      # http://localhost:5173
```

Without any keys the whole flow runs: in-memory database, **simulated** PayPal
(clearly labelled SIMULATED in the UI and the pay note), and a built-in **WhatsApp
simulator** that runs the same bot code as the real webhook. Add keys one at a time
to make each part real.

## Demo script (doc §11)

1. **Sign up** → **Crew** → **Load demo crew**, then pick *Lekki Phase 2 Duplex* in the site picker.
   This adds the four workers from the doc and the past 6 days of register; today is empty.
2. **WhatsApp simulator** (as Musa): send `hi` → tap **✅ Check in** → 📎 attach a work
   photo with caption *Finished wall section B* → send `2 hours overtime`.
3. **Register**: Musa is *P* with 📸 1, an AI summary, and a "claims 2h OT" chip.
   Click his name to see the photo and AI summary → **Accept 2h OT** (P becomes OT).
   Click Chinedu's Status cell → **H**, set Advance 1000.
4. **Pay runs** → *Last 7 days* → review gross/advances/net and the USD payout per
   worker → **Approve period** (days are now locked) → **💸 Pay via PayPal**.
5. Each line shows the PayPal transaction status → **Pay note sent**. Back in the
   **WhatsApp simulator**, the worker has a pay note: days, OT, advances, net, PayPal ref.

## Making it real

### PayPal sandbox payouts
Docs: [REST auth](https://developer.paypal.com/api/rest) · [Payouts](https://developer.paypal.com/api/payouts/standard) · [Test & go live](https://developer.paypal.com/api/payouts/test-go-live)

1. [Developer Dashboard](https://developer.paypal.com/dashboard/) → **Apps & Credentials** (Sandbox) → *Create App*.
   Copy the Client ID and Secret into `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`.
2. **Testing Tools → Sandbox Accounts**: the app's *business* account pays. Make sure
   it has a USD balance. Create one or more *personal* accounts for the workers.
3. Put the personal-account emails in `DEMO_PAYPAL_RECEIVERS=a@…,b@…` before loading the
   demo crew, or set each worker's PayPal email on the Crew page.
4. Restart the API. The top bar now shows **PayPal sandbox**, and *Pay* calls
   `POST /v1/payments/payouts`; status comes from `GET /v1/payments/payouts/{id}`.
   Log in to the personal sandbox account at sandbox.paypal.com to see the money arrive.

How the PayPal integration behaves:
* **No double pay.** The pay-run ID is sent as both `sender_batch_id` and the
  `PayPal-Request-Id` header. PayPal rejects a reused batch ID for 30 days, and the run
  is claimed (`submitting`) before the call, so a double click can't start a second batch.
* **Currency.** Wages are in naira; PayPal can't pay out NGN, so each line converts at
  `PAYOUT_FX_RATE` (default 1500 NGN = 1 USD). The rate is stored on the run.
* **Clear purpose.** Each item's `note` reads like *"Lekki Phase 2 Duplex | 3–9 Nov | day
  labour. Present 4 days, Half 1 day. Gross ₦29,250, advances ₦1,500, net ₦27,750."*
* `UNCLAIMED` means the receiver email has no PayPal account; PayPal holds it 30 days.

### AI (photo summaries + messy-register parsing)
Set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (and optionally `LLM_VISION_MODEL`) to any
OpenAI-compatible endpoint with an image-capable model. The AI only writes summaries
and flags, and proposes rows from pasted notes for the supervisor to confirm. **It never
sets pay or triggers a payout.** "Too dark" and "repeat photo" checks are deterministic
(brightness + perceptual hash), so they work with AI off.

### WhatsApp Cloud API
Same setup as Avalio: set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, and point the Meta webhook at
`https://<your-host>/whatsapp`. Workers are recognised by the phone number on the Crew
page. Free-form pay notes only deliver within 24h of the worker's last message. For later
ones, create an approved template with one body variable and set `WHATSAPP_PAYNOTE_TEMPLATE`.
Voice notes aren't used: workers send text, photos, location or button taps.

### Database
`MONGO_URI=mongomock://` is in-memory (lost on restart). Use a MongoDB Atlas URI to keep data.

## Wage rules
| Code | Meaning | Pay |
|---|---|---|
| P | Present | 1 × daily rate |
| A | Absent | 0 |
| H | Half day | 0.5 × daily rate |
| OT | Present + overtime | daily rate + OT hours × OT rate |
| L | Paid leave | 1 × daily rate |

Advances are deducted from the period total. Net never goes below 0; the excess is
reported as carry-over. Rates are frozen onto each day when it's logged, and an approved
day is locked so it can't be edited or paid twice. Default OT rate is 1.5× the hourly
rate of an 8-hour day.

## Tests
```bash
cd backend && python -m pytest -q
```
19 tests cover the wage math, the PayPal request shape (against the official OpenAPI
spec), token caching, error handling, retry after failure, and the full flow:
signup → WhatsApp check-in/photo → register → approve → payout → pay note.

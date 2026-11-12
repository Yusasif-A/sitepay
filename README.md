# SitePay

**Day labourers are paid in cash with no proof of work or pay. SitePay gives every site day verified proof and a traceable PayPal payout.**

Built for the PayPal AI Hackathon.

- **Live demo:** https://sitepay-ai.web.app
- **Product brief:** [DayLabor_Payroll_PayPal_Solution.md](DayLabor_Payroll_PayPal_Solution.md)

## The problem

Millions of day labourers on construction sites in Nigeria, Kenya and India are paid in cash from a paper register. Disputes are constant ("I was here all day" / "you left early"), workers leave with no record of their pay, and contractors can't prove what they paid. Supervisors have no single place to manage the crew: attendance sits in a notebook, proof of work in WhatsApp chats, the plan in their head, and pay in an envelope of cash.

## How SitePay works

```
1. Check-in        worker on WhatsApp: live location + a photo from the site
2. AI verification AI reads the photos: present on site? photos genuine? work done?
3. Approve/reject  supervisor confirms or rejects each day on the dashboard
4. Scheduling      supervisor plans future shifts; worker is told on WhatsApp
5. Paying          PayPal Payouts pays approved days (one worker or the whole crew)
6. Pay note        worker gets a WhatsApp receipt once PayPal confirms
```

**AI flags, the human decides, PayPal pays.** The AI never approves a day or moves money.

## How PayPal is used

All PayPal calls run in the **sandbox** (`https://api-m.sandbox.paypal.com`). Code: [backend/paypal.py](backend/paypal.py), [backend/payruns.py](backend/payruns.py).

| PayPal API | What SitePay uses it for |
|---|---|
| OAuth 2.0 client credentials, `POST /v1/oauth2/token` | Access token for the contractor's PayPal business account (cached until expiry). |
| Payouts, `POST /v1/payments/payouts` | Pays approved wages to each worker's PayPal: one worker, or everyone still unpaid in one batch. Each item's `note` says what it's for, e.g. *"Lekki Phase 2 Duplex \| 6–12 Nov \| day labour. Present 5 days, Overtime 1 day. Net ₦74,500."* |
| Payouts batch status, `GET /v1/payments/payouts/{id}` | Tracks each item (Pending → Success / Unclaimed / Failed). The worker's WhatsApp pay note is sent only once PayPal confirms. |

- **Only approved days are paid.** Unapproved and rejected days never reach PayPal.
- **No double pay.** Every send has a unique `sender_batch_id` and `PayPal-Request-Id` (PayPal rejects a reused id for 30 days), and pay lines are claimed in the database before the call, so double clicks and retries are safe.
- **Currency.** Wages are kept in naira. PayPal can't pay out NGN, so each line converts at `PAYOUT_FX_RATE` (default ₦1,500 = 1 USD), and the rate is stored on every payment.

## How AI is used

Model: **Google Gemma** (`google/gemma-4-E26B-it`), a vision-language model, called through any OpenAI-compatible endpoint. Code: [backend/ai.py](backend/ai.py), [backend/checks.py](backend/checks.py).

For each worker-day the AI reads two photos:
- **Check-in photo:** is the worker visible, are they on a work site, and what date/time is stamped on the photo?
- **Work photo:** is work visible, and is it **completed** or still in progress?

SitePay turns that into a verdict the supervisor reads instead of studying every photo:

| Question | Checked by |
|---|---|
| Present on site? | location shared + check-in photo shows the worker on a site + photo date matches the day + **on time** (photo stamp before `CHECK_IN_LATE_AFTER`, default 08:30) |
| Photos genuine? | perceptual hash: not reused from another day |
| Work done? | work photo sent + AI says work is visible and completed |

Example verdicts: *"AI confirms: present on site, photos genuine, work done. Safe to approve."* / *"AI flags this day: Present, but LATE: check-in photo stamped 12:00 (start 08:30)."* / *"NOT completed: wall is incomplete with visible gaps in the top course."*

When the supervisor approves, the AI verdict at that moment is saved with the day, so the record shows whether a flagged day was approved anyway.

## Sponsor tools

### AG Grid: the daily register
[dashboard/src/pages/Register.jsx](dashboard/src/pages/Register.jsx). A paper-style register (one row per worker; P / A / H / OT / L, overtime, advances, day pay) with:
- in-place editing (select and number cell editors); day pay recalculates instantly
- a custom **AI check** cell showing ✅ verified / ⚠️ flagged with the reason
- custom **Approve / Reject** buttons in each row; unapproved WhatsApp check-ins show as **P?**
- row selection for bulk Present / Half day / Absent / Approve

### Bryntum Scheduler: crew calendar and scheduling
[dashboard/src/pages/SiteCalendar.jsx](dashboard/src/pages/SiteCalendar.jsx). A two-week view, one row per worker:
- each worked day is a block coloured by status; paid days are faded; a line marks "now"
- double-click a future day (or **+ Schedule worker**) to plan a shift with dates, start time and task; the worker gets it on WhatsApp immediately ([backend/schedule.py](backend/schedule.py))
- planned shifts are striped; clicking one cancels it and tells the worker

### WhatsApp Cloud API: the worker's channel
[backend/bot.py](backend/bot.py), [backend/whatsapp.py](backend/whatsapp.py). Workers install nothing.
- **Check in** asks for a shared location **and** a site photo; the worker is only checked in when both arrive.
- Work photos, overtime claims and "My pay" during the day.
- Outbound: schedule messages, rejection notices with the reason, and pay notes.
- Photos are re-encoded on arrival to strip GPS and other metadata before storage.

## Project layout

```
backend/     Python + FastAPI: WhatsApp webhook, supervisor API, PayPal client, AI checks, wage math
  app.py           server + WhatsApp webhook
  bot.py           WhatsApp conversation (check-in, photos, OT, my pay)
  ai.py            Gemma photo reading
  checks.py        AI verdict per worker-day
  paypal.py        PayPal OAuth + Payouts client
  payruns.py       approve → PayPal batch → status → pay note
  schedule.py      shifts + WhatsApp schedule messages
  attendance.py    register (one record per worker per day)
  payroll.py       Hajri wage rules
  routers/api.py   dashboard API
  tests/           pytest suite
dashboard/   React + Vite: login/sign-up, Register (AG Grid), Site calendar (Bryntum), Pay, Crew, Sites
```

## Setup

Requirements: Python 3.12, Node 20+, a MongoDB URI (or `mongomock://` for in-memory).

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env     # then fill in the keys below
uvicorn app:app --port 5001

# 2. Dashboard (new terminal)
cd dashboard
npm install
echo "VITE_API_BASE_URL=http://localhost:5001" > .env
npm run dev              # http://localhost:5173
```

Or run the backend with Docker: `cd backend && docker compose up -d --build` (uses `PORT` from `.env`).

### Keys in `backend/.env`

| Setting | What for |
|---|---|
| `MONGO_URI`, `MONGO_DB_NAME` | Database. `mongomock://` = in-memory, lost on restart. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV=sandbox` | From the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) → Apps & Credentials (Sandbox). Without them, payouts run in a clearly labelled *simulated* mode. |
| `DEMO_PAYPAL_RECEIVERS` | Sandbox *personal* account email(s) the demo crew is paid to (Testing Tools → Sandbox Accounts). |
| `PAYOUT_CURRENCY`, `PAYOUT_FX_RATE`, `WAGE_CURRENCY` | Wages in NGN, paid in USD at the given rate. |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Any OpenAI-compatible endpoint with a vision model (we use Gemma). |
| `CHECK_IN_LATE_AFTER` | Check-in photos stamped after this time are flagged late (default `08:30`). |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | WhatsApp Cloud API. Point the Meta webhook at `https://<your-host>/whatsapp`. |
| `JWT_SECRET`, `ALLOWED_ORIGINS` | Dashboard login tokens and CORS. |

Note: WhatsApp only delivers free-form messages within 24 hours of the worker's last message. For later pay notes, set `WHATSAPP_PAYNOTE_TEMPLATE` to an approved template.

### Trying it

1. Sign up on the dashboard → **Crew** → **Load demo crew** (4 workers, past days on the register).
2. Add a worker with your own WhatsApp number on **Crew**, message the bot `hi`, tap **Check in**, share location, send a site photo, then a work photo.
3. **Register** → click the worker → read the AI check → **Confirm & approve** (or **Reject**).
4. **Site calendar** → double-click a future day → schedule the worker.
5. **Pay runs** → **💸 Pay [name]** → status goes Pending → Paid and the pay note arrives on WhatsApp.

## Wage rules (Hajri-style)

| Code | Meaning | Pay |
|---|---|---|
| P | Present | 1 × daily rate |
| A | Absent | 0 |
| H | Half day | 0.5 × daily rate |
| OT | Present + overtime | daily rate + OT hours × OT rate |
| L | Paid leave | 1 × daily rate |

Advances are deducted from the period total; net never goes below 0. Rates are frozen onto each day when it's logged. Default OT rate is 1.5× the hourly rate of an 8-hour day.

## Tests

```bash
cd backend && python -m pytest -q
```

The suite covers the wage maths, the PayPal request shape (checked against PayPal's OpenAPI spec), token caching, error handling and retry, paying one worker then the rest without double pay, approve/reject, check-in needing both location and photo, the AI verdict (late check-in, unfinished work, reused photos), scheduling messages, and the full flow from check-in to pay note.

## Tech

Python 3.12 · FastAPI · MongoDB Atlas · Docker · React 19 · Vite · AG Grid 34 · Bryntum Scheduler 7 · PayPal REST + Payouts API (sandbox) · WhatsApp Cloud API · Google Gemma (vision) · Pillow · Firebase Hosting

## License

[MIT](LICENSE)

# Day-Labour Payroll — Problem & Solution Document
**For PayPal AI Hackathon**

---

## 1. Product name (working)

**SitePay** *(or your preferred name)*  
*From site day → proof → approved pay → digital payout*

---

## 2. Problem

Millions of day labourers on construction sites, farms, and loading yards are still paid from **paper registers and cash**.

Typical flow today:
- Supervisor marks attendance in a notebook (or by memory)
- Advances and deductions are written by hand
- At end of day/week, cash is shared with little or no clear record
- Disputes are common (“I was here full day” vs “you left early”)
- Workers leave with **no digital proof** of work or pay
- Contractors cannot easily show what was paid if there is a complaint

This is widespread in informal markets (Nigeria, Kenya, India and similar contexts). Tools like HajriBook, CasualPay, and OgaBuild show demand exists — but most stop at attendance, matching, or basic payroll. **Few close the full loop:**

> Proof of work → clean register → human approval → digital payout with a clear “what this payment is for”

**Core gap:**  
Supervisors need a fast way to log a site day with evidence. Workers need fair, traceable pay. Both need something better than cash and a notebook.

---

## 3. Solution overview

A system that turns one site day into:

1. **Attendance** (Hajri-style)
2. **Work evidence** (photos + optional notes)
3. **AI structuring** (for the supervisor)
4. **Human approval**
5. **PayPal (or wallet) payout** with a clear pay note

### Two user surfaces

| User | Channel | What they do |
|------|---------|--------------|
| **Worker** | WhatsApp bot | Check in, send work photos, receive pay note / confirmation |
| **Supervisor** | Web / mobile dashboard | See attendance grid, AI summary of evidence, approve amounts, trigger payout |

---

## 4. Attendance format (Hajri-style)

Inspired by how contractors already think (Present / Absent / Half-day / Overtime).

### Status codes

| Code | Meaning | Typical wage rule |
|------|---------|-------------------|
| **P** | Present (full day) | 1 × daily rate |
| **A** | Absent | 0 |
| **H** | Half day | 0.5 × daily rate |
| **OT** | Overtime (extra hours) | Daily rate + OT hours × OT rate |
| **L** | Paid leave (if used) | As agreed |
| **ADV** | Advance taken | Deducted from period total |

### Example daily register (one site, one day)

| Worker | Trade | Daily rate (₦) | Status | OT hours | Advance (₦) | Notes |
|--------|-------|----------------|--------|----------|-------------|-------|
| Musa A. | Mason | 12,000 | P | 2 | 0 | — |
| Chinedu O. | Labourer | 6,500 | H | 0 | 1,000 | Left 1pm |
| Fatima B. | Painter | 9,000 | P | 0 | 0 | — |
| Ibrahim K. | Electrician | 15,000 | A | 0 | 0 | — |

### Period summary (auto-calculated)

For each worker over the selected period:
- Days P / H / A / OT
- Gross = (P × rate) + (H × 0.5 × rate) + (OT hours × OT rate)
- Less advances
- **Net payable**

Supervisor can edit any line before approval. AI never pays without human confirmation.

---

## 5. Work evidence (images + AI)

Attendance alone is not enough. The system also captures **proof of work**.

### What the worker (or supervisor) can send

Via WhatsApp bot or dashboard upload:
- Photo of the work area / task completed that day
- Optional short voice note or text (“Finished wall section B”, “Loaded 12 bags”)
- Optional location (if shared)

### What AI does with the images

AI (vision + language) analyses the photo(s) and produces a **supervisor-facing summary**, for example:

- Scene type (wall, foundation, loading, painting, electrical, etc.)
- Rough progress signal (e.g. “section appears completed”, “materials visible on site”)
- Flags if image looks unrelated, too dark, or duplicate of another day
- Short plain-language note the supervisor can accept or ignore

**Important:**  
AI does **not** decide pay. It only structures evidence so the supervisor decides faster and with less argument later.

### Supervisor view (example)

```
Musa A. — 09 Nov — Present + 2h OT
Evidence: 2 photos
AI summary: “Bricklaying on upper wall; course looks continuous; tools and mix visible.”
Status: Ready for your approval
```

Supervisor can:
- Accept
- Request clearer photo
- Override status (e.g. change P → H)
- Add manual note

---

## 6. User flows

### A. Worker (WhatsApp)

1. Worker messages the bot (or is added by supervisor with phone number).
2. Bot: “Send today’s check-in” → worker sends photo of self/site or taps Present.
3. During/after work: worker can send **work photos** + optional voice/text.
4. End of day/period: worker receives a simple pay note when supervisor has paid  
   (“You were marked Present 4 days, Half 1 day. Net ₦X. Paid via …”).

Low literacy friendly: voice notes + simple buttons where possible.

### B. Supervisor (Dashboard)

1. Selects site + date (or date range).
2. Sees **attendance grid** (Hajri-style table).
3. Sees per-worker **evidence panel** (photos + AI summary).
4. Edits any status / OT / advance if needed.
5. Clicks **Approve period**.
6. Triggers **PayPal payout** (sandbox in hackathon) to worker accounts/wallets on file.
7. System stores: who was paid, how much, for which days, linked evidence IDs.

### C. PayPal role

- Hold or send approved amounts
- Create a clear transaction reference / note (“Site X — week of 3–9 Nov — day labour”)
- Give both sides a digital trail (better than cash)

Optional stretch: batch payout list from the approved register.

---

## 7. What AI is responsible for (and what it is not)

| AI does | AI does not |
|---------|-------------|
| Read/structure attendance if submitted as messy text or voice | Invent attendance |
| Analyse work photos and write a short evidence summary | Decide final pay amount |
| Flag weak/missing/duplicate evidence | Override supervisor |
| Help generate clear pay notes in simple language | Move money without approval |

Human supervisor always approves before any payout.

---

## 8. Tech shape (high level)

- **WhatsApp Cloud API** — worker check-in, photo upload, notifications  
- **Vision model** — work-photo analysis  
- **LLM** — structure notes, summaries, pay-note language  
- **Dashboard** — attendance grid + evidence + approval (strong fit for **AG Grid**)  
- **PayPal** — sandbox payouts / payment recording  
- Optional: **Bryntum** if you add work schedules or multi-day site calendars  

---

## 9. Why this fits PayPal AI Hackathon

- Real **financial inclusion** problem (informal day labour)
- Clear **PayPal** role (payout + record)
- Clear **AI** role (evidence + structuring, not blind autopay)
- Demoable story:  
  worker sends photo on WhatsApp → supervisor sees grid + AI summary → approves → PayPal pays → worker gets pay note
- Differentiated from pure attendance apps (HajriBook-style) and pure marketplaces (OgaBuild-style)

---

## 10. Differentiation vs existing tools

| Tool type | Typical strength | Gap vs this idea |
|-----------|------------------|------------------|
| HajriBook / LabourBook | Fast attendance + wage math | Little/no AI evidence, no PayPal-style payout loop |
| CasualPay / similar | Casual pay rails | Less proof-of-work + AI structuring |
| OgaBuild | Crew matching + local payouts | Hiring-first; not “supervisor logs this site day with photos” |
| Formal payroll (Payrail, etc.) | SME compliance | Not built for dusty daily muster + photo evidence |

**This solution:** attendance (Hajri format) + work photos + AI summary + human approval + PayPal payout + worker WhatsApp.

---

## 11. Demo script (short)

1. Worker on WhatsApp: check-in + 2 work photos.  
2. Dashboard: attendance row = Present; AI summary of photos appears.  
3. Supervisor adjusts one half-day, approves the day.  
4. PayPal sandbox payout triggered.  
5. Worker receives simple pay confirmation on WhatsApp.

---

## 12. Open choices for the team

- Product name final (SitePay / HajriPay / CrewPay / etc.)
- Primary currency & region for demo (e.g. Nigeria ₦ narrative, PayPal sandbox)
- Whether supervisor can also mark attendance without worker WhatsApp (yes — recommended fallback)
- Minimum evidence rule (e.g. at least one photo for OT claims)

---

---

## 13. Developer resources (use these links)

### Hackathon home
- **PayPal AI Hackathon (Devpost):** https://paypalaihackathon.devpost.com/
- **PayPal community blog post:** https://developer.paypal.com/community/blog/PayPal_AI_Hackathon/

### PayPal (required)
- **Get started / REST APIs:** https://developer.paypal.com/api/rest
- **Sandbox base URL:** `https://api-m.sandbox.paypal.com`
- **Live base URL:** `https://api-m.paypal.com`
- **Get access token:** https://developer.paypal.com/api/rest (OAuth client credentials)
- **Payouts API (batch pay workers):** https://developer.paypal.com/api/payouts/standard  
  - Create batch: `POST /v1/payments/payouts`
  - Track batch: `GET /v1/payments/payouts/{payout_batch_id}`
- **Payouts overview:** https://developer.paypal.com/api/payouts
- **Test & go live (payouts):** https://developer.paypal.com/api/payouts/test-go-live
- **API requests guide:** https://developer.paypal.com/api/rest/requests
- Developer Dashboard (create app + sandbox accounts): https://developer.paypal.com/dashboard/

**Recommended PayPal flow for this product**
1. Create sandbox business + personal accounts.
2. Create REST app → copy Client ID + Secret.
3. Get OAuth token.
4. After supervisor approves the register → call **Payouts API** with one item per worker (email or PayPal receiver + amount + note like `Site X — 3–9 Nov — day labour`).
5. Store `payout_batch_id` and show status on dashboard; notify worker on WhatsApp when completed.

### AG Grid (strongly recommended — attendance + approval grid)
- **Hackathon AG Grid page:** https://paypalaihackathon.devpost.com/details/aggrid
- **AG Studio quick start:** https://www.ag-grid.com/studio/react/quick-start/
- **Custom widgets & theming:** https://www.ag-grid.com/studio/react/custom-widgets/
- **Studio Agent Framework:** https://www.ag-grid.com/studio/react/ai-agents/
- **React Data Grid docs:** https://www.ag-grid.com/react-data-grid/grid-interface/
- **React quick start:** https://www.ag-grid.com/react-data-grid/getting-started/  
Use AG Grid for: daily/period attendance table, editable status (P/A/H/OT), net pay column, approve checkbox, filter by site/date.

### Bryntum (optional — site calendar / multi-day schedule)
- **Bryntum × PayPal hackathon:** https://bryntum.com/blog/hackathon-paypal-and-bryntum/
- **Scheduler docs:** https://bryntum.com/products/scheduler/docs/
- **Calendar docs:** https://bryntum.com/products/calendar/docs/
- **Gantt docs:** https://bryntum.com/products/gantt/docs/  
Useful if you show multi-day site roster or pay-period calendar.

### APIMatic (optional — faster PayPal integration with AI coding tools)
- **Hackathon page:** https://paypalaihackathon.devpost.com/details/apimatic
- **APIMatic PayPal hackathon:** https://www.apimatic.io/paypal-ai-hackathon  
Gives AI coding agents structured PayPal API context (Context Plugin).

### WhatsApp (worker channel)
- **WhatsApp Cloud API docs:** https://developers.facebook.com/docs/whatsapp/cloud-api
- **Getting started:** https://developers.facebook.com/docs/whatsapp/cloud-api/get-started
- **Webhooks:** https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks  
Use for: worker check-in, photo upload, pay-note messages. Keep media handling and privacy clear (work photos only).

### Suggested stack mapping for developers

| Layer | Tool | Why |
|-------|------|-----|
| Worker chat | WhatsApp Cloud API | Photos + low-friction check-in |
| Attendance UI | AG Grid / AG Studio | Editable Hajri-style register + approval |
| Optional schedule | Bryntum Scheduler/Calendar | Multi-day site view |
| Payments | PayPal Payouts API (sandbox) | Batch pay after approval |
| AI | Vision model + LLM | Photo evidence summary; structure messy notes |
| PayPal coding aid | APIMatic Context Plugin | Faster, accurate PayPal calls |


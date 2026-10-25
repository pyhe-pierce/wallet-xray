---
name: wallet-xray
description: 'Money audit for AI-built apps. Finds every code path that spends your money (LLM, image, email, SMS, maps, storage), estimates cost per user and worst-case abuse cost per hour, checks pricing margin, and fixes holes. Use for "how much will this cost me", "can someone run up my bill", "API bill", "pricing", "before launch".'
---

# Wallet X-Ray

Security skills ask "can someone steal my data?". This skill asks the question that actually bankrupts solo builders: **"how much money can this app burn — on a normal day, and on the worst day?"**

It produces three numbers and a fix list:

1. **Cost per active user per month** — what one real user costs you.
2. **Worst-case burn per hour** — what an attacker (or a bug in a loop) can spend if they find your weakest endpoint.
3. **Margin** — whether your price covers #1 with room to spare.

Report in the user's language. Use plain words; the typical user built the app with AI and may not read code fluently. Never shame the build — the point is the Monday after the weekend hack.

## Workflow

### Step 1 — Inventory spend points

If `scripts/scan.py` exists next to this file, run it from the project root:

```bash
python3 <skill_dir>/scripts/scan.py . --json wallet-scan.json
```

It prints a summary and writes JSON. It is a heuristic: treat every finding as a lead, then **open each flagged file and confirm** before reporting it.

If the script is not available, do the same inventory by hand with Grep (skip `node_modules`, `.next`, `dist`, `build`, `.git`):

- **Paid calls**: `new OpenAI(`, `chat.completions.create`, `responses.create`, `new Anthropic(`, `messages.create`, `GoogleGenerativeAI`, `GoogleGenAI`, `generateContent`, `openrouter.ai`, `generateText(`, `streamText(`, `generateObject(`, `images.generate`, `replicate`, `fal.ai`, `elevenlabs`, `resend.emails.send`, `sgMail.send`, `twilio`, `maps.googleapis.com`, `storage.from(...).upload`, `@vercel/blob` `put(`.
- **Exposed keys**: literals matching `sk-`, `sk-ant-`, `sk-or-v1-`, `AIza`, `sk_live_`, `rk_live_`, `re_`; env names starting `NEXT_PUBLIC_` / `VITE_` / `EXPO_PUBLIC_` / `REACT_APP_` / `PUBLIC_` that contain `SECRET`, `SERVICE_ROLE`, `OPENAI`, `ANTHROPIC`, `GEMINI`, `OPENROUTER`, `STRIPE_SECRET`, `PRIVATE`, `API_KEY`; `.env` files tracked by git (`git ls-files | grep -i '\.env'`).
- **Webhooks**: files/paths containing `webhook`; check for signature verification (`constructEvent`, `verifySignature`, `createHmac`, `timingSafeEqual`, `svix`).

### Step 2 — Classify each spend point

For every confirmed paid call, record:

| Field | How to decide |
|---|---|
| **Where it runs** | Browser (`'use client'`, Vite/CRA `src/` without a server) = key is public, worst case. Server route / server action / edge function = OK if guarded. |
| **Who can trigger it** | Anyone on the internet / any signed-up user (free signup = anyone) / paying users only / admin / cron. |
| **Guards present** | Auth check, per-user rate limit or daily quota, `max_tokens` / `maxOutputTokens`, input length cap, model fixed server-side (not taken from the request body). |
| **Fan-out** | Called inside a loop, `Promise.all`, retry wrapper, or agent loop → multiply cost. |
| **Model / SKU** | Exact model string, image size, voice minutes, etc. |

Rule of thumb: **a spend point reachable by "anyone" with no rate limit has no upper bound except the provider's own limit.** That is the number to report.

### Step 3 — Get current prices (do not trust memory)

Prices change monthly. Search the web for the provider's official pricing page for each model/SKU found, and note the date. If a price cannot be confirmed, say "estimated" next to it. See `references/providers.md` for where each provider keeps pricing and spend caps (verify those pages too — dashboards move).

### Step 4 — Do the math

Use `scripts/cost_calc.py` if present (fill a JSON like `references/cost_input_example.json`), otherwise compute by hand:

- **Cost per call** = input_tokens × in_price/1M + output_tokens × out_price/1M (+ per-image / per-email / per-minute fees). Estimate tokens from the actual prompt in the code (system prompt + typical user input + any retrieved context); ~4 chars ≈ 1 token for English, ~1–1.5 chars ≈ 1 token for Chinese.
- **Cost per active user / month** = Σ (cost per call × calls per user per month). If the user hasn't said usage, assume light / typical / heavy (e.g. 10 / 50 / 300 calls) and show all three.
- **Worst-case burn per hour** = cost per call at **max** input/output × max requests per hour.
  - Max requests/hour = the rate limit if one exists; if not, the provider's account limit (RPM) — or for a leaked key, assume the provider limit applies to the attacker.
  - If there is no `max_tokens`, use the model's max output.
- **Margin** = (price − payment fees − cost per paying user − share of free users' cost) / price. Free users count: 1,000 free users who each cost $0.20 is $200/month someone has to pay.

### Step 5 — Write the report

Use this shape (translate headings to the user's language):

```
## 钱包体检 / Wallet X-Ray: <app> — verdict: SAFE / FIX BEFORE LAUNCH / BLEEDING NOW

### Three numbers
- Cost per active user: $x (light) / $y (typical) / $z (heavy) per month
- Worst-case burn: $N per hour via <endpoint>  (≈ $N×24 per day)
- Margin at current price: x%  (break-even at N paying users)

### Holes, ordered by money saved per minute of fixing
| # | 🔴🟡🟢 | What's wrong (plain words) | Where | Fix | Saves |

### Account-level money firewall (do these today, no code)
- [ ] Spend cap / budget alert on each provider (list only providers actually used)
- [ ] ...

### Cost cutting (optional, only if margin < ~70%)
- cheaper model for X, cache Y, shorten system prompt by N tokens, etc.

### Assumptions
Prices checked on <date> from <sources>. Usage assumptions: ...
```

Severity:
- 🔴 **Bleeding / unbounded**: secret key in browser or git; paid endpoint callable by anyone with no rate limit; payment webhook without signature check (anyone can fake a payment and get credits); model or `max_tokens` taken from the request body.
- 🟡 **Bounded but expensive**: auth exists but no per-user quota (free signup = anyone); no `max_tokens`; no input length cap; fan-out loops; retries without cap; margin under 50%.
- 🟢 **Fine / nice-to-have**: caching, cheaper model routing, budget alerts already set.

### Step 6 — Offer fixes

Ask once whether to apply the 🔴 fixes. When applying, use the patterns in `references/fix-recipes.md`, keep changes minimal, and never print secret values back in chat. If a key was ever exposed publicly, the fix is **rotate the key first**, then move it server-side — deleting it from code does not un-leak it.

## Notes

- Free sign-up is not a guard. Treat "any logged-in user" as "anyone" unless there's a per-user quota.
- Guest / anonymous sign-in is the same: if anyone can mint a guest account, a per-user limit can be multiplied by creating accounts. Look for a per-IP limit too, or a limit on guest creation.
- Next.js server actions (`'use server'`) are public POST endpoints. Guard them exactly like API routes.
- BYOK (the user pastes their own API key) means the bill is theirs, not yours — lower severity. Still check there's no fallback to your own env key, and that their keys aren't logged or returned to the browser.
- When the scanner says "guards inherited from X", the guard was found in the route that calls the helper. Open X and confirm the check runs *before* the paid call, on every code path.
- Supabase `anon` key in the browser is normal **only if RLS is on**; the `service_role` key in the browser is always 🔴.
- Google API keys (Maps, Firebase) can silently gain Gemini access if the Generative Language API is enabled on the same project — check key restrictions.
- A spend cap that pauses the app is a feature: a few hours of downtime beats a five-figure bill.
- This skill reviews the user's own app. Don't help probe other people's apps.

# Fix recipes

Minimal, copy-adaptable patterns. Adapt names to the project; keep diffs small.

## 1. Move a key out of the browser

Before (Next.js client component or Vite app):
```ts
'use client'
const ai = new GoogleGenAI({ apiKey: process.env.NEXT_PUBLIC_GEMINI_API_KEY })
```

After — call your own server route instead:
```ts
// app/api/ai/route.ts  (server only)
import { GoogleGenAI } from '@google/genai'
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY }) // no NEXT_PUBLIC_
export async function POST(req: Request) { /* auth + quota + caps, see below */ }
```
```ts
// client
const res = await fetch('/api/ai', { method: 'POST', body: JSON.stringify({ prompt }) })
```
Then: **rotate the old key** in the provider dashboard, rename the env var in Vercel (remove the `NEXT_PUBLIC_` one), redeploy.

## 2. Guard a paid server route (auth + quota + caps)

```ts
import { createClient } from '@/lib/supabase/server'

const MAX_INPUT_CHARS = 4000
const DAILY_LIMIT = 30           // per user per day
const MODEL = 'gemini-x-flash'    // fixed server-side, never from req body

export async function POST(req: Request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return new Response('Unauthorized', { status: 401 })

  const { prompt } = await req.json()
  if (typeof prompt !== 'string' || prompt.length > MAX_INPUT_CHARS)
    return new Response('Too long', { status: 413 })

  // atomic per-user daily counter (SQL function below)
  const { data: ok } = await supabase.rpc('consume_quota', { p_limit: DAILY_LIMIT })
  if (!ok) return new Response('Daily limit reached', { status: 429 })

  const result = await ai.models.generateContent({
    model: MODEL,
    contents: prompt,
    config: { maxOutputTokens: 800 },
  })
  return Response.json({ text: result.text })
}
```

```sql
create table if not exists usage_daily (
  user_id uuid references auth.users not null,
  day date not null default current_date,
  count int not null default 0,
  primary key (user_id, day)
);
alter table usage_daily enable row level security;

create or replace function consume_quota(p_limit int) returns boolean
language plpgsql security definer set search_path = public as $$
declare c int;
begin
  insert into usage_daily(user_id, day, count) values (auth.uid(), current_date, 1)
  on conflict (user_id, day) do update set count = usage_daily.count + 1
  returning count into c;
  return c <= p_limit;
end $$;
revoke all on function consume_quota(int) from public;
grant execute on function consume_quota(int) to authenticated;
```

Paid tiers: look up the user's plan first and pick the limit from it.

## 3. Anonymous / public endpoints (landing-page demo, contact form)

- Per-IP rate limit: Upstash Ratelimit, Vercel Firewall rate-limit rule, or Cloudflare rule.
- Add a CAPTCHA (Cloudflare Turnstile is free) before any paid call or email send.
- Lower caps than logged-in users (e.g. 3 calls per IP per day, short `maxOutputTokens`).

## 4. Never trust the client for model / token settings

```ts
// ❌ const { model, max_tokens } = await req.json()
// ✅ allow-list
const ALLOWED = { fast: 'model-small', smart: 'model-large' } as const
const model = ALLOWED[body.tier as keyof typeof ALLOWED] ?? ALLOWED.fast
```
Gate the expensive tier behind the paid plan check.

## 5. Webhook signature (credits must come from verified events only)

Stripe:
```ts
const raw = await req.text()
const event = stripe.webhooks.constructEvent(raw, req.headers.get('stripe-signature')!, process.env.STRIPE_WEBHOOK_SECRET!)
```

Generic HMAC (Creem and similar — check the provider docs for the exact header name and algorithm):
```ts
import crypto from 'crypto'
const raw = await req.text()
const sig = req.headers.get('<provider-signature-header>') ?? ''
const expected = crypto.createHmac('sha256', process.env.WEBHOOK_SECRET!).update(raw).digest('hex')
const ok = sig.length === expected.length &&
  crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
if (!ok) return new Response('Bad signature', { status: 401 })
```
Also store processed event IDs so the same event can't grant credits twice. Never grant credits on the success-page redirect.

## 6. Kill fan-out

- Cap loops: `items.slice(0, 20)` before `Promise.all`.
- Retry wrapper: max 2 retries, exponential backoff, no retry on 4xx.
- Agent loops: hard `maxSteps` and a per-run token budget.

## 7. Cheaper without being worse

- Cache identical requests (hash of prompt + model) in a table or KV for N hours.
- Use prompt caching for long fixed system prompts.
- Route simple tasks (classification, short rewrites) to the small model.
- Trim the system prompt: every 1,000 tokens removed is saved on every single call.
- Batch / async APIs for non-urgent jobs (often ~50% off — verify).

# Provider notes — where money leaks and where the brakes are

Always verify current prices and dashboard locations by searching the provider's official docs; these notes say *what to look for*, not today's numbers.

## LLM / AI

| Provider | Pricing page to search | Brakes to set | Gotchas |
|---|---|---|---|
| OpenAI | "OpenAI API pricing" | Project budget + usage limits in platform settings; turn off auto-recharge; per-project keys | Keys starting `sk-` / `sk-proj-`. Image and realtime/audio are billed very differently from text. |
| Anthropic | "Claude API pricing" | Workspace spend limits in Console; separate workspace per app | Keys `sk-ant-`. Prompt caching cuts repeated system prompts a lot. |
| Google Gemini | "Gemini API pricing" | Cloud Billing budget + alerts (alerts don't stop spend by themselves); API key restrictions (restrict to specific APIs + HTTP referrers / IPs); quotas per API | Keys `AIza…`. Old Maps/Firebase keys on a project with the Generative Language API enabled can call Gemini. New AI Studio keys may be scoped differently — check. |
| OpenRouter | "OpenRouter pricing" / model page | Per-key credit limit; prepaid credits only | Keys `sk-or-v1-`. Model choice in request = price choice; never let the client pick the model. |
| Replicate / fal | model page | Spend limit in account settings | Billed per second of GPU — long video/image jobs add up fast. |
| ElevenLabs / Deepgram | pricing page | Plan quota | Per character / per minute. |

## Non-AI spenders

| Service | Risk | Brake |
|---|---|---|
| Resend / SendGrid / Postmark | Open "contact" or "invite" endpoint → spam relay, account banned, overage | Rate limit + CAPTCHA on public forms, daily send cap |
| Twilio (SMS / OTP) | SMS pumping fraud — attackers trigger OTPs to premium numbers | Geo permissions (allow only needed countries), Verify fraud guard, per-IP + per-number limits |
| Google Maps | Key in browser is normal but must be HTTP-referrer restricted | Key restrictions + quota caps per API |
| Vercel | Function invocations, bandwidth, image optimization on public routes | Spend Management (hard limit / pause projects), Firewall rate limiting |
| Supabase | Egress from public storage buckets, compute add-ons | Spend cap setting on the org, private buckets + signed URLs |
| Cloudflare / AWS / GCP | Leaked cloud keys → crypto mining / GPU training | Budgets + least-privilege keys; never put cloud root keys in an app |

## Payment providers (revenue leaks)

| Provider | What to verify |
|---|---|
| Stripe | Webhook uses `stripe.webhooks.constructEvent(rawBody, sig, secret)`; credits granted only from webhook, never from the success-page redirect |
| Creem | Webhook signature header verified with HMAC + webhook secret before granting access; same "never trust the redirect" rule |
| Lemon Squeezy / Paddle | Signature verification on webhooks; idempotency (same event twice ≠ double credits) |

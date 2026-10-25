#!/usr/bin/env python3
"""Wallet X-Ray scanner: find code paths that spend money, exposed keys,
and unverified webhooks. Heuristic — every hit is a lead to confirm by reading.

Usage: python3 scan.py [project_root] [--json out.json]
Never prints full secret values (masks them).
"""
import json, os, re, subprocess, sys

SKIP_DIRS = {"node_modules", ".next", "dist", "build", ".git", ".vercel", "out",
             "coverage", ".turbo", ".svelte-kit", "venv", ".venv", "__pycache__"}
EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".py",
        ".html", ".astro", ".env", ".json", ".toml", ".yaml", ".yml"}
MAX_BYTES = 800_000

SPEND = [
    ("openai", "LLM", r"new\s+OpenAI\s*\(|chat\.completions\.create|responses\.create|api\.openai\.com"),
    ("anthropic", "LLM", r"new\s+Anthropic\s*\(|messages\.create\s*\(|api\.anthropic\.com"),
    ("gemini", "LLM", r"GoogleGenerativeAI|GoogleGenAI|generateContent(Stream)?\s*\(|generativelanguage\.googleapis\.com"),
    ("openrouter", "LLM", r"openrouter\.ai"),
    ("ai-sdk", "LLM", r"\b(generateText|streamText|generateObject|streamObject)\s*\("),
    ("image-gen", "Image", r"images\.generate|dall-e|gpt-image|imagen|replicate\.run|fal\.ai|@fal-ai|stability\.ai"),
    ("voice", "Audio", r"elevenlabs|deepgram|audio\.speech|audio\.transcriptions|whisper"),
    ("email", "Email", r"resend\.emails\.send|sgMail\.send|postmark|mailgun|nodemailer"),
    ("sms", "SMS", r"twilio|messages\.create\(\s*\{\s*(to|from)|verify\.v2"),
    ("maps", "Maps", r"maps\.googleapis\.com|@googlemaps|mapbox"),
    ("storage", "Storage", r"storage\s*\.from\([^)]*\)\s*\.upload|@vercel/blob|\bput\s*\(.*access:\s*['\"]public|PutObjectCommand"),
]

KEY_PATTERNS = [
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenRouter key", r"sk-or-v1-[A-Za-z0-9]{20,}"),
    ("OpenAI key", r"sk-(proj-)?[A-Za-z0-9_\-]{20,}"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("Stripe secret", r"(sk|rk)_live_[0-9A-Za-z]{16,}"),
    ("Resend key", r"\bre_[A-Za-z0-9]{20,}"),
    ("Supabase service_role JWT", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*c2VydmljZV9yb2xl[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]+"),
]
PUBLIC_PREFIX = r"(NEXT_PUBLIC_|VITE_|EXPO_PUBLIC_|REACT_APP_|PUBLIC_)"
PUBLIC_SECRET_ENV = re.compile(PUBLIC_PREFIX + r"[A-Z0-9_]*(SECRET|SERVICE_ROLE|OPENAI|ANTHROPIC|GEMINI|OPENROUTER|STRIPE_SECRET|PRIVATE|API_KEY|REPLICATE|ELEVEN|RESEND|TWILIO)[A-Z0-9_]*")

GUARDS = {
    "auth": r"getUser\(|getSession\(|auth\(\)|currentUser\(|getServerSession|requireAuth|clerk|verifyIdToken|if\s*\(\s*!\s*(user|session)",
    "rate_limit": r"ratelimit|rateLimit|rate_limit|Ratelimit|consume_quota|quota|usage_daily|limiter|429",
    "max_tokens": r"max_tokens|maxTokens|maxOutputTokens|max_output_tokens|max_completion_tokens",
    "input_cap": r"\.length\s*>\s*\d+|\.slice\(0,\s*\d+\)|maxLength|z\.string\(\)\.max",
}
CLIENT_HINT = re.compile(r"^\s*['\"]use client['\"]", re.M)
MODEL_FROM_BODY = re.compile(r"model\s*:\s*(body|req\.body|input|params|data|json)\.?\w*|\{[^}]*\bmodel\b[^}]*\}\s*=\s*(await\s+)?(req\.json|body|request\.json)")
MAXTOK_FROM_BODY = re.compile(r"(max_tokens|maxTokens|maxOutputTokens)\s*:\s*(body|req\.body|input|params|data)\.")
FANOUT = re.compile(r"Promise\.all|for\s*\(|\.map\(\s*async|forEach\(\s*async|while\s*\(")
WEBHOOK_VERIFY = re.compile(r"constructEvent|verifySignature|createHmac|timingSafeEqual|svix|Webhook\(|verifyWebhook|validateSignature", re.I)


def mask(s):
    return s[:6] + "…" + s[-4:] if len(s) > 12 else "***"


def is_client_file(path, text):
    p = path.replace("\\", "/")
    if CLIENT_HINT.search(text):
        return True
    if p.endswith(".html"):
        return True
    server_markers = ("/api/", "/server/", "route.", "/actions", "server.", "/functions/", "/supabase/functions/", "middleware.")
    if any(m in p for m in server_markers):
        return False
    if "'use server'" in text or '"use server"' in text:
        return False
    # Vite / CRA style frontends
    if re.search(r"import\.meta\.env\.VITE_", text):
        return True
    return None  # unknown


def iter_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in EXTS or f.startswith(".env"):
                p = os.path.join(d, f)
                try:
                    if os.path.getsize(p) <= MAX_BYTES:
                        yield p
                except OSError:
                    pass


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def git_tracked_env(root):
    try:
        out = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True, timeout=20)
        return [l for l in out.stdout.splitlines()
                if re.search(r"(^|/)\.env(\.|$)", l) and not l.endswith((".example", ".sample", ".template"))]
    except Exception:
        return []


def scan(root):
    spend, keys, public_env, webhooks = [], [], [], []
    for p in iter_files(root):
        rel = os.path.relpath(p, root)
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        is_env = os.path.basename(p).startswith(".env")
        is_lock = rel.endswith(("package-lock.json", "pnpm-lock.yaml", "yarn.lock"))
        if is_lock:
            continue

        # keys
        for label, pat in KEY_PATTERNS:
            for m in re.finditer(pat, text):
                if label == "OpenAI key" and m.group(0).startswith(("sk-ant-", "sk-or-")):
                    continue
                keys.append({"type": label, "file": rel, "line": line_of(text, m.start()),
                             "value": mask(m.group(0)), "in_env_file": is_env})
        for m in PUBLIC_SECRET_ENV.finditer(text):
            name = m.group(0)
            if "SUPABASE_ANON" in name or "PUBLISHABLE" in name:
                continue
            public_env.append({"name": name, "file": rel, "line": line_of(text, m.start())})

        if is_env or rel.endswith(".json"):
            continue

        # webhooks
        if "webhook" in rel.lower():
            webhooks.append({"file": rel, "verified": bool(WEBHOOK_VERIFY.search(text))})

        # spend points
        client = is_client_file(rel, text)
        for prov, kind, pat in SPEND:
            for m in re.finditer(pat, text):
                guards = {g: bool(re.search(gp, text)) for g, gp in GUARDS.items()}
                spend.append({
                    "provider": prov, "kind": kind, "file": rel, "line": line_of(text, m.start()),
                    "match": m.group(0)[:60],
                    "runs_in": "browser" if client else ("server" if client is False else "unknown"),
                    "guards": guards,
                    "model_from_request": bool(MODEL_FROM_BODY.search(text)),
                    "max_tokens_from_request": bool(MAXTOK_FROM_BODY.search(text)),
                    "possible_fanout": bool(FANOUT.search(text)),
                })
                break  # one hit per provider per file is enough

    tracked_env = git_tracked_env(root)

    # severity
    for s in spend:
        g = s["guards"]
        if s["runs_in"] == "browser" and s["kind"] not in ("Maps", "Storage"):
            s["severity"] = "red"; s["why"] = "paid call runs in the browser — key is public"
        elif s["model_from_request"] or s["max_tokens_from_request"]:
            s["severity"] = "red"; s["why"] = "client controls model / max_tokens"
        elif not g["auth"] and not g["rate_limit"]:
            s["severity"] = "red"; s["why"] = "no auth and no rate limit found — anyone can call it"
        elif not g["rate_limit"]:
            s["severity"] = "yellow"; s["why"] = "auth but no per-user quota (free signup = anyone)"
        elif s["kind"] == "LLM" and not g["max_tokens"]:
            s["severity"] = "yellow"; s["why"] = "no max_tokens cap"
        else:
            s["severity"] = "green"; s["why"] = "guards found (confirm they apply to this call)"
        if s["possible_fanout"] and s["severity"] == "green":
            s["severity"] = "yellow"; s["why"] += "; loop/Promise.all in file — check fan-out"

    for k in keys:
        k["severity"] = "yellow" if (k["in_env_file"] and k["file"] not in tracked_env) else "red"
    for w in webhooks:
        w["severity"] = "green" if w["verified"] else "red"

    return {"root": os.path.abspath(root), "spend_points": spend, "exposed_keys": keys,
            "public_secret_env": public_env, "git_tracked_env_files": tracked_env,
            "webhooks": webhooks}


ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def print_summary(r):
    print(f"Wallet X-Ray scan: {r['root']}\n")
    print(f"Spend points: {len(r['spend_points'])}")
    for s in sorted(r["spend_points"], key=lambda x: ["red", "yellow", "green"].index(x["severity"])):
        print(f"  {ICON[s['severity']]} [{s['kind']}/{s['provider']}] {s['file']}:{s['line']}  ({s['runs_in']}) — {s['why']}")
    print(f"\nHard-coded keys: {len(r['exposed_keys'])}")
    for k in r["exposed_keys"]:
        where = "env file (not in git)" if k["severity"] == "yellow" else "CODE or git-tracked"
        print(f"  {ICON[k['severity']]} {k['type']} {k['value']} at {k['file']}:{k['line']} — {where}")
    print(f"\nSecret-looking PUBLIC env vars (shipped to browser): {len(r['public_secret_env'])}")
    seen = set()
    for e in r["public_secret_env"]:
        if e["name"] in seen:
            continue
        seen.add(e["name"]); print(f"  🔴 {e['name']}  (first seen {e['file']}:{e['line']})")
    if r["git_tracked_env_files"]:
        print("\n🔴 .env files tracked by git: " + ", ".join(r["git_tracked_env_files"]))
    print(f"\nWebhooks: {len(r['webhooks'])}")
    for w in r["webhooks"]:
        print(f"  {ICON[w['severity']]} {w['file']} — {'signature check found' if w['verified'] else 'NO signature check found'}")
    print("\nHeuristic results. Open each file and confirm before reporting.")


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json"); out = args[i + 1]; del args[i:i + 2]
    root = args[0] if args else "."
    res = scan(root)
    print_summary(res)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\nJSON written to {out}")

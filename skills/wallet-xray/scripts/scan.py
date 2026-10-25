#!/usr/bin/env python3
"""Wallet X-Ray scanner: find code paths that spend money, exposed keys,
and unverified webhooks. Heuristic — every hit is a lead to confirm by reading.

Usage: python3 scan.py [project_root] [--json out.json]
Never prints full secret values (masks them). Reads files only; runs nothing.
"""
import json, os, re, subprocess, sys

SKIP_DIRS = {"node_modules", ".next", "dist", "build", ".git", ".vercel", "out",
             "coverage", ".turbo", ".svelte-kit", "venv", ".venv", "__pycache__",
             ".expo", "ios", "android", "vendor"}
CODE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".html", ".astro"}
CONF_EXTS = {".json", ".toml", ".yaml", ".yml"}
MAX_BYTES = 800_000

# (provider, kind, pattern)
SPEND = [
    ("openai", "LLM", r"new\s+OpenAI\s*\(|chat\.completions\.create|responses\.create|api\.openai\.com|createOpenAI\s*\("),
    ("anthropic", "LLM", r"new\s+Anthropic\s*\(|\.messages\.create\s*\(|api\.anthropic\.com|createAnthropic\s*\("),
    ("gemini", "LLM", r"GoogleGenerativeAI|GoogleGenAI|generateContent(Stream)?\s*\(|generativelanguage\.googleapis\.com|createGoogleGenerativeAI|aiplatform\.googleapis\.com"),
    ("openrouter", "LLM", r"openrouter\.ai"),
    ("other-llm", "LLM", r"together-ai|api\.together\.(xyz|ai)|new\s+Together\s*\(|groq-sdk|api\.groq\.com|api\.mistral\.ai|@mistralai|api\.deepseek\.com|api\.x\.ai|api\.fireworks\.ai|api\.perplexity\.ai|api\.cohere\.(ai|com)"),
    ("ai-sdk", "LLM", r"\b(generateText|streamText|generateObject|streamObject|embedMany|generateImage)\s*\("),
    ("image-gen", "Image", r"images\.generate|gpt-image|imagen-|replicate\.run|api\.replicate\.com|new\s+Replicate\s*\(|fal\.ai|@fal-ai|api\.stability\.ai|api\.bfl\.ai"),
    ("voice", "Audio", r"elevenlabs|api\.deepgram\.com|@deepgram|audio\.speech\.create|audio\.transcriptions\.create"),
    ("email", "Email", r"resend\.emails\.send|sgMail\.send|postmark|mailgun\.(js|net)|api\.sendgrid\.com"),
    ("sms", "SMS", r"\btwilio\s*\(|require\(['\"]twilio['\"]\)|from\s+['\"]twilio['\"]|verify\.v2\.services|api\.twilio\.com"),
    ("maps", "Maps", r"maps\.googleapis\.com|@googlemaps/|api\.mapbox\.com"),
    ("storage", "Storage", r"storage\s*\.from\([^)]*\)\s*\.upload|@vercel/blob|PutObjectCommand|getSignedUrl\(.*PutObject"),
]

KEY_PATTERNS = [
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenRouter key", r"sk-or-v1-[A-Za-z0-9]{20,}"),
    ("OpenAI key", r"sk-(proj-)?[A-Za-z0-9_\-]{20,}"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("Stripe secret", r"(sk|rk)_live_[0-9A-Za-z]{16,}"),
    ("Resend key", r"\bre_[A-Za-z0-9]{20,}"),
    ("Replicate token", r"\br8_[A-Za-z0-9]{30,}"),
    ("Groq key", r"\bgsk_[A-Za-z0-9]{30,}"),
    ("Supabase service_role JWT", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*c2VydmljZV9yb2xl[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]+"),
]
PUBLIC_SECRET_ENV = re.compile(r"\b(NEXT_PUBLIC_|VITE_|EXPO_PUBLIC_|REACT_APP_|PUBLIC_)[A-Z0-9_]*(SECRET|SERVICE_ROLE|OPENAI|ANTHROPIC|GEMINI|GOOGLE_AI|OPENROUTER|STRIPE_SECRET|PRIVATE|API_KEY|REPLICATE|ELEVEN|RESEND|TWILIO|GROQ|TOGETHER|MISTRAL|DEEPSEEK)[A-Z0-9_]*")
PUBLIC_ENV_NOT_SECRET = re.compile(r"(_ID|_URL|_REGION|_HOST|_ENDPOINT|_MODEL|_BASE|_VERSION|ANON_KEY|PUBLISHABLE[A-Z_]*)$")
PUBLIC_BY_DESIGN = re.compile(r"MAPS|FIREBASE|UPLOAD|POSTHOG|SENTRY|ALGOLIA_SEARCH|PUSHER|MAPBOX")
PLACEHOLDER = re.compile(r"=\s*(['\"]?)(|your[_\- ]?\w*|xxx+|changeme|placeholder|<[^>]*>|\.\.\.|todo|replace[_\-]?me|sk-\.\.\.)\1\s*$", re.I)

GUARDS = {
    "auth": re.compile(r"\bauth\(\)|getUser\(|getSession\(|getServerSession|currentUser\(|clerk|verifyIdToken|withAuth|requireAuth"
                       r"|\b(get|require|current|verify|ensure|check)\w*(User|Session|Profile|Auth)\w*\s*\(|if\s*\(\s*!\s*(user|session|profile)\b", re.I),
    "rate_limit": re.compile(r"rate[_\-]?limit|ratelimit|limiter|throttl|quota|usage_daily|maxMessagesPer|maxRequestsPer|entitlement|status:\s*429|\b429\b", re.I),
    "max_tokens": re.compile(r"max_tokens|maxTokens|maxOutputTokens|max_output_tokens|max_completion_tokens|maxCompletionTokens", re.I),
    "input_cap": re.compile(r"\.length\s*>\s*\w+|\.slice\(0,\s*\w+\)|maxLength|\.max\(\s*\d+|MAX_\w*(CHARS|LENGTH|TOKENS|SIZE)|input[_\-]?limits", re.I),
}
CLIENT_DIRECTIVE = re.compile(r"^\s*['\"]use client['\"]", re.M)
SERVER_DIRECTIVE = re.compile(r"^\s*['\"]use server['\"]", re.M)
ROUTE_HANDLER = re.compile(r"export\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b|export\s+const\s+(GET|POST|PUT|PATCH|DELETE)\b|export\s+default\s+(async\s+)?function\s+handler|app\.(get|post|put)\(|router\.(get|post|put)\(|Deno\.serve|serve\(\s*async|@app\.(route|post|get)|onRequest\(")
CDN_IMPORT = re.compile(r"from\s+['\"]https://(esm\.run|esm\.sh|cdn\.jsdelivr|unpkg|cdn\.skypack)")
BODY_READ = re.compile(r"(req|request)\.json\(\)|req\.body|await\s+request\.formData|searchParams")
MODEL_FROM_BODY = re.compile(r"\bmodel\s*:\s*(body|req\.body|json|input|params|data|payload|args|chatSettings|settings|options)\.\w*model\w*\b"
                             r"|\bmodel\s*:\s*(body|json|input|params|data|payload)\.\w+|\{[^}]*\bmodel\b[^}]*\}\s*=\s*(await\s+)?(req|request)\.json", re.I)
MODEL_ALLOWLIST = re.compile(r"resolveModel|ALLOWED_MODELS|allowedModels|MODELS\[|\.includes\(\s*model|z\.enum\(", re.I)
MAXTOK_FROM_BODY = re.compile(r"(max_tokens|maxTokens|maxOutputTokens)\s*:\s*(body|req\.body|json|input|params|data|chatSettings|settings)\.", re.I)
BYOK = re.compile(r"apiKey\s*:\s*(profile|user|settings|userSettings|chatSettings|body|json|req\.body|keys?|userKeys?)\b[\w.?\[\]'\"]*|apiKey\s*:\s*\w+\.api_key\b|\(\s*\w*(profile|user|settings)\w*\.\w*api_?key", re.I)
CREDENTIAL = re.compile(r"apiKey|api_key|process\.env|import\.meta\.env|Authorization|x-api-key|[?&]key=|\bnew\s+(GoogleGenAI|GoogleGenerativeAI|OpenAI|Anthropic|Together|Replicate)\s*\(\s*\w", re.I)
FANOUT = re.compile(r"Promise\.all\s*\(\s*\w+\.map|for\s*\(\s*(const|let)\s+\w+\s+of|\.map\(\s*async|forEach\(\s*async")
WEBHOOK_VERIFY = re.compile(r"constructEvent|verifySignature|createHmac|timingSafeEqual|svix|new\s+Webhook\(|verifyWebhook|validateSignature|unwrap\(", re.I)
DEV_PATH = re.compile(r"(^|/)(scripts?|bench(mark)?s?|tests?|__tests__|e2e|fixtures|examples?|seed|playground|stories)(/|$)|\.(test|spec|stories)\.\w+$", re.I)
IMPORT_RE = re.compile(r"""(?:import(?!\s+type\b)[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*)['"]([^'"]+)['"]""")


def mask(s):
    return s[:6] + "…" + s[-4:] if len(s) > 12 else "***"


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def iter_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in CODE_EXTS or ext in CONF_EXTS or f.startswith(".env") or f.endswith(".env"):
                p = os.path.join(d, f)
                try:
                    if os.path.getsize(p) <= MAX_BYTES:
                        yield p
                except OSError:
                    pass


def git_tracked_env(root):
    try:
        out = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True, timeout=20)
        return [l for l in out.stdout.splitlines()
                if re.search(r"(^|/)\.env(\.|$)|\.env$", l) and not re.search(r"example|sample|template|\.dist$", l, re.I)]
    except Exception:
        return []


def project_traits(root):
    has = lambda *names: any(os.path.exists(os.path.join(root, n)) for n in names)
    return {
        "vite": has("vite.config.ts", "vite.config.js", "vite.config.mjs"),
        "next": has("next.config.js", "next.config.ts", "next.config.mjs"),
        "cra": has("public/index.html") and not has("next.config.js", "next.config.ts", "next.config.mjs"),
    }


def where_it_runs(rel, text, traits, root):
    p = rel.replace("\\", "/")
    if CLIENT_DIRECTIVE.search(text) or p.endswith((".html", ".vue", ".svelte")) and "<script" in text and "server" not in p:
        return "browser"
    if CDN_IMPORT.search(text):
        return "browser"
    if SERVER_DIRECTIVE.search(text) or ROUTE_HANDLER.search(text):
        return "server"
    if re.search(r"(^|/)(api|server|functions|supabase/functions|netlify/functions|workers?)(/|$)|(^|/)(route|middleware|server)\.\w+$|\.server\.\w+$", p):
        return "server"
    if re.search(r"process\.env\.(?!NEXT_PUBLIC_)[A-Z_]*KEY", text) and not re.search(r"import\.meta\.env", text):
        return "server"  # reads non-public env: server-side code (or broken in browser)
    if re.search(r"import\.meta\.env\.VITE_|process\.env\.(REACT_APP_|EXPO_PUBLIC_)", text):
        return "browser"
    if re.search(r"(^|/)src/", p) and not re.search(r"(^|/)(server|api)(/|$)", p):
        d = os.path.dirname(os.path.join(root, rel))
        while d.startswith(root):
            if any(os.path.exists(os.path.join(d, f)) for f in ("vite.config.js", "vite.config.ts", "vite.config.mjs")) or \
               (os.path.exists(os.path.join(d, "public", "index.html")) and not any(os.path.exists(os.path.join(d, f)) for f in ("next.config.js", "next.config.ts", "next.config.mjs"))):
                return "browser"
            if d == root:
                break
            d = os.path.dirname(d)
    # plain static site: js next to an index.html, no server folder
    d = os.path.dirname(os.path.join(root, rel))
    if p.endswith((".js", ".mjs")) and os.path.exists(os.path.join(d, "index.html")):
        return "browser"
    return "unknown"


def resolve_import(spec, from_file, root, files_set):
    if spec.startswith("@/") or spec.startswith("~/"):
        bases = [os.path.join(root, spec[2:]), os.path.join(root, "src", spec[2:])]
    elif spec.startswith("."):
        bases = [os.path.normpath(os.path.join(os.path.dirname(from_file), spec))]
    else:
        return None
    for b in bases:
        for cand in [b] + [b + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs")] + [os.path.join(b, "index" + e) for e in (".ts", ".tsx", ".js")]:
            if cand in files_set:
                return cand
    return None


def guards_of(text):
    return {g: bool(rx.search(text)) for g, rx in GUARDS.items()}


def scan(root):
    root = os.path.abspath(root)
    traits = project_traits(root)
    texts = {}
    for p in iter_files(root):
        try:
            texts[p] = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            pass
    files_set = set(texts)

    # import graph: who imports whom (code files only)
    importers = {}
    for p, t in texts.items():
        if os.path.splitext(p)[1] not in CODE_EXTS:
            continue
        for spec in IMPORT_RE.findall(t):
            tgt = resolve_import(spec, p, root, files_set)
            if tgt:
                importers.setdefault(tgt, set()).add(p)

    def upstream_entries(p, depth=0, seen=None):
        """Route/server-action files that (transitively) import p."""
        seen = seen or set()
        out = []
        for imp in importers.get(p, ()):
            if imp in seen:
                continue
            seen.add(imp)
            t = texts[imp]
            if ROUTE_HANDLER.search(t) or SERVER_DIRECTIVE.search(t) or CLIENT_DIRECTIVE.search(t):
                out.append(imp)
            elif depth < 4:
                out.extend(upstream_entries(imp, depth + 1, seen))
        return out

    tracked_env = git_tracked_env(root)
    spend, keys, public_env, webhooks = [], [], [], []

    for p, text in texts.items():
        rel = os.path.relpath(p, root).replace("\\", "/")
        base = os.path.basename(p)
        ext = os.path.splitext(p)[1].lower()
        is_env = base.startswith(".env") or base.endswith(".env")
        if base in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"):
            continue
        is_example = bool(re.search(r"example|sample|template", base, re.I))

        for label, pat in KEY_PATTERNS:
            for m in re.finditer(pat, text):
                v = m.group(0)
                if label == "OpenAI key" and v.startswith(("sk-ant-", "sk-or-")):
                    continue
                if re.search(r"x{6,}|\.\.\.|your|example|placeholder", v, re.I):
                    continue
                tracked = rel in tracked_env
                keys.append({"type": label, "file": rel, "line": line_of(text, m.start()), "value": mask(v),
                             "in_env_file": is_env, "git_tracked": tracked or not is_env,
                             "severity": "yellow" if (is_env and not tracked) else "red"})

        for m in PUBLIC_SECRET_ENV.finditer(text):
            name = m.group(0)
            if PUBLIC_ENV_NOT_SECRET.search(name):
                continue
            by_design = bool(PUBLIC_BY_DESIGN.search(name))
            public_env.append({"name": name, "file": rel, "line": line_of(text, m.start()),
                               "severity": "yellow" if by_design else "red",
                               "why": "public-by-design key? confirm it is restricted (referrer/domain/quota)" if by_design
                                      else "secret-looking key is bundled into the browser"})

        if is_env or ext in CONF_EXTS:
            continue

        if "webhook" in rel.lower() and ROUTE_HANDLER.search(text):
            webhooks.append({"file": rel, "verified": bool(WEBHOOK_VERIFY.search(text))})

        runs = where_it_runs(rel, text, traits, root)
        is_dev = bool(DEV_PATH.search(rel))
        for prov, kind, pat in SPEND:
            m = None
            for mm in re.finditer(pat, text):
                tail = text[mm.end():mm.end() + 30]
                if re.match(r"[^'\"`]*?/models['\"`]", tail):
                    continue  # model-list endpoints are free
                m = mm; break
            if not m:
                continue
            g = guards_of(text)
            entry = bool(ROUTE_HANDLER.search(text) or SERVER_DIRECTIVE.search(text))
            ups = [] if entry else upstream_entries(p)
            inherited_from = []
            if ups:
                for u in ups:
                    ug = guards_of(texts[u])
                    for k in g:
                        g[k] = g[k] or ug[k]
                    inherited_from.append(os.path.relpath(u, root).replace("\\", "/"))
                if runs == "unknown":
                    runs = "browser" if any(CLIENT_DIRECTIVE.search(texts[u]) for u in ups) else "server"
            spend.append({
                "provider": prov, "kind": kind, "file": rel, "line": line_of(text, m.start()),
                "match": m.group(0)[:60], "runs_in": runs, "entrypoint": entry,
                "called_from": inherited_from[:5], "guards": g, "dev_only": is_dev,
                "byok": bool(BYOK.search(text)),
                "has_credential": bool(CREDENTIAL.search(text)),
                "model_from_request": bool(MODEL_FROM_BODY.search(text)) and bool(BODY_READ.search(text)) and not MODEL_ALLOWLIST.search(text),
                "max_tokens_from_request": bool(MAXTOK_FROM_BODY.search(text)),
                "possible_fanout": bool(FANOUT.search(text)),
            })

    for s in spend:
        g = s["guards"]
        if s["dev_only"]:
            s["severity"], s["why"] = "green", "dev/test script — not reachable by users (confirm it isn't deployed)"
        elif s["byok"]:
            s["severity"], s["why"] = "green", "uses the user's own API key (BYOK) — their bill, not yours; check no fallback to your env key"
        elif s["runs_in"] == "browser" and s["kind"] not in ("Maps", "Storage") and not s["has_credential"]:
            s["severity"], s["why"] = "yellow", "provider SDK used in the browser but no key in this file — likely calls your own endpoint; confirm"
        elif s["runs_in"] == "browser" and s["kind"] not in ("Maps", "Storage"):
            s["severity"], s["why"] = "red", "paid call runs in the browser — key is public"
        elif s["model_from_request"] or s["max_tokens_from_request"]:
            s["severity"], s["why"] = "red", "client controls model / max_tokens"
        elif s["kind"] == "Storage" and not s["entrypoint"] and s["runs_in"] != "server":
            s["severity"], s["why"] = "yellow", "client-side upload — check bucket policy, file size limit, per-user quota"
        elif not s["entrypoint"] and not s["called_from"] and s["runs_in"] != "browser":
            s["severity"], s["why"] = "yellow", "helper with no caller found — check which endpoint calls it and its guards"
        elif not g["auth"] and not g["rate_limit"]:
            s["severity"], s["why"] = "red", "no auth and no rate limit found — anyone can call it"
        elif not g["rate_limit"]:
            s["severity"], s["why"] = "yellow", "auth but no per-user quota (free signup = anyone)"
        elif s["kind"] == "LLM" and not g["max_tokens"]:
            s["severity"], s["why"] = "yellow", "rate-limited, but no max_tokens cap"
        elif not g["auth"]:
            s["severity"], s["why"] = "green", "IP/global rate limit, no auth — check the limit is low enough"
        else:
            s["severity"], s["why"] = "green", "auth + rate limit found (confirm they apply to this call)"
        if s["called_from"]:
            s["why"] += f" [guards inherited from {s['called_from'][0]}]"
        if s["possible_fanout"] and s["severity"] == "green" and not s["dev_only"]:
            s["severity"] = "yellow"; s["why"] += "; loop over items — check fan-out"

    for k in keys:
        if k["in_env_file"] and not k["git_tracked"]:
            k["severity"] = "yellow"

    env_files = []
    for f in tracked_env:
        t = texts.get(os.path.join(root, f), "")
        vals = [l for l in t.splitlines() if "=" in l and not l.strip().startswith("#")]
        real = [l for l in vals if not PLACEHOLDER.search(l)]
        env_files.append({"file": f, "severity": "red" if real else "yellow",
                          "why": "contains real-looking values" if real else "only placeholders — but add it to .gitignore"})

    for w in webhooks:
        w["severity"] = "green" if w["verified"] else "red"

    return {"root": root, "traits": traits, "spend_points": spend, "exposed_keys": keys,
            "public_secret_env": public_env, "git_tracked_env_files": env_files, "webhooks": webhooks}


ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
ORDER = ["red", "yellow", "green"]


def print_summary(r):
    print(f"Wallet X-Ray scan: {r['root']}\n")
    sp = r["spend_points"]
    counts = {c: sum(1 for s in sp if s["severity"] == c) for c in ORDER}
    print(f"Spend points: {len(sp)}  ({counts['red']} 🔴  {counts['yellow']} 🟡  {counts['green']} 🟢)")
    for s in sorted(sp, key=lambda x: (ORDER.index(x["severity"]), x["file"])):
        print(f"  {ICON[s['severity']]} [{s['kind']}/{s['provider']}] {s['file']}:{s['line']}  ({s['runs_in']}) — {s['why']}")
    print(f"\nHard-coded keys: {len(r['exposed_keys'])}")
    for k in r["exposed_keys"]:
        where = "env file (not in git)" if k["severity"] == "yellow" else "CODE or git-tracked"
        print(f"  {ICON[k['severity']]} {k['type']} {k['value']} at {k['file']}:{k['line']} — {where}")
    seen = {}
    for e in r["public_secret_env"]:
        seen.setdefault(e["name"], e)
    print(f"\nKey-like PUBLIC env vars (shipped to browser): {len(seen)}")
    for e in seen.values():
        print(f"  {ICON[e['severity']]} {e['name']}  (first seen {e['file']}:{e['line']}) — {e['why']}")
    if r["git_tracked_env_files"]:
        print("\n.env files tracked by git:")
        for e in r["git_tracked_env_files"]:
            print(f"  {ICON[e['severity']]} {e['file']} — {e['why']}")
    print(f"\nWebhooks: {len(r['webhooks'])}")
    for w in r["webhooks"]:
        print(f"  {ICON[w['severity']]} {w['file']} — {'signature check found' if w['verified'] else 'NO signature check found'}")
    print("\nHeuristic results. Open each flagged file and confirm before reporting.")


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json"); out = args[i + 1]; del args[i:i + 2]
    res = scan(args[0] if args else ".")
    print_summary(res)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\nJSON written to {out}")

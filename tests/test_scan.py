import os, subprocess, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "skills", "wallet-xray", "scripts", "scan.py")
CALC = os.path.join(ROOT, "skills", "wallet-xray", "scripts", "cost_calc.py")
APP = os.path.join(ROOT, "examples", "leaky-app")

def run_scan():
    out = os.path.join(tempfile.mkdtemp(), "r.json")
    subprocess.run([sys.executable, SCAN, APP, "--json", out], check=True, capture_output=True)
    return json.load(open(out))

def test_spend_points():
    r = run_scan()
    sev = {s["file"].replace("\\", "/"): s["severity"] for s in r["spend_points"]}
    assert sev["app/chat/page.tsx"] == "red"          # browser call
    assert sev["app/api/explain/route.ts"] == "red"   # model from body
    assert sev["app/api/safe/route.ts"] == "green"    # guarded

def test_keys_and_env():
    r = run_scan()
    types = {k["type"] for k in r["exposed_keys"]}
    assert "OpenAI key" in types
    assert any(e["name"] == "NEXT_PUBLIC_GEMINI_API_KEY" for e in r["public_secret_env"])
    assert all("FAKEKEY" not in k["value"] or "…" in k["value"] for k in r["exposed_keys"])  # masked

def test_webhooks():
    r = run_scan()
    w = {x["file"].replace("\\", "/"): x["verified"] for x in r["webhooks"]}
    assert w["app/api/webhook/creem/route.ts"] is False
    assert w["app/api/webhook/stripe/route.ts"] is True

def test_cost_calc_runs():
    ex = os.path.join(ROOT, "skills", "wallet-xray", "references", "cost_input_example.json")
    p = subprocess.run([sys.executable, CALC, ex], check=True, capture_output=True, text=True)
    assert "Worst-case burn" in p.stdout and "margin" in p.stdout


# --- regressions found by testing on real open-source apps ---
PAT = os.path.join(ROOT, "tests", "fixtures", "patterns")

def scan_pat():
    out = os.path.join(tempfile.mkdtemp(), "p.json")
    subprocess.run([sys.executable, SCAN, PAT, "--json", out], check=True, capture_output=True)
    r = json.load(open(out))
    return r, {(s["file"], s["provider"]): s for s in r["spend_points"]}

def test_fetch_replicate_detected_and_camelcase_ratelimit():
    _, sp = scan_pat()
    s = sp[("app/api/gen/route.ts", "image-gen")]          # raw fetch() to Replicate used to be missed
    assert s["guards"]["rate_limit"]                        # enforceRateLimit (capital R) used to be missed
    assert s["severity"] == "green"

def test_helper_inherits_guards_from_route():
    _, sp = scan_pat()
    s = sp[("lib/ai.ts", "ai-sdk")]
    assert "app/api/chat/route.ts" in s["called_from"]
    assert s["severity"] == "green"                        # auth + hourly limit + maxOutputTokens
    assert s["runs_in"] == "server"                         # `import type` from a client page must not flip it

def test_byok_is_not_your_bill():
    _, sp = scan_pat()
    assert sp[("app/api/byok/route.ts", "openai")]["byok"]
    assert sp[("app/api/byok/route.ts", "openai")]["severity"] == "green"

def test_noise_filtered():
    r, sp = scan_pat()
    assert ("lib/models.ts", "openrouter") not in sp        # free /models listing
    assert sp[("scripts/bench.ts", "openai")]["dev_only"]
    assert not any("ORGANIZATION_ID" in e["name"] for e in r["public_secret_env"])

def test_literal_key_in_browser_constructor():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "index.html"), "w").write("<script type=module src=script.js></script>")
    open(os.path.join(d, "script.js"), "w").write('import { GoogleGenerativeAI } from "https://esm.run/@google/generative-ai";\nconst c = new GoogleGenerativeAI("your_key_here");\nc.getGenerativeModel({}).generateContent("x");\n')
    out = os.path.join(d, "r.json")
    subprocess.run([sys.executable, SCAN, d, "--json", out], check=True, capture_output=True)
    s = json.load(open(out))["spend_points"][0]
    assert s["runs_in"] == "browser" and s["severity"] == "red"

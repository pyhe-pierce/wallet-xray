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

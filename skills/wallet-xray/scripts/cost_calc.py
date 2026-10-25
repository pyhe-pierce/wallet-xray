#!/usr/bin/env python3
"""Wallet X-Ray cost calculator.
Usage: python3 cost_calc.py input.json
Input shape: see references/cost_input_example.json

Prints: cost per user (light/typical/heavy), worst-case burn per hour, margin,
and — if any spend point has an "after" block — a before/after comparison.

Every worst-case number is labelled by how much you can trust its request cap:
  confirmed  — a limit you verified in code or a provider dashboard
  estimated  — your guess (e.g. provider RPM from docs, not checked)
  unbounded  — no limit found; the $ figure is only "at this assumed rate",
               the real ceiling is whatever the provider lets through
"""
import json, sys

LIMIT_LABEL = {
    "confirmed": "confirmed limit",
    "estimated": "ESTIMATED limit",
    "unbounded": "NO LIMIT — figure assumes this rate; real ceiling is the provider's",
}


def merged(sp, overrides):
    d = dict(sp); d.update(overrides or {}); return d


def call_cost(sp, which="avg"):
    i = sp.get(f"{which}_input_tokens", 0); o = sp.get(f"{which}_output_tokens", 0)
    c = i * sp.get("in_price_per_m", 0) / 1e6 + o * sp.get("out_price_per_m", 0) / 1e6
    c += sp.get("fixed_fee_per_call", 0)
    return c * sp.get("fanout", 1)


def limit_source(sp):
    src = sp.get("limit_source")
    if src in LIMIT_LABEL:
        return src
    # backwards compatible with v0.1 inputs
    return "confirmed" if sp.get("rate_limited") else "unbounded"


def worst_per_hour(sp):
    return call_cost(sp, "max") * sp.get("max_requests_per_hour", 0)


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    cur = d.get("currency", "USD"); sym = "$" if cur == "USD" else cur + " "
    sps = d["spend_points"]
    total_share = sum(sp.get("share_of_calls", 0) for sp in sps) or 1
    blended = sum(call_cost(sp) * sp.get("share_of_calls", 0) for sp in sps) / total_share

    print(f"== Wallet X-Ray: {d.get('app', 'app')} ==")
    print(f"Prices: {d.get('prices_checked', 'NOT CHECKED — verify!')}\n")
    print("Per-call cost (avg / max):")
    for sp in sps:
        print(f"  {sp['name']:<34} {sym}{call_cost(sp):.5f} / {sym}{call_cost(sp, 'max'):.4f}")
    print(f"  blended avg per call: {sym}{blended:.5f}\n")

    prof = d.get("usage_profiles", {"light": 10, "typical": 50, "heavy": 300})
    print("1) Cost per active user per month:")
    per_user = {}
    for k, n in prof.items():
        per_user[k] = blended * n
        print(f"  {k:<8} {n:>5} calls → {sym}{per_user[k]:.2f}")

    print("\n2) Worst-case burn per hour (max tokens × max requests on one endpoint):")
    rows = sorted(((worst_per_hour(sp), sp) for sp in sps), key=lambda x: -x[0])
    for h, sp in rows:
        src = limit_source(sp)
        prefix = "≥ " if src == "unbounded" else ("~ " if src == "estimated" else "")
        print(f"  {sp['name']:<34} {prefix}{sym}{h:,.2f}/h  ≈ {prefix}{sym}{h*24:,.0f}/day")
        print(f"  {'':<34} at {sp.get('max_requests_per_hour', 0):,} req/h — {LIMIT_LABEL[src]}")
    if any(limit_source(sp) == "unbounded" for sp in sps):
        print("  ⚠ Unbounded endpoints have no real upper bound. Treat the $ figure as an example, not a ceiling.")

    price = d.get("price_per_month")
    if price:
        fee = price * d.get("payment_fee_pct", 0) / 100 + d.get("payment_fee_fixed", 0)
        typ = per_user.get("typical", blended * 50)
        free_n = d.get("free_users", 0); paid_n = d.get("paying_users", 0) or 1
        free_cost_total = free_n * typ * d.get("free_user_usage_ratio", 0.2)
        free_share = free_cost_total / paid_n
        net = price - fee - typ - free_share
        print("\n3) Margin per paying user (typical usage):")
        print(f"  price {sym}{price:.2f} − fees {sym}{fee:.2f} − own usage {sym}{typ:.2f} − free-user share {sym}{free_share:.2f}")
        print(f"  = {sym}{net:.2f}  → margin {net/price*100:.0f}%")
        heavy_net = price - fee - per_user.get("heavy", typ) - free_share
        print(f"  heavy user margin: {heavy_net/price*100:.0f}%")
        unit = price - fee - typ
        if unit > 0:
            print(f"  break-even (covering free users' AI cost): {free_cost_total/unit:.0f} paying users")
        else:
            print("  ⚠ each paying user loses money at typical usage")

    # 4) before / after
    if any("after" in sp for sp in sps):
        print("\n4) Before / after fixes (worst case per hour):")
        tb = ta = 0.0
        honest = True
        for sp in sps:
            after = merged(sp, sp.get("after"))
            b, a = worst_per_hour(sp), worst_per_hour(after)
            tb += b; ta += a
            sa = limit_source(after)
            if sa != "confirmed":
                honest = False
            print(f"  {sp['name']:<34} {sym}{b:,.2f}/h → {sym}{a:,.2f}/h   (after: {LIMIT_LABEL[sa]})")
        red = (1 - ta / tb) * 100 if tb else 0
        print(f"  total                              {sym}{tb:,.2f}/h → {sym}{ta:,.2f}/h   exposure −{red:.1f}%")
        if not honest:
            print("  ⚠ Some 'after' limits are not confirmed. Verify them in code before quoting this number.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1])

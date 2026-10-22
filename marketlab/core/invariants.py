"""회계 불변식 검사. 설계안 §2·§8-1.

crossed_ok: 일괄 경매의 수집 단계에서는 호가장이 교차 상태로 존재하는 것이
정상이므로, 교차 검사를 라운드 경계에서만 켠다.
"""


def check_invariants(state, totals, crossed_ok=False):
    errs = []
    tc = sum(a["cash"] + a["res_cash"] for a in state["accounts"].values())
    ts = sum(a["shares"] + a["res_shares"] for a in state["accounts"].values())
    if (tc, ts) != totals:
        errs.append(f"conservation broken: cash {tc}!={totals[0]} or shares {ts}!={totals[1]}")
    for ag, a in state["accounts"].items():
        for f in ("cash", "res_cash", "shares", "res_shares"):
            if a[f] < 0:
                errs.append(f"negative {f} for {ag}: {a[f]}")
    exp_res_cash, exp_res_shares = {}, {}
    for book, side in ((state["bids"], "buy"), (state["asks"], "sell")):
        for oid in book:
            o = state["orders"][oid]
            if o["status"] != "open" or o["remaining"] <= 0:
                errs.append(f"book holds non-open order {oid}")
            if side == "buy":
                exp_res_cash[o["agent"]] = (exp_res_cash.get(o["agent"], 0)
                                            + o["price"] * o["remaining"])
            else:
                exp_res_shares[o["agent"]] = (exp_res_shares.get(o["agent"], 0)
                                              + o["remaining"])
    for ag, a in state["accounts"].items():
        if a["res_cash"] != exp_res_cash.get(ag, 0):
            errs.append(f"res_cash mismatch for {ag}: {a['res_cash']} != {exp_res_cash.get(ag, 0)}")
        if a["res_shares"] != exp_res_shares.get(ag, 0):
            errs.append(f"res_shares mismatch for {ag}: {a['res_shares']} != {exp_res_shares.get(ag, 0)}")
    if not crossed_ok and state["bids"] and state["asks"]:
        if (state["orders"][state["bids"][0]]["price"]
                >= state["orders"][state["asks"][0]]["price"]):
            errs.append("book is crossed")
    return errs

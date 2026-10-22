"""클론 정책 100회 자동 실행 러너.

파일럿의 수동 중계 루프를 자동화한 것: 결정 공급원만 '클론 실시간 응답'에서
'클론이 작성한 정책 코드(policies.py)'로 교체했다. 유료 API가 승인되면 같은
자리에 M4 LiveAdapter(매 틱 LLM 판단)를 꽂을 수 있다.

설계 반영 사항:
  - 종료 효과 차단: 에이전트는 전체 라운드 수를 모른다 (파일럿 교훈)
  - 교체는 원자적 cancel-replace (이중 노출 방지, M2 교훈) — 기존 미체결과
    새 주문을 순서대로 짝지어 교체, 남는 기존 주문은 취소
  - 런별 격리: 런마다 새 엔진·새 에이전트·파생 시드 (오염 원천 없음)
  - 매 런 종료 시 회계 불변식 검사 + 런0 결정론 재확인

실행: python3 experiments/claude-pilot/auto100.py [runs] [rounds]
"""

import json
import pathlib
import random
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketlab.core.engine import MarketEngine            # noqa: E402
from marketlab.core.invariants import check_invariants    # noqa: E402
from marketlab.core.state import state_hash               # noqa: E402
from marketlab.disclosure.policies import BestQuoteOnly   # noqa: E402
from marketlab.gateway.ingress import Gateway             # noqa: E402
from marketlab.mechanisms.cda import CDA                  # noqa: E402
from marketlab.mechanisms.call_auction import CallAuction  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from policies import PERSONAS                             # noqa: E402

FUNDAMENTAL = 100
MECHANISMS = {"cda": CDA, "call_auction": CallAuction}


def apply_decision(gw, eng, aid, orders, rnd, tag):
    """기존 미체결과 새 주문을 짝지어 원자 교체, 잉여는 취소/신규 제출."""
    open_oids = sorted(oid for oid, o in eng.state["orders"].items()
                       if o["agent"] == aid and o["status"] == "open")
    if orders is None:
        return                                   # HOLD: 대기주문 유지
    for j, o in enumerate(orders):
        oid = f"t{rnd}-{aid}-{j}-{tag}"
        if j < len(open_oids):
            gw.cancel_replace(open_oids[j], oid, aid, o["side"], o["price"],
                              o["qty"], gw.epoch)
        else:
            gw.submit(oid, aid, o["side"], o["price"], o["qty"], gw.epoch)
    for leftover in open_oids[len(orders):]:
        gw.cancel(leftover, gw.epoch)


def run_once(run_seed, rounds, mechanism="cda", personas=None):
    personas = personas or PERSONAS
    eng = MarketEngine(MECHANISMS[mechanism](), BestQuoteOnly(), seed=run_seed)
    gw = Gateway(eng)
    agents = {}
    for aid, (cls, cash, shares) in personas.items():
        agents[aid] = cls(aid, cash, shares, seed=f"{aid}-{run_seed}")
        gw.create_account(aid, cash, shares)
    totals = (sum(c for _, c, _ in personas.values()),
              sum(s for _, _, s in personas.values()))

    recent, seen = [], 0
    shuffle_rng = random.Random(f"auto-shuffle-{run_seed}")
    for r in range(rounds):
        snaps = {aid: gw.snapshot(aid) for aid in agents}
        ctx = {"round": r, "recent": list(recent)}
        decisions = [(aid, agents[aid].decide(snaps[aid], ctx)) for aid in agents]
        shuffle_rng.shuffle(decisions)
        for aid, orders in decisions:
            apply_decision(gw, eng, aid, orders, r, run_seed)
        gw.clock()
        for ev in eng.log[seen:]:
            if ev["type"] == "trade":
                recent.append(ev["price"])
        recent = recent[-5:]
        seen = len(eng.log)

    errs = check_invariants(eng.state, totals)
    trades = [ev for ev in eng.log if ev["type"] == "trade"]
    prices = [ev["price"] for ev in trades]
    last = prices[-1] if prices else None
    row = {"run": run_seed, "n_trades": len(trades),
           "volume": sum(ev["qty"] for ev in trades),
           "last_price": last,
           "max_price": max(prices) if prices else None,
           "min_price": min(prices) if prices else None,
           "violations": len(errs), "hash": state_hash(eng.state)[:16]}
    for aid, (_, cash0, shares0) in personas.items():
        a = eng.state["accounts"][aid]
        cash = a["cash"] + a["res_cash"]
        sh = a["shares"] + a["res_shares"]
        row[f"pnl100_{aid}"] = (cash + sh * FUNDAMENTAL) - (cash0 + shares0 * FUNDAMENTAL)
        mark = last if last is not None else FUNDAMENTAL
        row[f"pnlL_{aid}"] = (cash + sh * mark) - (cash0 + shares0 * mark)
    return row


def summarize(rows, key):
    xs = [r[key] for r in rows if r[key] is not None]
    if not xs:
        return None
    return {"mean": statistics.mean(xs),
            "sd": statistics.stdev(xs) if len(xs) > 1 else 0,
            "min": min(xs), "max": max(xs)}


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    mechanism = sys.argv[3] if len(sys.argv) > 3 else "cda"
    variant = sys.argv[4] if len(sys.argv) > 4 else "base"
    if variant == "anchored":
        from policies_anchored import PERSONAS as personas
    else:
        personas = PERSONAS
    rows = [run_once(s, rounds, mechanism, personas) for s in range(n_runs)]

    # 결정론 확인: 런0 재실행 해시 일치
    assert run_once(0, rounds, mechanism, personas)["hash"] == rows[0]["hash"], "non-deterministic run!"
    assert sum(r["violations"] for r in rows) == 0, "invariant violations!"

    out = {"runs": n_runs, "rounds": rounds, "mechanism": mechanism,
           "variant": variant,
           "market": {k: summarize(rows, k) for k in
                      ("n_trades", "volume", "last_price", "max_price", "min_price")},
           "runs_end_above_105": sum(1 for r in rows if (r["last_price"] or 0) > 105),
           "runs_end_below_95": sum(1 for r in rows
                                    if r["last_price"] is not None and r["last_price"] < 95),
           "runs_no_trades": sum(1 for r in rows if r["n_trades"] == 0),
           "pnl_at_fundamental_100": {}, "pnl_at_last_price": {}}
    for aid in personas:
        s100 = summarize(rows, f"pnl100_{aid}")
        sL = summarize(rows, f"pnlL_{aid}")
        s100["win_rate"] = sum(1 for r in rows if r[f"pnl100_{aid}"] > 0) / n_runs
        sL["win_rate"] = sum(1 for r in rows if r[f"pnlL_{aid}"] > 0) / n_runs
        out["pnl_at_fundamental_100"][aid] = s100
        out["pnl_at_last_price"][aid] = sL

    here = pathlib.Path(__file__).parent
    suffix = ("" if mechanism == "cda" else f"-{mechanism}") + ("" if variant == "base" else f"-{variant}")
    (here / f"auto100-rows{suffix}.json").write_text(json.dumps(rows, indent=1))
    (here / f"auto100-summary{suffix}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

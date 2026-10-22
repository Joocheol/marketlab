"""클로드 클론 파일럿 드라이버 (API 미사용).

LLM = 이 세션이 띄운 클로드 서브에이전트 클론들. 이 드라이버는 시장 쪽만
맡는다: 상태는 도착 로그(재현 패키지)로 라운드 사이를 잇고, 오케스트레이터
(세션의 클로드)가 라운드마다 클론들의 주문을 decisions JSON으로 넘긴다.
클론과의 왕복 전문은 state/round-*.json(판단 로그)으로 남아 재현 가능하다.

사용:
  python3 driver.py init                     # 시장 생성, 스냅샷 출력
  python3 driver.py round <decisions.json>   # 한 라운드 집행, 결과·스냅샷 출력
  python3 driver.py summary                  # 체결·손익 요약
"""

import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketlab.core.engine import MarketEngine            # noqa: E402
from marketlab.core.invariants import check_invariants    # noqa: E402
from marketlab.core.state import state_hash               # noqa: E402
from marketlab.disclosure.policies import BestQuoteOnly   # noqa: E402
from marketlab.gateway.ingress import Gateway             # noqa: E402
from marketlab.mechanisms.cda import CDA                  # noqa: E402

STATE = pathlib.Path(__file__).parent / "state"
RECORD = STATE / "record.json"
SEED = 7

CLONES = {   # agent_id: (cash, shares) — 위험한도는 클론 프롬프트와 분석에서 관리
    "momentum": (2500, 20),
    "value": (2500, 20),
    "mm": (2500, 30),
    "conservative": (2500, 20),
    "aggressive": (2500, 20),
}
META = {"factors": {"mechanism": "cda", "info_policy": "best_quote_only",
                    "population": "claude-clones-x5", "clock": {"mode": "sync"}},
        "seed": SEED, "note": "LLM = in-session Claude clones, no API"}


def fresh_engine():
    return MarketEngine(CDA(), BestQuoteOnly(), seed=SEED)


def load():
    record = json.loads(RECORD.read_text())
    eng = fresh_engine()
    gw = Gateway(eng)
    from marketlab.gateway.ingress import replay_record
    replayed = replay_record(record, lambda meta: eng)
    assert replayed is eng
    gw.arrivals = list(record["arrivals"])
    return eng, gw


def save(gw):
    from marketlab.gateway.ingress import make_record
    RECORD.write_text(json.dumps(make_record(gw, META)))


def snapshots(eng):
    out = {}
    for aid in CLONES:
        s = eng.state
        out[aid] = eng.info_policy.view(s, aid)
    return out


def cmd_init():
    STATE.mkdir(exist_ok=True)
    eng = fresh_engine()
    gw = Gateway(eng)
    for aid, (cash, shares) in CLONES.items():
        gw.create_account(aid, cash, shares)
    save(gw)
    print(json.dumps({"tick": eng.state["tick"], "snapshots": snapshots(eng)},
                     ensure_ascii=False, indent=1))


def cmd_round(path):
    spec = json.loads(pathlib.Path(path).read_text())
    eng, gw = load()
    n = eng.state["tick"]
    before = {aid: dict(eng.state["accounts"][aid]) for aid in CLONES}

    decisions = list(spec["decisions"])
    random.Random(f"pilot-shuffle-{n}").shuffle(decisions)
    for d in decisions:
        aid = d["agent"]
        if d.get("action") in ("hold", None) and not d.get("orders"):
            continue
        if d.get("action") == "abstain":
            gw.abstain(aid, d.get("reason", "no_decision"))
            continue
        open_oids = sorted(
            oid for oid, o in eng.state["orders"].items()
            if o["agent"] == aid and o["status"] == "open")
        for j, o in enumerate(d.get("orders", [])):
            oid = f"r{n}-{aid}-{j}"
            if j == 0 and open_oids:
                gw.cancel_replace(open_oids[0], oid, aid, o["side"],
                                  o["price"], o["qty"], gw.epoch)
            else:
                gw.submit(oid, aid, o["side"], o["price"], o["qty"], gw.epoch)
    gw.clock()
    save(gw)

    trades = [ev for ev in eng.log if ev["type"] == "trade"]
    result = {"tick": eng.state["tick"], "ref_price": eng.state["ref_price"],
              "trades_total": len(trades),
              "fills": {}, "snapshots": snapshots(eng),
              "state_hash": state_hash(eng.state)[:16]}
    for aid in CLONES:
        a = eng.state["accounts"][aid]
        result["fills"][aid] = {
            "d_cash": a["cash"] + a["res_cash"] - before[aid]["cash"] - before[aid]["res_cash"],
            "d_shares": a["shares"] + a["res_shares"] - before[aid]["shares"] - before[aid]["res_shares"]}
    totals = (sum(c for c, _ in CLONES.values()), sum(s for _, s in CLONES.values()))
    errs = check_invariants(eng.state, totals)
    if errs:
        result["INVARIANT_VIOLATIONS"] = errs
    print(json.dumps(result, ensure_ascii=False, indent=1))


def cmd_summary():
    eng, gw = load()
    mark = eng.state["ref_price"] or 100
    rows = {}
    for aid, (cash0, shares0) in CLONES.items():
        a = eng.state["accounts"][aid]
        w0 = cash0 + shares0 * mark
        w1 = a["cash"] + a["res_cash"] + (a["shares"] + a["res_shares"]) * mark
        rows[aid] = {"cash": a["cash"] + a["res_cash"],
                     "shares": a["shares"] + a["res_shares"],
                     "pnl_at_mark": w1 - w0}
    trades = [(ev["seq"], ev["price"], ev["qty"],
               eng.state["orders"][ev["buy_oid"]]["agent"],
               eng.state["orders"][ev["sell_oid"]]["agent"])
              for ev in eng.log if ev["type"] == "trade"]
    print(json.dumps({"tick": eng.state["tick"], "mark": mark, "clones": rows,
                      "trades": trades,
                      "abstained": eng.state["abstained"],
                      "rejections": eng.state["rejections"],
                      "state_hash": state_hash(eng.state)[:16]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "init":
        cmd_init()
    elif sys.argv[1] == "round":
        cmd_round(sys.argv[2])
    elif sys.argv[1] == "summary":
        cmd_summary()
    else:
        raise SystemExit("usage: driver.py init | round <decisions.json> | summary")

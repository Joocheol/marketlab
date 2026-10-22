"""상태와 이벤트 적용(apply): 이벤트 로그의 순수 폴드.

설계안 §2. 이 모듈에는 매칭·검증 로직이 없다. 어떤 이벤트가 정당한지는
엔진(process 쪽)이 결정하고, 여기서는 이미 확정된 이벤트를 상태에 반영만 한다.
재생(replay)은 이 모듈만으로 수행된다.
"""

import hashlib
import json

SCHEMA_VERSION = 1


def new_state():
    return {
        "v": SCHEMA_VERSION,
        "epoch": 0,
        "seq": 0,                 # 이벤트 일련번호 (사건 전순서)
        "tick": 0,                # 논리적 시간 (clock_advanced로만 증가)
        "ref_price": None,        # 직전 체결/클리어링 가격 (경매 타이브레이크 기준)
        "accounts": {},           # agent -> {cash, res_cash, shares, res_shares}
        "orders": {},             # oid -> {agent, side, price, qty, remaining, status, epoch, seq}
        "bids": [],               # 미체결 매수 oid, (가격 내림차순, seq 오름차순)
        "asks": [],               # 미체결 매도 oid, (가격 오름차순, seq 오름차순)
        "rejections": {"duplicate": 0, "stale_epoch": 0, "insufficient": 0,
                       "unknown_cancel": 0, "bad_qty": 0, "replace_target_gone": 0},
        "published": 0,           # info_published 횟수
        "abstained": 0,           # 기권(타임아웃·판단 실패) 횟수 — 결측이 아니라 데이터
    }


def state_hash(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _book_insert(state, oid):
    o = state["orders"][oid]
    if o["side"] == "buy":
        book = state["bids"]
        keyf = lambda x: (-state["orders"][x]["price"], state["orders"][x]["seq"])
    else:
        book = state["asks"]
        keyf = lambda x: (state["orders"][x]["price"], state["orders"][x]["seq"])
    lo, hi = 0, len(book)
    while lo < hi:
        mid = (lo + hi) // 2
        if keyf(book[mid]) <= keyf(oid):
            lo = mid + 1
        else:
            hi = mid
    book.insert(lo, oid)


def apply_event(state, ev):
    t = ev["type"]
    state["seq"] = ev["seq"]

    if t == "account_created":
        state["accounts"][ev["agent"]] = {
            "cash": ev["cash"], "res_cash": 0,
            "shares": ev["shares"], "res_shares": 0}

    elif t == "accepted":
        a = state["accounts"][ev["agent"]]
        if ev["side"] == "buy":
            cost = ev["price"] * ev["qty"]
            a["cash"] -= cost
            a["res_cash"] += cost
        else:
            a["shares"] -= ev["qty"]
            a["res_shares"] += ev["qty"]
        state["orders"][ev["oid"]] = {
            "agent": ev["agent"], "side": ev["side"], "price": ev["price"],
            "qty": ev["qty"], "remaining": ev["qty"], "status": "open",
            "epoch": ev["epoch"], "seq": ev["seq"]}
        _book_insert(state, ev["oid"])

    elif t == "trade":
        qty, price = ev["qty"], ev["price"]
        bo = state["orders"][ev["buy_oid"]]
        so = state["orders"][ev["sell_oid"]]
        buyer = state["accounts"][bo["agent"]]
        seller = state["accounts"][so["agent"]]
        # 매수자: 자기 지정가로 예약한 금액에서 체결가만 지불, 차액 환불
        buyer["res_cash"] -= bo["price"] * qty
        buyer["cash"] += (bo["price"] - price) * qty
        buyer["shares"] += qty
        seller["res_shares"] -= qty
        seller["cash"] += price * qty
        for oid_key, book in ((ev["buy_oid"], state["bids"]),
                              (ev["sell_oid"], state["asks"])):
            o = state["orders"][oid_key]
            o["remaining"] -= qty
            if o["remaining"] == 0:
                o["status"] = "filled"
                book.remove(oid_key)
        state["ref_price"] = price

    elif t == "cancelled":
        o = state["orders"][ev["oid"]]
        a = state["accounts"][o["agent"]]
        if o["side"] == "buy":
            refund = o["price"] * o["remaining"]
            a["res_cash"] -= refund
            a["cash"] += refund
            state["bids"].remove(ev["oid"])
        else:
            a["res_shares"] -= o["remaining"]
            a["shares"] += o["remaining"]
            state["asks"].remove(ev["oid"])
        o["remaining"] = 0
        o["status"] = "cancelled"

    elif t == "rejected":
        state["rejections"][ev["reason"]] += 1

    elif t == "epoch_bumped":
        state["epoch"] += 1

    elif t == "clock_advanced":
        state["tick"] += 1

    elif t == "auction_cleared":
        if ev["price"] is not None:
            state["ref_price"] = ev["price"]

    elif t == "info_published":
        state["published"] += 1

    elif t == "abstained":
        state["abstained"] += 1

    else:
        raise ValueError("unknown event type: " + t)


def replay(log):
    """이벤트 로그만으로 상태를 재구성한다. 메커니즘·검증 로직을 전혀 거치지 않는다."""
    state = new_state()
    for ev in log:
        apply_event(state, ev)
    return state

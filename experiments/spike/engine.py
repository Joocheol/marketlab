"""이벤트 소싱 연속 복식 호가(CDA) 시장 엔진 스파이크.

NetLogo 분석 보고서 10장의 설계 원칙을 그대로 구현한 최소 엔진:
  - 상태 변경의 문은 하나: 모든 변경은 submit()/cancel()/bump_epoch() 명령이
    만들어 내는 '이벤트'로만 일어난다 (단일 직렬화 지점).
  - 장부의 진실은 추가 전용 이벤트 로그: 상태 = apply(이벤트들)의 순수 폴드.
    엔진의 매칭 로직(process)은 이벤트를 '계산'만 하고, 상태 반영은 전부
    apply()를 거친다. 재생(replay)은 process 없이 apply만 다시 돌린다.
  - 멱등 주문 키: 같은 oid의 재제출은 거부 이벤트만 남기고 상태를 바꾸지 않는다.
  - epoch 표지: 세계 리셋 이후 도착한 이전 세대 주문은 거부된다
    (NetLogo Web의 '문맥 잃은 콜백' 문제의 해독제).

가격은 정수(센트), 수량은 정수. 지정가 주문만 지원(스파이크 범위).
"""

import hashlib
import json


# ---------------------------------------------------------------- 상태

def new_state():
    return {
        "epoch": 0,
        "seq": 0,                 # 이벤트 일련번호
        "accounts": {},           # agent -> {cash, res_cash, shares, res_shares}
        "orders": {},             # oid -> {agent, side, price, qty, remaining, status, epoch, seq}
        "bids": [],               # 미체결 oid, (가격 내림차순, seq 오름차순) 정렬 유지
        "asks": [],               # 미체결 oid, (가격 오름차순, seq 오름차순) 정렬 유지
        "rejections": {"duplicate": 0, "stale_epoch": 0, "insufficient": 0,
                       "unknown_cancel": 0, "bad_qty": 0},
    }


def state_hash(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ---------------------------------------------------------------- apply: 이벤트 -> 상태 (순수 폴드, 매칭 로직 없음)

def _book_insert(state, oid):
    o = state["orders"][oid]
    if o["side"] == "buy":
        book, keyf = state["bids"], (lambda x: (-state["orders"][x]["price"], state["orders"][x]["seq"]))
    else:
        book, keyf = state["asks"], (lambda x: (state["orders"][x]["price"], state["orders"][x]["seq"]))
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
            "cash": ev["cash"], "res_cash": 0, "shares": ev["shares"], "res_shares": 0}

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
        bo, so = state["orders"][ev["buy_oid"]], state["orders"][ev["sell_oid"]]
        buyer, seller = state["accounts"][bo["agent"]], state["accounts"][so["agent"]]
        # 매수자: 지정가로 예약해 둔 현금에서 체결가만큼 지불, 차액은 환불
        buyer["res_cash"] -= bo["price"] * qty
        buyer["cash"] += (bo["price"] - price) * qty
        buyer["shares"] += qty
        # 매도자: 예약 주식 인도, 현금 수취
        seller["res_shares"] -= qty
        seller["cash"] += price * qty
        for oid_key, book in ((ev["buy_oid"], state["bids"]), (ev["sell_oid"], state["asks"])):
            o = state["orders"][oid_key]
            o["remaining"] -= qty
            if o["remaining"] == 0:
                o["status"] = "filled"
                book.remove(oid_key)

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

    else:
        raise ValueError("unknown event " + t)


# ---------------------------------------------------------------- 엔진: 명령 -> 이벤트 (+즉시 apply)

class MarketEngine:
    def __init__(self):
        self.state = new_state()
        self.log = []

    def _emit(self, ev):
        ev["seq"] = self.state["seq"] + 1
        apply_event(self.state, ev)
        self.log.append(ev)
        return ev

    def create_account(self, agent, cash, shares):
        self._emit({"type": "account_created", "agent": agent,
                    "cash": cash, "shares": shares})

    def bump_epoch(self):
        self._emit({"type": "epoch_bumped"})

    def submit(self, oid, agent, side, price, qty, epoch):
        s = self.state
        if oid in s["orders"]:
            return self._emit({"type": "rejected", "reason": "duplicate", "oid": oid})
        if epoch != s["epoch"]:
            return self._emit({"type": "rejected", "reason": "stale_epoch", "oid": oid})
        if qty <= 0 or price <= 0:
            return self._emit({"type": "rejected", "reason": "bad_qty", "oid": oid})
        a = s["accounts"][agent]
        if side == "buy" and a["cash"] < price * qty:
            return self._emit({"type": "rejected", "reason": "insufficient", "oid": oid})
        if side == "sell" and a["shares"] < qty:
            return self._emit({"type": "rejected", "reason": "insufficient", "oid": oid})

        self._emit({"type": "accepted", "oid": oid, "agent": agent, "side": side,
                    "price": price, "qty": qty, "epoch": epoch})
        # 교차하는 동안 체결: 가격은 '먼저 쉬고 있던'(seq 낮은) 주문의 지정가
        while s["bids"] and s["asks"]:
            b, k = s["orders"][s["bids"][0]], s["orders"][s["asks"][0]]
            if b["price"] < k["price"]:
                break
            resting = b if b["seq"] < k["seq"] else k
            self._emit({"type": "trade", "buy_oid": s["bids"][0], "sell_oid": s["asks"][0],
                        "price": resting["price"], "qty": min(b["remaining"], k["remaining"])})
        return None

    def cancel(self, oid, epoch):
        s = self.state
        if epoch != s["epoch"]:
            return self._emit({"type": "rejected", "reason": "stale_epoch", "oid": oid})
        o = s["orders"].get(oid)
        if o is None or o["status"] != "open":
            return self._emit({"type": "rejected", "reason": "unknown_cancel", "oid": oid})
        return self._emit({"type": "cancelled", "oid": oid})


def replay(log):
    """이벤트 로그만으로 상태를 재구성한다 (매칭 로직을 전혀 거치지 않음)."""
    state = new_state()
    for ev in log:
        apply_event(state, ev)
    return state


# ---------------------------------------------------------------- 불변식 검사

def check_invariants(state, totals):
    """totals = (총현금+예약현금 기대값, 총주식+예약주식 기대값)"""
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
                exp_res_cash[o["agent"]] = exp_res_cash.get(o["agent"], 0) + o["price"] * o["remaining"]
            else:
                exp_res_shares[o["agent"]] = exp_res_shares.get(o["agent"], 0) + o["remaining"]
    for ag, a in state["accounts"].items():
        if a["res_cash"] != exp_res_cash.get(ag, 0):
            errs.append(f"res_cash mismatch for {ag}: {a['res_cash']} != {exp_res_cash.get(ag, 0)}")
        if a["res_shares"] != exp_res_shares.get(ag, 0):
            errs.append(f"res_shares mismatch for {ag}: {a['res_shares']} != {exp_res_shares.get(ag, 0)}")
    # 호가장 교차 없음 (매칭 후 최우선 매수가 < 최우선 매도가)
    if state["bids"] and state["asks"]:
        if state["orders"][state["bids"][0]]["price"] >= state["orders"][state["asks"][0]]["price"]:
            errs.append("book is crossed after matching")
    return errs

"""Gateway: 비동기 세계와 결정론 세계의 경계 (설계안 §1·§6).

엔진에 닿는 모든 상호작용(주문·취소·기권·스냅샷·시계)이 이 문을 지나며,
지나는 순서 그대로 '도착 로그(arrival log)'에 기록된다. 도착 로그와 런 설정만
있으면 에이전트·스레드·지연 없이 전체 런을 재생할 수 있다 — 재현 패키지의
핵심 구성물이다 (LLM 호출 로그는 M4에서 이 옆에 나란히 놓인다).
"""

import json

from marketlab.core.engine import MarketEngine
from marketlab.core.state import state_hash


class Gateway:
    def __init__(self, engine):
        self.engine = engine
        self.arrivals = []   # 도착 순서 그대로의 완전한 구동 기록

    # ---- 엔진으로 들어가는 모든 경로 (기록 후 실행)

    def create_account(self, agent, cash, shares):
        self.arrivals.append({"k": "acct", "agent": agent,
                              "cash": cash, "shares": shares})
        self.engine.create_account(agent, cash, shares)

    def submit(self, oid, agent, side, price, qty, epoch):
        self.arrivals.append({"k": "sub", "oid": oid, "agent": agent, "side": side,
                              "price": price, "qty": qty, "epoch": epoch})
        self.engine.submit(oid, agent, side, price, qty, epoch)

    def cancel(self, oid, epoch):
        self.arrivals.append({"k": "can", "oid": oid, "epoch": epoch})
        self.engine.cancel(oid, epoch)

    def cancel_replace(self, old_oid, new_oid, agent, side, price, qty, epoch):
        self.arrivals.append({"k": "rep", "old": old_oid, "oid": new_oid,
                              "agent": agent, "side": side, "price": price,
                              "qty": qty, "epoch": epoch})
        self.engine.cancel_replace(old_oid, new_oid, agent, side, price, qty, epoch)

    def abstain(self, agent, reason):
        self.arrivals.append({"k": "abs", "agent": agent, "reason": reason})
        self.engine.abstain(agent, reason)

    def snapshot(self, agent):
        self.arrivals.append({"k": "snap", "agent": agent})
        return self.engine.request_snapshot(agent)

    def clock(self):
        self.arrivals.append({"k": "clk"})
        self.engine.advance_clock()

    def bump_epoch(self):
        self.arrivals.append({"k": "epoch"})
        self.engine.bump_epoch()

    @property
    def epoch(self):
        return self.engine.state["epoch"]


# ---------------------------------------------------------------- 재현 패키지

def make_record(gateway, meta):
    """런 기록: 설정 메타 + 도착 로그 + 최종 상태 해시(무결성 검증용)."""
    return {"meta": meta, "arrivals": gateway.arrivals,
            "final_hash": state_hash(gateway.engine.state)}


def record_to_json(record):
    return json.dumps(record, sort_keys=True)


def record_from_json(text):
    return json.loads(text)


def replay_record(record, engine_factory):
    """도착 로그만으로 런을 재구동한다. 에이전트·스케줄러를 전혀 거치지 않는다.

    engine_factory: meta -> MarketEngine (메커니즘·정보정책·시드를 meta에서 복원)
    """
    engine = engine_factory(record["meta"])
    gw = Gateway(engine)
    for e in record["arrivals"]:
        k = e["k"]
        if k == "acct":
            gw.create_account(e["agent"], e["cash"], e["shares"])
        elif k == "sub":
            gw.submit(e["oid"], e["agent"], e["side"], e["price"], e["qty"], e["epoch"])
        elif k == "can":
            gw.cancel(e["oid"], e["epoch"])
        elif k == "rep":
            gw.cancel_replace(e["old"], e["oid"], e["agent"], e["side"],
                              e["price"], e["qty"], e["epoch"])
        elif k == "abs":
            gw.abstain(e["agent"], e["reason"])
        elif k == "snap":
            gw.snapshot(e["agent"])
        elif k == "clk":
            gw.clock()
        elif k == "epoch":
            gw.bump_epoch()
        else:
            raise ValueError("unknown arrival kind: " + k)
    return engine

"""연속 복식 호가(CDA): 도착 즉시 매칭. 순차 정보 모형의 구현체 (설계안 §3).

가격 규칙: 교차 시 '먼저 쉬고 있던'(seq 낮은) 주문의 지정가로 체결.
우선순위: 가격-시간.
"""


class CDA:
    name = "cda"

    def on_order_accepted(self, engine, oid):
        s = engine.state
        while s["bids"] and s["asks"]:
            b = s["orders"][s["bids"][0]]
            k = s["orders"][s["asks"][0]]
            if b["price"] < k["price"]:
                break
            resting = b if b["seq"] < k["seq"] else k
            engine._emit({"type": "trade",
                          "buy_oid": s["bids"][0], "sell_oid": s["asks"][0],
                          "price": resting["price"],
                          "qty": min(b["remaining"], k["remaining"])})

    def on_clock(self, engine):
        pass

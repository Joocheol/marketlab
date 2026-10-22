"""간단한 규칙 기반 에이전트 — 이질적 개체군을 같은 하네스에 섞기 위한 예시.

SpreadImprover: 최우선 호가 스프레드가 넓으면 그 안쪽에 양방향 호가를 내는
단순 유동성 공급 규칙. 스프레드가 좁거나 호가가 없으면 기권(None) —
기권 경로의 테스트 겸용.
"""

from .base import AgentBase


class SpreadImprover(AgentBase):
    def __init__(self, agent_id, cash, shares, min_spread=4, improve=1):
        super().__init__(agent_id)
        self._cash, self._shares = cash, shares
        self.min_spread = min_spread
        self.improve = improve

    def endowment(self):
        return (self._cash, self._shares)

    def decide(self, snapshot, ctx):
        me = snapshot["me"]
        bb = snapshot.get("best_bid")
        ba = snapshot.get("best_ask")
        if bb is None and snapshot.get("bids"):
            bb = snapshot["bids"][0][0]
        if ba is None and snapshot.get("asks"):
            ba = snapshot["asks"][0][0]
        cancels = list(me["open_orders"].keys())
        if bb is None or ba is None or ba - bb < self.min_spread:
            return None                                  # 기권
        orders = []
        if me["cash"] >= bb + self.improve:
            orders.append({"side": "buy", "price": bb + self.improve, "qty": 1})
        if me["shares"] >= 1:
            orders.append({"side": "sell", "price": ba - self.improve, "qty": 1})
        return {"cancels": cancels, "orders": orders}

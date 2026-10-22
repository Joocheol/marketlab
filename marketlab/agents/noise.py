"""비소진 ZI 노이즈 트레이더 — 스타일라이즈드 팩트 측정용.

Gode-Sunder 단일 유닛 ZI는 유보가치가 소진되면 시장이 멈추므로 긴 가격
경로가 나오지 않는다. 이 트레이더는 유보가치 없이 '기준가(직전 체결가)
주변 균등분포' 호가를 계속 낸다 — 예산 제약(현금·주식 한도)만 지키는
순수 잡음 주문 흐름. 가격 동학은 전적으로 메커니즘·정보 구조가 만든다.

ZITrader와 같은 규율을 따른다: 미체결 주문이 있으면 취소만 하고
재호가하지 않는다 (이중 노출 방지).
"""

import random

from .base import AgentBase


class NoiseTrader(AgentBase):
    def __init__(self, agent_id, cash, shares, band=10, seed=0):
        super().__init__(agent_id)
        self._cash, self._shares = cash, shares
        self.band = band
        self.rng = random.Random(seed)

    def endowment(self):
        return (self._cash, self._shares)

    def decide(self, snapshot, ctx):
        me = snapshot["me"]
        cancels = list(me["open_orders"].keys())
        if cancels:
            return {"cancels": cancels, "orders": []}
        ref = snapshot.get("ref_price") or 100
        price = max(1, ref + self.rng.randint(-self.band, self.band))
        side = "buy" if self.rng.random() < 0.5 else "sell"
        # 예산 제약: 선택한 방향이 불가능하면 반대 방향, 둘 다 불가면 관망
        if side == "buy" and me["cash"] < price:
            side = "sell"
        if side == "sell" and me["shares"] < 1:
            side = "buy"
            if me["cash"] < price:
                return {"cancels": [], "orders": []}
        return {"cancels": [], "orders": [{"side": side, "price": price, "qty": 1}]}

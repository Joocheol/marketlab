"""제로 지능(ZI-C) 트레이더 — Gode & Sunder (1993).

매수자는 유보가치 v를 넘지 않는 균등분포 호가 U[pmin, v]를,
매도자는 비용 c를 밑돌지 않는 U[c, pmax]를 낸다 (예산 제약 = 손해 거래 금지).
지능은 없다: 과거도, 전략도, 학습도 없다. 시장 메커니즘의 효과를 재는 기준선.

단위 가치 목록을 받아 유닛을 차례로 거래한다. 이미 거래한 유닛 수는
스냅샷의 자기 계좌에서 복원한다(매수자: 보유 주식 증가분, 매도자: 주식 감소분).
매 라운드 자기 미체결 주문을 전부 취소하고 새 호가를 낸다 (표준 GS 재현 방식).
"""

import random

from .base import AgentBase


class ZITrader(AgentBase):
    def __init__(self, agent_id, role, unit_values, pmin, pmax, seed, cash=None):
        super().__init__(agent_id)
        assert role in ("buyer", "seller")
        self.role = role
        # 매수자: 가치 내림차순(높은 가치 유닛부터), 매도자: 비용 오름차순
        self.unit_values = sorted(unit_values, reverse=(role == "buyer"))
        self.pmin, self.pmax = pmin, pmax
        self.rng = random.Random(seed)
        self._cash = cash if cash is not None else pmax * len(unit_values)

    def endowment(self):
        if self.role == "buyer":
            return (self._cash, 0)
        return (0, len(self.unit_values))

    def _units_traded(self, me):
        if self.role == "buyer":
            return me["shares"]                       # 시작 0 -> 산 만큼
        return len(self.unit_values) - me["shares"] - me["res_shares"]

    def decide(self, snapshot, ctx):
        me = snapshot["me"]
        cancels = list(me["open_orders"].keys())
        k = self._units_traded(me)
        if k >= len(self.unit_values):
            return {"cancels": cancels, "orders": []}   # 다 거래함: 정리만
        if cancels:
            # 미체결 주문이 있으면 이번 라운드는 취소만 하고 재호가하지 않는다.
            # 같은 라운드에 '취소+새 호가'를 함께 내면, 낡은 스냅샷 때문에
            # 옛 주문이 반입 중 먼저 체결되고 새 호가까지 체결되는 이중 노출
            # (가치 없는 추가 유닛 거래 = ZI-C 예산 제약 위반)이 생길 수 있다.
            return {"cancels": cancels, "orders": []}
        v = self.unit_values[k]
        if self.role == "buyer":
            price = self.rng.randint(self.pmin, v)
            side = "buy"
        else:
            price = self.rng.randint(v, self.pmax)
            side = "sell"
        return {"cancels": cancels, "orders": [{"side": side, "price": price, "qty": 1}]}

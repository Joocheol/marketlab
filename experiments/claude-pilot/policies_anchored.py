"""앵커 변형: "알 수 없는 시점에 주당 100으로 청산(공통 지식)" 고지에 대한
클론 5개의 수정 지시(전원 AMEND, 2026-10-23)를 이식한 정책들.

핵심 변화: 모멘텀·공격이 추세 추종을 '매수 ≤99 / 매도 ≥101' 차익거래 규율로
구속했고, 가치는 경계를 98/102로 좁혔으며(청산 불확실성 보상 1~2 마진 유지),
MM은 호가 중심을 100 쪽으로 견인(0.6·ref+0.4·100)+유리한 방향만 테이킹,
보수는 ref를 상수 100으로 고정했다. 수정 전문: state/policy-specs-anchored.md
"""

import random
import statistics

from policies import (PolicyAgent, MomentumPolicy, ValuePolicy, MMPolicy,
                      ConservativePolicy, AggressivePolicy, clamp)

V = 100


class MomentumAnchored(MomentumPolicy):
    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        last = snap["ref_price"]
        recent = ctx["recent"]
        ref = last if last is not None else V
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        ba, bb = snap["best_ask"], snap["best_bid"]

        def buy(px):
            """AMEND1: 매수는 99 이하에서만, (100-가격)이 클수록 수량 확대."""
            if px > 99:
                return None
            qty = min(5, 1 + (V - px) // 2, 50 - shares, (cash - 300) // px)
            if qty >= 1:
                return [{"side": "buy", "price": clamp(px), "qty": int(qty)}]
            return None

        # AMEND2: last 또는 best_bid가 101 이상이면 추세 무관 확정 차익 매도
        if ((last is not None and last >= 101) or (bb is not None and bb >= 101)) \
                and shares >= 1:
            px = max(bb if bb is not None else 0, 101)
            return [{"side": "sell", "price": clamp(px), "qty": int(min(5, shares))}]

        if last is None:
            if ba is not None and ba <= 99 and rng.uniform(0, 1) < 0.4:
                r = buy(ba)
                if r:
                    return r
            if rng.uniform(0, 1) < 0.7:
                return buy(min(99, ref + rng.randint(-1, 0)))
            return None
        if rng.uniform(0, 1) < 0.15:
            return None
        if trend > 0:
            px = ba if (ba is not None and ba - last <= 3) else last + rng.randint(1, 2)
            return buy(px)                      # px>99면 추격 매수 금지 (AMEND1)
        if trend < 0:
            px = bb if (bb is not None and last - bb <= 3) else clamp(last - rng.randint(1, 2))
            qty = min(5, shares)
            if qty >= 1:
                return [{"side": "sell", "price": clamp(px), "qty": int(qty)}]
            return None
        # AMEND3: 횡보 수취도 가격 ≤100일 때만
        if (rng.uniform(0, 1) < 0.1 and ba is not None and ba <= min(last + 2, V)
                and cash - ba >= 300 and shares + 1 <= 50):
            return [{"side": "buy", "price": clamp(ba), "qty": 1}]
        return None


class ValueAnchored(ValuePolicy):
    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        bb, ba = snap["best_bid"], snap["best_ask"]
        qty = rng.randint(1, 3)
        can_buy = shares + qty <= 40 and cash >= 98 * qty
        can_sell = shares - qty >= 0
        # AMEND1: 경계 98/102 (청산가 보장으로 무위험 차익 구간 확대)
        if bb is not None and bb >= 102 and can_sell:
            return [{"side": "sell", "price": clamp(bb), "qty": qty}]
        if ba is not None and ba <= 98 and can_buy:
            return [{"side": "buy", "price": clamp(ba), "qty": qty}]
        # AMEND2: 대기주문 101+j 매도 / 99-j 매수 (마진 1~2 유지)
        if rng.uniform(0, 1) < 0.5:
            if can_sell and (bb is None or bb > V):
                return [{"side": "sell", "price": clamp(101 + rng.randint(0, 2)), "qty": qty}]
            if can_buy and (bb is None or bb <= V):
                return [{"side": "buy", "price": clamp(99 - rng.randint(0, 2)), "qty": qty}]
        return None


class MMAnchored(MMPolicy):
    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        bb, ba = snap["best_bid"], snap["best_ask"]
        last = snap["ref_price"]
        # AMEND2: 테이킹은 유리한 방향만 (ask<100 매수 / bid>100 매도)
        if not self.just_took:
            if (rng.uniform(0, 1) < 0.15 and bb is not None and ba is not None
                    and ba - bb <= 4 and 20 <= shares <= 40):
                if ba < V and cash >= ba:
                    self.just_took = True
                    return [{"side": "buy", "price": clamp(ba), "qty": 1}]
                if bb > V and shares >= 1:
                    self.just_took = True
                    return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        self.just_took = False
        if last is not None:
            ref0 = last
        elif bb is not None and ba is not None:
            ref0 = (bb + ba) / 2
        else:
            ref0 = V
        if len(recent) >= 3:
            drift = max(-2, min(2, statistics.mean(recent[-3:]) - ref0))
        else:
            drift = 0
        ref0 = ref0 + 0.5 * drift
        ref = round(0.6 * ref0 + 0.4 * V)        # AMEND1: 청산가로 호가 중심 견인
        half = rng.choice([1, 2, 3])
        skew = round((shares - 30) / 10)
        bid = clamp(ref - half - skew)
        ask = clamp(ref + half - skew)
        if ba is not None and bid >= ba:
            bid = clamp(ba - 1)
        if bb is not None and ask <= bb:
            ask = clamp(bb + 1)
        if ask <= bid:
            ask = clamp(bid + 1)
        # AMEND3: 괴리 방향으로 수량 비대칭
        if last is not None and last > V:
            q_buy, q_sell = 1, 2
        elif last is not None and last < V:
            q_buy, q_sell = 2, 1
        else:
            q_buy, q_sell = 2, 2
        if shares > 45:
            orders = [{"side": "sell", "price": ask, "qty": q_sell}]
        elif shares < 15:
            orders = [{"side": "buy", "price": bid, "qty": q_buy}] if cash >= bid * q_buy else []
        else:
            orders = []
            if cash >= bid * q_buy:
                orders.append({"side": "buy", "price": bid, "qty": q_buy})
            if shares >= q_sell:
                orders.append({"side": "sell", "price": ask, "qty": q_sell})
        return orders or None


class ConservativeAnchored(ConservativePolicy):
    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        bb, ba = snap["best_bid"], snap["best_ask"]
        u = rng.uniform(0, 1)
        if snap["me"]["open_orders"]:
            return None                           # AMEND3: 기존 주문은 항상 유지
        can_sell = shares >= 1
        # AMEND1·2: ref=상수 100, 경계 ±10%
        if can_sell and bb is not None and bb >= 110 and u < 0.8:
            return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        if ba is not None and ba <= 90 and cash - ba >= 1800 and u < 0.8:
            return [{"side": "buy", "price": clamp(ba), "qty": 1}]
        if u < 0.3:
            if u < 0.15 and cash - 88 >= 1800:
                return [{"side": "buy", "price": 88, "qty": 1}]
            if can_sell:
                return [{"side": "sell", "price": 112, "qty": 1}]
        return None


class AggressiveAnchored(AggressivePolicy):
    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        last = snap["ref_price"]
        ref = last if last is not None else V
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        if rng.uniform(0, 1) < 0.15:
            return None
        bb, ba = snap["best_bid"], snap["best_ask"]
        # AMEND1 전역 제약: 매수 ≤99 / 매도 ≥101 (위반 분기는 건너뜀)
        if ba is None and bb is None:
            px = min(99, clamp(ref - rng.randint(3, 6)))
            qty = min(8, cash // px)
            return [{"side": "buy", "price": px, "qty": int(qty)}] if qty >= 1 else None
        if ba is None and shares > 0:
            px = max(101, clamp(ref + rng.randint(5, 9)))
            return [{"side": "sell", "price": px, "qty": int(min(8, shares))}]
        # AMEND2: 걷기는 best_ask ≤ 99일 때만
        if ((trend > 0 or last is None) and ba is not None and ba <= 99
                and cash // ba >= 1 and rng.uniform(0, 1) < 0.6):
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if trend > 0 and ba is not None and ba <= 99 and cash // ba >= 1:
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if (trend >= 0 and shares >= 8 and ba is not None and ba - (bb or 0) >= 3
                and ba - 1 >= 101):
            return [{"side": "sell", "price": clamp(ba - 1), "qty": 8}]
        if trend < 0 and bb is not None and bb >= 101 and shares > 0:
            return [{"side": "sell", "price": clamp(bb), "qty": int(min(8, shares))}]
        # AMEND3 기본 행동: 100 하단 매집 + (50%) 100 상단 공급 상시 유지
        orders = []
        px_b = min(99, clamp((bb if bb is not None else ref) - rng.randint(0, 2)))
        if cash // px_b >= 1:
            orders.append({"side": "buy", "price": px_b, "qty": int(min(8, cash // px_b))})
        if shares > 0 and not snap["me"]["open_orders"] and rng.uniform(0, 1) < 0.5:
            px_s = max(101, clamp((ba - 1) if ba is not None else ref + rng.randint(2, 5)))
            orders.append({"side": "sell", "price": px_s, "qty": int(min(8, shares))})
        return orders or None


PERSONAS = {
    "momentum": (MomentumAnchored, 2500, 20),
    "value": (ValueAnchored, 2500, 20),
    "mm": (MMAnchored, 2500, 30),
    "conservative": (ConservativeAnchored, 2500, 20),
    "aggressive": (AggressiveAnchored, 2500, 20),
}

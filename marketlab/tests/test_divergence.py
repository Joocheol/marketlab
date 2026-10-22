"""M1 완료 기준 (설계안 §9): 같은 주문 흐름이 메커니즘에 따라
다른 가격 경로를 만들되, 둘 다 재생 가능하고 회계가 깨끗해야 한다."""

import random
import unittest

from marketlab.core.engine import MarketEngine
from marketlab.core.state import replay, state_hash
from marketlab.core.invariants import check_invariants
from marketlab.disclosure.policies import FullBook
from marketlab.mechanisms.cda import CDA
from marketlab.mechanisms.call_auction import CallAuction

AGENTS = ["A", "B", "C", "D"]
TOTALS = (400_000, 400)


def order_stream(n=600, seed=123):
    rng = random.Random(seed)
    for i in range(n):
        yield (f"o{i}", rng.choice(AGENTS), rng.choice(["buy", "sell"]),
               rng.randint(95, 105) * 100, rng.randint(1, 5))


def run(mechanism, is_auction):
    eng = MarketEngine(mechanism, FullBook(), seed=7)
    for ag in AGENTS:
        eng.create_account(ag, 100_000, 100)
    for i, (oid, agent, side, price, qty) in enumerate(order_stream()):
        eng.submit(oid, agent, side, price, qty, 0)
        if i % 25 == 24:
            eng.advance_clock()
    eng.advance_clock()
    return eng


class DivergenceTest(unittest.TestCase):

    def test_same_flow_different_mechanism(self):
        cda = run(CDA(), is_auction=False)
        auc = run(CallAuction(), is_auction=True)

        cda_prices = [ev["price"] for ev in cda.log if ev["type"] == "trade"]
        auc_prices = [ev["price"] for ev in auc.log if ev["type"] == "trade"]
        self.assertGreater(len(cda_prices), 0)
        self.assertGreater(len(auc_prices), 0)
        # 같은 주문 흐름, 다른 메커니즘 -> 다른 가격 경로와 다른 최종 상태
        self.assertNotEqual(cda_prices, auc_prices)
        self.assertNotEqual(state_hash(cda.state), state_hash(auc.state))
        # 둘 다: 회계 깨끗 + 로그만으로 재생 일치
        for eng in (cda, auc):
            self.assertEqual(check_invariants(eng.state, TOTALS), [])
            self.assertEqual(state_hash(replay(eng.log)), state_hash(eng.state))

    def test_auction_price_path_is_steppy(self):
        """경매는 라운드당 단일 가격: 체결가 종류 수 <= 클리어링 횟수."""
        auc = run(CallAuction(), is_auction=True)
        n_clearings = sum(1 for ev in auc.log
                          if ev["type"] == "auction_cleared" and ev["volume"] > 0)
        price_changes = len({ev["price"] for ev in auc.log if ev["type"] == "trade"})
        self.assertLessEqual(price_changes, n_clearings)


if __name__ == "__main__":
    unittest.main()

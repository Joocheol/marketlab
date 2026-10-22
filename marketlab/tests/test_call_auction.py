"""일괄 경매 단위 검증 (설계안 §8-4):
손계산 사례 + 독립 구현 brute-force와의 대조 + 실행 가능성 속성."""

import random
import unittest

from marketlab.core.engine import MarketEngine
from marketlab.disclosure.policies import FullBook
from marketlab.mechanisms.call_auction import CallAuction


def fresh(seed=0):
    eng = MarketEngine(CallAuction(), FullBook(), seed=seed)
    for ag in ("A", "B", "C", "D"):
        eng.create_account(ag, 10_000_000, 10_000)
    return eng


def brute_force_max_volume(orders):
    """독립 구현: 전 정수 가격을 전수 탐색해 최대 체결량을 구한다."""
    prices = [o[2] for o in orders]
    best_v = 0
    for p in range(min(prices), max(prices) + 1):
        d = sum(q for side, _, pr, q in orders if side == "buy" and pr >= p)
        s = sum(q for side, _, pr, q in orders if side == "sell" and pr <= p)
        best_v = max(best_v, min(d, s))
    return best_v


class HandCases(unittest.TestCase):

    def _clear(self, orders, seed=0):
        eng = fresh(seed)
        for side, agent, price, qty in orders:
            eng.submit(f"o{len(eng.log)}", agent, side, price, qty, 0)
        eng.advance_clock()
        cleared = [ev for ev in eng.log if ev["type"] == "auction_cleared"][-1]
        trades = [ev for ev in eng.log if ev["type"] == "trade"]
        return eng, cleared, trades

    def test_tie_no_ref_lower_median(self):
        _, cleared, _ = self._clear([("buy", "A", 102, 5), ("sell", "B", 98, 3)])
        self.assertEqual(cleared["volume"], 3)
        self.assertEqual(cleared["price"], 98)   # V·불균형 동률 → 하위 중앙값

    def test_unique_max_volume(self):
        _, cleared, _ = self._clear([
            ("buy", "A", 101, 10),
            ("sell", "B", 99, 4), ("sell", "C", 100, 4), ("sell", "D", 101, 4)])
        self.assertEqual((cleared["price"], cleared["volume"]), (101, 10))

    def test_rationing_partial_fill(self):
        eng, cleared, trades = self._clear([
            ("buy", "A", 100, 3), ("buy", "B", 100, 3), ("sell", "C", 100, 4)])
        self.assertEqual(cleared["volume"], 4)
        self.assertEqual(sum(t["qty"] for t in trades), 4)
        remaining = sorted(o["remaining"] for o in eng.state["orders"].values()
                           if o["side"] == "buy")
        self.assertEqual(remaining, [0, 2])      # 한쪽 전량, 한쪽 부분(셔플이 선택)

    def test_ref_price_tiebreak(self):
        eng = fresh()
        # 1라운드: 기준가 100 형성
        eng.submit("r1", "A", "buy", 100, 2, 0)
        eng.submit("r2", "B", "sell", 100, 2, 0)
        eng.advance_clock()
        self.assertEqual(eng.state["ref_price"], 100)
        # 2라운드: 98~102 전부 동률이면 기준가(100)에 가장 가까운 후보 선택
        eng.submit("r3", "C", "buy", 102, 3, 0)
        eng.submit("r4", "D", "sell", 98, 3, 0)
        eng.advance_clock()
        cleared = [ev for ev in eng.log if ev["type"] == "auction_cleared"][-1]
        self.assertEqual(cleared["price"], 100)

    def test_empty_and_uncrossed_rounds(self):
        eng = fresh()
        eng.advance_clock()                       # 빈 장
        eng.submit("b", "A", "buy", 90, 1, 0)
        eng.submit("s", "B", "sell", 110, 1, 0)   # 교차 없음
        eng.advance_clock()
        vols = [ev["volume"] for ev in eng.log if ev["type"] == "auction_cleared"]
        self.assertEqual(vols, [0, 0])


class RandomizedAgainstBruteForce(unittest.TestCase):

    def test_volume_matches_and_feasible(self):
        for case in range(300):
            rng = random.Random(9_000 + case)
            orders = [(rng.choice(["buy", "sell"]), rng.choice("ABCD"),
                       rng.randint(95, 105), rng.randint(1, 8))
                      for _ in range(rng.randint(2, 12))]
            eng = fresh(seed=case)
            for i, (side, agent, price, qty) in enumerate(orders):
                eng.submit(f"o{i}", agent, side, price, qty, 0)
            eng.advance_clock()
            cleared = [ev for ev in eng.log if ev["type"] == "auction_cleared"][-1]
            trades = [ev for ev in eng.log if ev["type"] == "trade"]

            self.assertEqual(cleared["volume"], brute_force_max_volume(orders),
                             f"case {case}: not volume-maximizing")
            self.assertEqual(sum(t["qty"] for t in trades), cleared["volume"])
            p = cleared["price"]
            for t in trades:
                self.assertEqual(t["price"], p)
                self.assertGreaterEqual(eng.state["orders"][t["buy_oid"]]["price"], p)
                self.assertLessEqual(eng.state["orders"][t["sell_oid"]]["price"], p)
            # 클리어링 직후 호가장은 비교차 (한계 가격 잔량은 한쪽에만 남는다)
            if eng.state["bids"] and eng.state["asks"]:
                self.assertLess(
                    eng.state["orders"][eng.state["bids"][0]]["price"],
                    eng.state["orders"][eng.state["asks"][0]]["price"],
                    f"case {case}: crossed book after clearing")


if __name__ == "__main__":
    unittest.main()

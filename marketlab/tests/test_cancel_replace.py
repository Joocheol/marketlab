"""원자적 cancel-replace의 의미론과 이중 노출 방어 검사 (M2 발견의 해법)."""

import unittest

from marketlab.core.engine import MarketEngine
from marketlab.core.invariants import check_invariants
from marketlab.core.state import replay, state_hash
from marketlab.disclosure.policies import BestQuoteOnly
from marketlab.gateway.ingress import Gateway
from marketlab.mechanisms.cda import CDA


def fresh():
    eng = MarketEngine(CDA(), BestQuoteOnly(), seed=0)
    eng.create_account("A", 1000, 10)
    eng.create_account("B", 1000, 10)
    return eng


class CancelReplaceTest(unittest.TestCase):

    def test_open_order_is_replaced(self):
        eng = fresh()
        eng.submit("o1", "A", "buy", 100, 2, 0)
        eng.cancel_replace("o1", "o2", "A", "buy", 105, 2, 0)
        self.assertEqual(eng.state["orders"]["o1"]["status"], "cancelled")
        self.assertEqual(eng.state["orders"]["o2"]["status"], "open")
        self.assertEqual(check_invariants(eng.state, (2000, 20)), [])
        self.assertEqual(state_hash(replay(eng.log)), state_hash(eng.state))

    def test_filled_target_blocks_new_exposure(self):
        """M2의 이중 노출 레이스 시나리오: 옛 주문이 교체 '직전에' 체결된 경우,
        단순 취소+재제출은 두 번째 노출을 만들지만 cancel-replace는 막는다."""
        # 단순 취소+재제출 (위험한 패턴)
        eng = fresh()
        eng.submit("o1", "A", "buy", 100, 1, 0)
        eng.submit("s1", "B", "sell", 95, 1, 0)      # o1 체결 (A가 1주 매수)
        eng.cancel("o1", 0)                           # unknown_cancel 거부
        eng.submit("o2", "A", "buy", 100, 1, 0)      # 그래도 수리됨 = 이중 노출
        self.assertEqual(eng.state["orders"]["o2"]["status"], "open")

        # 원자적 cancel-replace (안전한 패턴)
        eng2 = fresh()
        eng2.submit("o1", "A", "buy", 100, 1, 0)
        eng2.submit("s1", "B", "sell", 95, 1, 0)     # o1 체결
        eng2.cancel_replace("o1", "o2", "A", "buy", 100, 1, 0)
        self.assertEqual(eng2.state["rejections"]["replace_target_gone"], 1)
        self.assertNotIn("o2", eng2.state["orders"])  # 새 노출 없음
        self.assertEqual(check_invariants(eng2.state, (2000, 20)), [])

    def test_cannot_replace_someone_elses_order(self):
        eng = fresh()
        eng.submit("o1", "A", "buy", 100, 1, 0)
        eng.cancel_replace("o1", "x1", "B", "buy", 101, 1, 0)
        self.assertEqual(eng.state["rejections"]["replace_target_gone"], 1)
        self.assertEqual(eng.state["orders"]["o1"]["status"], "open")

    def test_stale_epoch_replace_rejected(self):
        eng = fresh()
        eng.submit("o1", "A", "buy", 100, 1, 0)
        eng.bump_epoch()
        eng.cancel_replace("o1", "o2", "A", "buy", 101, 1, 0)
        self.assertEqual(eng.state["rejections"]["stale_epoch"], 1)
        self.assertEqual(eng.state["orders"]["o1"]["status"], "open")

    def test_gateway_records_and_replays_replace(self):
        from marketlab.gateway.ingress import make_record, replay_record
        eng = fresh()
        gw = Gateway(eng)
        gw.create_account("C", 500, 5)
        gw.submit("o1", "C", "buy", 100, 1, 0)
        gw.cancel_replace("o1", "o2", "C", "buy", 102, 1, 0)
        meta = {"factors": {"mechanism": "cda", "population": [],
                            "clock": {"mode": "sync", "rounds": 0}},
                "seed": 0}
        rec = make_record(gw, meta)
        from marketlab.lab.experiment import engine_factory
        # 주의: gw는 fresh()가 만든 계좌 A·B 생성 '이전'이 아니라 이후에 붙었으므로
        # 도착 로그에는 C만 있다. 재생 비교는 도착 로그가 전체 구동 기록일 때만
        # 성립한다 — 여기서는 '교체 항목이 재생 가능한가'만 확인한다.
        replayed = replay_record(rec, engine_factory)
        self.assertEqual(replayed.state["orders"]["o2"]["status"], "open")


if __name__ == "__main__":
    unittest.main()

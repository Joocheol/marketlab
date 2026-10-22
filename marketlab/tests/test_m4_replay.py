"""M4 통합 검사: 비결정적 모의 LLM 시장의 기록·재생 결정론.

판별 기준 (13.2의 실제 어댑터 계층 버전):
  - 라이브(모의 LLM) 런의 호출 로그로 ReplayAdapter 재실행 → 최종 해시 일치 (2회)
  - 라이브를 다시 돌리면 해시 불일치 (비결정성 실재)
  - 도착 로그 재생(replay_record)도 일치
  - 예산 소진 시 정상 종료 + 부분 도착 로그 재생 가능
  - δ 재배정 반사실: 같은 판단, 다른 지연 가정 → 다른 결과, 회계는 깨끗
"""

import unittest

from marketlab.agents.llm_agent import LLMAgent
from marketlab.clock.async_rounds import AsyncRounds
from marketlab.core.engine import MarketEngine
from marketlab.core.invariants import check_invariants
from marketlab.core.state import state_hash
from marketlab.disclosure.policies import BestQuoteOnly
from marketlab.gateway.ingress import Gateway, make_record, replay_record
from marketlab.lab.counterfactual import redelay
from marketlab.llm.adapter import BudgetGuard, CallLog, LiveAdapter, ReplayAdapter
from marketlab.llm.mock import MockTransport
from marketlab.mechanisms.cda import CDA

SEED = 42
ROUNDS = 12
PERSONAS = {
    "L0": "너는 공격적인 모멘텀 투자자다.",
    "L1": "너는 보수적인 가치 투자자다.",
    "L2": "너는 유동성을 공급하는 마켓메이커다.",
    "L3": "너는 소액 개인 투자자다.",
}


def agents():
    return [LLMAgent(aid, persona, cash=2000, shares=20)
            for aid, persona in sorted(PERSONAS.items())]


def meta():
    return {"factors": {"mechanism": "cda", "info_policy": "best_quote_only",
                        "population": "llm-mock", "clock": {"mode": "async_sync"}},
            "seed": SEED}


def engine_factory(m):
    return MarketEngine(CDA(), BestQuoteOnly(), seed=m["seed"])


def run_market(adapter, rounds=ROUNDS):
    eng = engine_factory(meta())
    gw = Gateway(eng)
    runner = AsyncRounds(gw, agents(), adapter, master_seed=SEED)
    runner.setup()
    runner.run(rounds)
    return eng, gw, runner


class M4ReplayTest(unittest.TestCase):

    def test_record_replay_determinism(self):
        log = CallLog()
        live_adapter = LiveAdapter(
            MockTransport(junk_rate=0.15, slow_rate=0.1, slow_latency=0.5),
            log, BudgetGuard(), "mock-model", timeout=0.05)
        eng1, gw1, run1 = run_market(live_adapter)
        h1 = state_hash(eng1.state)

        # 시장이 실제로 돌아갔고, 기권(타임아웃/파싱 실패)도 발생했는가
        self.assertGreater(len(run1.decision_log), 0)
        self.assertGreater(eng1.state["abstained"], 0)

        # 호출 로그 직렬화 왕복 후 재생 2회: 비트 단위 일치
        restored = CallLog.from_json(log.to_json())
        for _ in range(2):
            eng_r, _, _ = run_market(ReplayAdapter(restored))
            self.assertEqual(state_hash(eng_r.state), h1)

        # 도착 로그 재생도 일치
        record = make_record(gw1, meta())
        self.assertEqual(
            state_hash(replay_record(record, engine_factory).state), h1)

        # 라이브 재실행은 (기록 없이는) 재현 불가 — 비결정성의 실재
        log2 = CallLog()
        live2 = LiveAdapter(
            MockTransport(junk_rate=0.15, slow_rate=0.1, slow_latency=0.5),
            log2, BudgetGuard(), "mock-model", timeout=0.05)
        eng2, _, _ = run_market(live2)
        self.assertNotEqual(state_hash(eng2.state), h1)

        # 회계는 어느 실행에서나 깨끗하다
        totals = (2000 * 4, 20 * 4)
        for eng in (eng1, eng2):
            self.assertEqual(check_invariants(eng.state, totals), [])

    def test_budget_exhaustion_is_graceful_and_replayable(self):
        log = CallLog()
        adapter = LiveAdapter(MockTransport(slow_rate=0.0), log,
                              BudgetGuard(max_calls=10), "mock-model",
                              timeout=0.5)
        eng, gw, runner = run_market(adapter, rounds=ROUNDS)
        self.assertTrue(runner.budget_exhausted)
        self.assertLessEqual(len(log), 10)
        # 부분 런도 도착 로그만으로 재생된다
        record = make_record(gw, meta())
        self.assertEqual(
            state_hash(replay_record(record, engine_factory).state),
            state_hash(eng.state))

    def test_redelay_counterfactual(self):
        log = CallLog()
        adapter = LiveAdapter(MockTransport(junk_rate=0.0, slow_rate=0.0),
                              log, BudgetGuard(), "mock-model", timeout=0.5)
        eng, gw, runner = run_market(adapter)
        record = make_record(gw, meta())

        def instant(aid, rng):
            return 0.0

        def l0_slow(aid, rng):
            return 3.0 if aid == "L0" else 0.0

        cf_a = redelay(record, runner.decision_log, instant, engine_factory)
        cf_b = redelay(record, runner.decision_log, l0_slow, engine_factory)
        # 같은 판단, 다른 지연 가정 -> 다른 시장 결과
        self.assertNotEqual(state_hash(cf_a.state), state_hash(cf_b.state))
        totals = (2000 * 4, 20 * 4)
        for cf in (cf_a, cf_b):
            self.assertEqual(check_invariants(cf.state, totals), [])


if __name__ == "__main__":
    unittest.main()

"""M2: 재현 패키지 왕복과 지연 주입 모드 검사.

- 이질적 개체군(ZI + 규칙 기반)의 동기 라운드 런을 기록 → JSON 직렬화 왕복 →
  도착 로그만으로 재생했을 때 최종 해시가 일치해야 한다.
- 지연 주입 모드: 같은 시드·같은 에이전트로 지연 가정만 바꾸면 결과가 달라지고
  (속도가 결과에 개입), 각 런은 자기 기록으로 재생 가능해야 한다.
- 기권(abstain)은 이벤트로 남는다.
"""

import json
import random
import unittest

from marketlab.agents.rule import SpreadImprover
from marketlab.agents.zi import ZITrader
from marketlab.clock.latency import LatencyRounds
from marketlab.clock.sync_rounds import SyncRounds
from marketlab.core.engine import MarketEngine
from marketlab.core.state import state_hash
from marketlab.disclosure.policies import BestQuoteOnly
from marketlab.gateway.ingress import Gateway
from marketlab.mechanisms.cda import CDA
from marketlab.mechanisms.call_auction import CallAuction


def engine_factory(meta):
    mech = CallAuction() if meta["mechanism"] == "call_auction" else CDA()
    return MarketEngine(mech, BestQuoteOnly(), seed=meta["seed"])


def mixed_agents(seed):
    agents = []
    for i in range(4):
        role = "buyer" if i % 2 == 0 else "seller"
        agents.append(ZITrader(f"Z{i}", role, [120, 110, 100, 90], 1, 200,
                               seed * 100 + i, cash=600))
    agents.append(SpreadImprover("R0", cash=500, shares=5))
    agents.append(SpreadImprover("R1", cash=500, shares=5))
    return agents


def run_sync(meta, rounds=30):
    eng = engine_factory(meta)
    gw = Gateway(eng)
    runner = SyncRounds(gw, mixed_agents(meta["seed"]), master_seed=meta["seed"])
    runner.setup()
    runner.run(rounds)
    return eng, gw


class RoundtripTest(unittest.TestCase):

    def _roundtrip(self, mechanism):
        from marketlab.gateway.ingress import (make_record, record_to_json,
                                               record_from_json, replay_record)
        meta = {"mechanism": mechanism, "seed": 11}
        eng, gw = run_sync(meta)
        record = record_from_json(record_to_json(make_record(gw, meta)))
        replayed = replay_record(record, engine_factory)
        self.assertEqual(state_hash(replayed.state), record["final_hash"])
        self.assertEqual(state_hash(replayed.state), state_hash(eng.state))
        # 변조 탐지: 제출 하나를 제거하면 해시가 달라져야 한다
        tampered = dict(record)
        subs = [i for i, e in enumerate(record["arrivals"]) if e["k"] == "sub"]
        tampered["arrivals"] = (record["arrivals"][:subs[len(subs) // 2]]
                                + record["arrivals"][subs[len(subs) // 2] + 1:])
        t_eng = replay_record(tampered, engine_factory)
        self.assertNotEqual(state_hash(t_eng.state), record["final_hash"])

    def test_roundtrip_cda(self):
        self._roundtrip("cda")

    def test_roundtrip_call_auction(self):
        self._roundtrip("call_auction")

    def test_abstains_recorded(self):
        eng, gw = run_sync({"mechanism": "cda", "seed": 11})
        self.assertGreater(eng.state["abstained"], 0)   # 규칙 에이전트의 기권


class LatencyModeTest(unittest.TestCase):

    def _run_latency(self, delay_model, seed=5, horizon=25):
        from marketlab.gateway.ingress import make_record, replay_record
        eng = MarketEngine(CDA(), BestQuoteOnly(), seed=seed)
        gw = Gateway(eng)
        runner = LatencyRounds(gw, mixed_agents(seed), delay_model,
                               master_seed=seed)
        runner.setup()
        runner.run(horizon)
        meta = {"mechanism": "cda", "seed": seed}
        return eng, make_record(gw, meta)

    def test_delay_assumption_changes_outcome_and_both_replay(self):
        from marketlab.gateway.ingress import replay_record

        def fast(aid, rng):
            return rng.uniform(0.05, 0.3)

        def z0_is_slow(aid, rng):
            d = rng.uniform(0.05, 0.3)
            return d + 5.0 if aid == "Z0" else d

        eng_a, rec_a = self._run_latency(fast)
        eng_b, rec_b = self._run_latency(z0_is_slow)
        # 지연 가정이 다르면 시장 결과도 다르다 (속도의 경제적 효과)
        self.assertNotEqual(state_hash(eng_a.state), state_hash(eng_b.state))
        # 그러나 각 런은 자기 도착 로그만으로 재생된다
        for eng, rec in ((eng_a, rec_a), (eng_b, rec_b)):
            replayed = replay_record(rec, engine_factory)
            self.assertEqual(state_hash(replayed.state), rec["final_hash"])

    def test_latency_mode_deterministic(self):
        def fast(aid, rng):
            return rng.uniform(0.05, 0.3)
        eng_a, _ = self._run_latency(fast)
        eng_b, _ = self._run_latency(fast)
        self.assertEqual(state_hash(eng_a.state), state_hash(eng_b.state))


if __name__ == "__main__":
    unittest.main()

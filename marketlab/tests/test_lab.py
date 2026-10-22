"""M3 완료 기준: 실험 관리자의 격리·결정론·재현 패키지·반사실 실행기.

- 병렬(3프로세스) 실행과 순차 실행이 런별로 같은 최종 해시를 내야 한다
  (NetLogo 실측 실험 1의 본 엔진 버전).
- 런 간 오염이 구조적으로 불가능해야 한다 (런 = 새 프로세스의 새 엔진) —
  같은 요인의 반복 런들이 서로 다른 시드·다른 해시를 갖는 것으로 확인.
- 디스크의 record.json만으로 런이 재생되어야 한다.
- 에이전트 절제 반사실이 작동해야 한다.
"""

import json
import os
import tempfile
import unittest

from marketlab.core.invariants import check_invariants
from marketlab.core.state import state_hash
from marketlab.gateway.ingress import replay_record
from marketlab.lab.counterfactual import run_counterfactual, without_agent
from marketlab.lab.experiment import (derive_seed, engine_factory, expand_runs,
                                      run_experiment)

CONFIG = {
    "name": "m3test",
    "factors": {
        "mechanism": ["cda", "call_auction"],
        "info_policy": ["best_quote_only"],
        "clock": [{"mode": "sync", "rounds": 25}],
        "population": [[
            {"type": "zi", "role": "buyer", "values": [130, 120, 110],
             "count": 3, "cash": 600},
            {"type": "zi", "role": "seller", "values": [70, 80, 90], "count": 3},
            {"type": "spread", "count": 1, "cash": 500, "shares": 5},
        ]],
    },
    "repetitions": 3,
    "master_seed": 20261022,
}


class LabTest(unittest.TestCase):

    def test_seed_derivation(self):
        a = derive_seed(1, "k", 0)
        self.assertEqual(a, derive_seed(1, "k", 0))      # 결정적
        self.assertNotEqual(a, derive_seed(1, "k", 1))   # 반복번호 분리
        self.assertNotEqual(a, derive_seed(2, "k", 0))   # 마스터 분리

    def test_expand_runs(self):
        runs = expand_runs(CONFIG)
        self.assertEqual(len(runs), 2 * 3)               # 메커니즘 2 × 반복 3
        self.assertEqual(len({r["run_id"] for r in runs}), 6)
        self.assertEqual(len({r["seed"] for r in runs}), 6)

    def test_parallel_equals_serial_and_records_replay(self):
        with tempfile.TemporaryDirectory() as d1, \
             tempfile.TemporaryDirectory() as d2:
            serial = run_experiment(CONFIG, d1, max_workers=1)
            parallel = run_experiment(CONFIG, d2, max_workers=3)
            s = {r["run_id"]: r["final_hash"] for r in serial}
            p = {r["run_id"]: r["final_hash"] for r in parallel}
            self.assertEqual(s, p)                       # 병렬 = 순차 (런별 결정론)
            self.assertEqual(len(set(s.values())), 6)    # 런 간 상태 공유 없음
            # 디스크의 재현 패키지만으로 재생
            rid = serial[0]["run_id"]
            with open(os.path.join(d1, rid, "record.json")) as fp:
                record = json.load(fp)
            replayed = replay_record(record, engine_factory)
            self.assertEqual(state_hash(replayed.state), record["final_hash"])
            # manifest 존재·메트릭 수집 확인
            with open(os.path.join(d1, "manifest.json")) as fp:
                manifest = json.load(fp)
            self.assertEqual(len(manifest["results"]), 6)
            for r in manifest["results"]:
                self.assertGreaterEqual(r["metrics"]["n_trades"], 1)

    def test_ablation_counterfactual(self):
        with tempfile.TemporaryDirectory() as d:
            results = run_experiment(CONFIG, d, max_workers=1)
            rid = results[0]["run_id"]
            with open(os.path.join(d, rid, "record.json")) as fp:
                record = json.load(fp)
            cf = without_agent(record, "s1_0")           # 매도자 하나 절제
            cf_eng = run_counterfactual(cf, engine_factory)
            # 결과가 달라진다 (그 에이전트는 시장에 영향을 주고 있었다)
            self.assertNotEqual(state_hash(cf_eng.state), record["final_hash"])
            # 남은 참여자만으로 회계가 깨끗하다
            totals = (sum(e["cash"] for e in cf["arrivals"] if e["k"] == "acct"),
                      sum(e["shares"] for e in cf["arrivals"] if e["k"] == "acct"))
            self.assertEqual(check_invariants(cf_eng.state, totals), [])
            self.assertNotIn("s1_0", cf_eng.state["accounts"])


if __name__ == "__main__":
    unittest.main()

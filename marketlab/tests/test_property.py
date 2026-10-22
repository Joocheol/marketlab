"""속성 테스트 (설계안 §8-1): 두 메커니즘 모두에서
불변식·멱등성·epoch·재생(전체/접두사)을 무작위 시나리오로 검사한다.
13.2 스파이크 테스트의 정식화."""

import json
import random
import unittest

from marketlab.core.engine import MarketEngine
from marketlab.core.state import replay, state_hash
from marketlab.core.invariants import check_invariants
from marketlab.disclosure.policies import FullBook
from marketlab.mechanisms.cda import CDA
from marketlab.mechanisms.call_auction import CallAuction

AGENTS = ["A", "B", "C", "D"]
INIT_CASH = 100_000
INIT_SHARES = 100
TOTALS = (INIT_CASH * len(AGENTS), INIT_SHARES * len(AGENTS))

N_SCENARIOS = 40
N_COMMANDS = 800
CLOCK_EVERY = 40


def run_scenario(mechanism_factory, scen, is_auction):
    rng = random.Random(77_000 + scen)
    eng = MarketEngine(mechanism_factory(), FullBook(), seed=scen)
    for ag in AGENTS:
        eng.create_account(ag, INIT_CASH, INIT_SHARES)
    used, next_oid = [], 0
    dup_attempts = dup_effects = 0
    checkpoints, violations = [], []

    for i in range(N_COMMANDS):
        r = rng.random()
        epoch = eng.state["epoch"]
        if r < 0.62:
            oid = f"s{scen}-o{next_oid}"; next_oid += 1
            used.append(oid)
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(1, 10), epoch)
        elif r < 0.70 and used:
            oid = rng.choice(used)
            was_known = oid in eng.state["orders"]
            if was_known:
                dup_attempts += 1
                before = json.dumps(
                    (eng.state["accounts"], eng.state["orders"].get(oid)),
                    sort_keys=True)
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(1, 10), epoch)
            if was_known:
                after = json.dumps(
                    (eng.state["accounts"], eng.state["orders"].get(oid)),
                    sort_keys=True)
                if before != after:
                    dup_effects += 1
        elif r < 0.76 and used:
            oid = rng.choice(used) if rng.random() < 0.8 else f"ghost-{i}"
            eng.cancel(oid, epoch)
        elif r < 0.82 and used:                    # 원자적 취소·재호가
            old = rng.choice(used)
            oid = f"s{scen}-o{next_oid}"; next_oid += 1
            used.append(oid)
            eng.cancel_replace(old, oid, rng.choice(AGENTS),
                               rng.choice(["buy", "sell"]),
                               rng.randint(90, 110) * 100, rng.randint(1, 10),
                               epoch)
        elif r < 0.88:
            oid = f"s{scen}-o{next_oid}"; next_oid += 1
            used.append(oid)
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(500, 5000), epoch)
        elif r < 0.93:
            eng.request_snapshot(rng.choice(AGENTS))
        else:
            eng.bump_epoch()
            for _ in range(2):
                oid = f"s{scen}-o{next_oid}"; next_oid += 1
                eng.submit(oid, rng.choice(AGENTS), "buy", 100 * 100, 1, epoch)

        if is_auction and i % CLOCK_EVERY == CLOCK_EVERY - 1:
            eng.advance_clock()
            violations += check_invariants(eng.state, TOTALS, crossed_ok=False)
        else:
            violations += check_invariants(eng.state, TOTALS, crossed_ok=is_auction)
        if rng.random() < 0.004:
            checkpoints.append((len(eng.log), state_hash(eng.state)))

    return eng, violations, dup_attempts, dup_effects, checkpoints


class PropertyTests(unittest.TestCase):

    def _run(self, factory, is_auction):
        total_dups = 0
        for scen in range(N_SCENARIOS):
            eng, violations, dups, dup_effects, cps = run_scenario(
                factory, scen, is_auction)
            self.assertEqual(violations, [], f"scenario {scen}")
            self.assertEqual(dup_effects, 0, f"scenario {scen}: duplicate had effect")
            total_dups += dups
            self.assertEqual(state_hash(replay(eng.log)), state_hash(eng.state),
                             f"scenario {scen}: full replay mismatch")
            for k, h in cps:
                self.assertEqual(state_hash(replay(eng.log[:k])), h,
                                 f"scenario {scen}: prefix replay mismatch at {k}")
        self.assertGreater(total_dups, 0, "generator produced no duplicate attempts")

    def test_cda(self):
        self._run(CDA, is_auction=False)

    def test_call_auction(self):
        self._run(CallAuction, is_auction=True)

    def test_stale_epoch_rejected(self):
        eng = MarketEngine(CDA(), FullBook())
        eng.create_account("A", 1000, 10)
        eng.bump_epoch()
        eng.submit("x", "A", "buy", 100, 1, epoch=0)   # 옛 세대 주문
        self.assertEqual(eng.state["rejections"]["stale_epoch"], 1)
        self.assertNotIn("x", eng.state["orders"])


if __name__ == "__main__":
    unittest.main()

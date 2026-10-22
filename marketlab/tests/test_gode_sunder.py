"""M2 완료 기준 (설계안 §9): 동기 라운드 ZI-C 시장이 Gode & Sunder (1993)의
정형화 사실 — 제약된 제로 지능 트레이더의 CDA가 높은 배분 효율에 도달 —
을 재현하는지 검사한다.

시장: 한계 내 매수자 10(가치 105~150) / 매도자 10(비용 50~95) + 한계 외
매수자 3(80~90) / 매도자 3(110~120). 경쟁 균형 수량 10, 최대 잉여 550.
한계 외 트레이더가 한계 내 거래를 밀어내면 효율이 1 아래로 떨어질 수 있다 —
그럼에도 효율이 높게 유지된다는 것이 GS의 발견이다.
"""

import unittest

from marketlab.agents.zi import ZITrader
from marketlab.clock.sync_rounds import SyncRounds
from marketlab.core.engine import MarketEngine
from marketlab.core.invariants import check_invariants
from marketlab.core.state import replay, state_hash
from marketlab.disclosure.policies import TradesOnly
from marketlab.gateway.ingress import Gateway
from marketlab.mechanisms.cda import CDA

PMIN, PMAX = 1, 200
BUYER_VALUES = [150, 145, 140, 135, 130, 125, 120, 115, 110, 105, 90, 85, 80]
SELLER_COSTS = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 110, 115, 120]
MAX_SURPLUS = sum(BUYER_VALUES[:10]) - sum(SELLER_COSTS[:10])   # = 550


def build_agents(seed):
    agents = []
    for i, v in enumerate(BUYER_VALUES):
        agents.append(ZITrader(f"B{i}", "buyer", [v], PMIN, PMAX,
                               seed * 1000 + i, cash=PMAX))
    for i, c in enumerate(SELLER_COSTS):
        agents.append(ZITrader(f"S{i}", "seller", [c], PMIN, PMAX,
                               seed * 2000 + i))
    return agents


def run_market(seed, rounds=100):
    eng = MarketEngine(CDA(), TradesOnly(), seed=seed)
    gw = Gateway(eng)
    agents = build_agents(seed)
    runner = SyncRounds(gw, agents, master_seed=seed)
    runner.setup()
    runner.run(rounds)
    return eng, agents


def efficiency(eng):
    realized = 0
    for i, v in enumerate(BUYER_VALUES):
        bought = eng.state["accounts"][f"B{i}"]["shares"]
        realized += v * min(bought, 1)
    for i, c in enumerate(SELLER_COSTS):
        a = eng.state["accounts"][f"S{i}"]
        sold = 1 - a["shares"] - a["res_shares"]
        realized -= c * min(sold, 1)
    return realized / MAX_SURPLUS


class GodeSunderTest(unittest.TestCase):

    def test_zic_cda_allocative_efficiency(self):
        total_cash = sum(a.endowment()[0] for a in build_agents(0))
        total_shares = sum(a.endowment()[1] for a in build_agents(0))
        effs = []
        for seed in range(1, 6):
            eng, _ = run_market(seed)
            e = efficiency(eng)
            effs.append(e)
            # 회계·재생은 여기서도 깨끗해야 한다
            self.assertEqual(
                check_invariants(eng.state, (total_cash, total_shares)), [],
                f"seed {seed}")
            self.assertEqual(state_hash(replay(eng.log)), state_hash(eng.state),
                             f"seed {seed}: replay mismatch")
            self.assertGreaterEqual(e, 0.85, f"seed {seed}: efficiency {e:.3f}")
        mean_eff = sum(effs) / len(effs)
        print(f"\n[Gode-Sunder] efficiency by seed: "
              + ", ".join(f"{e:.3f}" for e in effs)
              + f" | mean={mean_eff:.3f}")
        self.assertGreaterEqual(mean_eff, 0.90)

    def test_trade_prices_within_rational_bounds(self):
        """ZI-C 예산 제약의 귀결: 어떤 체결가도 [최저 비용, 최고 가치] 밖일 수 없다."""
        eng, _ = run_market(seed=7)
        prices = [ev["price"] for ev in eng.log if ev["type"] == "trade"]
        self.assertGreater(len(prices), 0)
        self.assertGreaterEqual(min(prices), min(SELLER_COSTS))
        self.assertLessEqual(max(prices), max(BUYER_VALUES))

    def test_determinism_same_seed(self):
        a, _ = run_market(seed=3)
        b, _ = run_market(seed=3)
        self.assertEqual(state_hash(a.state), state_hash(b.state))

    def test_different_seed_differs(self):
        a, _ = run_market(seed=3)
        b, _ = run_market(seed=4)
        self.assertNotEqual(state_hash(a.state), state_hash(b.state))


if __name__ == "__main__":
    unittest.main()

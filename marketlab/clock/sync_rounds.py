"""모드 A: 동기 라운드 (설계안 §4).

라운드마다 ① 전원이 라운드 시작 시점의 같은 상태를 관찰(고정 순서로 스냅샷 발급)
② 판단 수집(이 동안 시장은 멈춰 있음) ③ 시드 셔플 순서로 반입(공평성은 명시적
셔플로 — NetLogo ask의 교훈) ④ 논리적 시간 1 진행. 속도 차이는 완전히 소거된다.
미응답(None)은 기권 이벤트로 기록된다.
"""

import random


class SyncRounds:
    def __init__(self, gateway, agents, master_seed):
        self.gw = gateway
        self.agents = list(agents)
        # 문자열 시드: CPython이 sha512로 시드하므로 프로세스 간 결정적
        self.shuffle_rng = random.Random(f"sync-shuffle-{master_seed}")

    def setup(self):
        for a in self.agents:
            cash, shares = a.endowment()
            self.gw.create_account(a.agent_id, cash, shares)

    def run(self, n_rounds):
        for r in range(n_rounds):
            self.run_round(r)

    def run_round(self, r):
        gw = self.gw
        # ① 같은 시점의 관찰 (발급 순서는 고정: 로그 결정론)
        snaps = {a.agent_id: gw.snapshot(a.agent_id) for a in self.agents}
        # ② 판단 수집 — 시장 상태는 아직 불변
        decisions = [(a, a.decide(snaps[a.agent_id], {"round": r}))
                     for a in self.agents]
        # ③ 명시적 셔플 반입
        self.shuffle_rng.shuffle(decisions)
        for agent, dec in decisions:
            aid = agent.agent_id
            if dec is None:
                gw.abstain(aid, "no_decision")
                continue
            for oid in dec.get("cancels", []):
                gw.cancel(oid, gw.epoch)
            for j, o in enumerate(dec.get("orders", [])):
                gw.submit(f"r{r}-{aid}-{j}", aid, o["side"], o["price"],
                          o["qty"], gw.epoch)
        # ④ 논리적 시간 진행 (일괄 경매라면 여기서 클리어링)
        gw.clock()

"""모드 B: 지연 주입 (설계안 §4).

이산 사건 스케줄: 에이전트는 주기적으로 '지금' 상태를 보고 판단하고(순차 정보
세계), 그 결과는 지연 모형이 준 δ 뒤의 모형 시간에 도착한다. δ는 라이브에서도
먼저 수치로 고정된 뒤 스케줄에 들어간다 — 벽시계가 모형 시간을 직접 결정하는
설계를 금지하는 장치. 같은 판단 스트림에 다른 δ 가정을 적용하는 반사실 실험이
가능하다. 힙의 동시각 동률은 단조 증가 일련번호로 깨서 완전 결정론을 유지한다.
"""

import heapq
import random


class LatencyRounds:
    def __init__(self, gateway, agents, delay_model, master_seed,
                 decision_interval=1.0):
        self.gw = gateway
        self.agents = {a.agent_id: a for a in agents}
        self.delay_model = delay_model          # (agent_id, rng) -> δ
        self.rng = random.Random(f"latency-{master_seed}")
        self.interval = decision_interval
        self.delays = []                        # 기록된 δ (분석·반사실용)

    def setup(self):
        for a in self.agents.values():
            cash, shares = a.endowment()
            self.gw.create_account(a.agent_id, cash, shares)

    def run(self, horizon):
        heap, seq = [], 0
        for aid in self.agents:                 # 고정 순서로 초기 판단 예약
            heapq.heappush(heap, (0.0, seq, "decide", aid)); seq += 1
        tick, n_calls = 0, 0
        while heap:
            t, _, kind, payload = heapq.heappop(heap)
            if t > horizon:
                break
            while tick < int(t):                # 논리적 시간을 사건 시각까지 진행
                self.gw.clock(); tick += 1
            if kind == "decide":
                aid = payload
                snap = self.gw.snapshot(aid)    # 순차 정보: '지금'의 상태
                dec = self.agents[aid].decide(snap, {"round": tick})
                if dec is None:
                    self.gw.abstain(aid, "no_decision")
                else:
                    delay = self.delay_model(aid, self.rng)
                    self.delays.append({"agent": aid, "t": t, "delay": delay})
                    heapq.heappush(heap, (t + delay, seq, "arrive",
                                          (aid, dec, n_calls))); seq += 1
                    n_calls += 1
                heapq.heappush(heap, (t + self.interval, seq, "decide", aid))
                seq += 1
            else:                               # arrive: 판단 결과가 시장에 도착
                aid, dec, call = payload
                for oid in dec.get("cancels", []):
                    self.gw.cancel(oid, self.gw.epoch)
                for j, o in enumerate(dec.get("orders", [])):
                    self.gw.submit(f"c{call}-{aid}-{j}", aid, o["side"],
                                   o["price"], o["qty"], self.gw.epoch)
        while tick < horizon:
            self.gw.clock(); tick += 1

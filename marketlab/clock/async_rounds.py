"""모드 A의 비동기 수집 버전 (설계안 §4·§6).

LLM 호출은 라운드마다 병렬로 발사되지만, 반입은 전부 수집된 뒤 시드 셔플
순서로 이뤄진다 — 완료 순서는 결과에 영향을 주지 않는다(동기 라운드 의미론
유지). 라이브 실행의 비결정성은 응답 내용과 타임아웃뿐이고 둘 다 호출 로그에
기록되므로, ReplayAdapter로 같은 러너를 다시 돌리면 비트 단위로 재현된다.

타임아웃·파싱 실패·LLM 오류 = 기권 이벤트(결측이 아니라 데이터).
BudgetExhausted = 그 라운드 반입 없이 정상 종료(부분 도착 로그도 재생 가능).
"""

import asyncio
import random

from marketlab.llm.adapter import BudgetExhausted


class AsyncRounds:
    def __init__(self, gateway, agents, adapter, master_seed):
        self.gw = gateway
        self.agents = list(agents)
        self.adapter = adapter
        self.shuffle_rng = random.Random(f"async-shuffle-{master_seed}")
        self.decision_log = []     # δ 재배정 반사실용: 라운드별 채택 판단
        self.budget_exhausted = False

    def setup(self):
        for a in self.agents:
            cash, shares = a.endowment()
            self.gw.create_account(a.agent_id, cash, shares)

    def run(self, n_rounds):
        asyncio.run(self._run(n_rounds))

    async def _run(self, n_rounds):
        for r in range(n_rounds):
            if not await self._round(r):
                break

    async def _round(self, r):
        gw = self.gw
        # ① 같은 시점의 관찰 (고정 순서 발급)
        snaps = {a.agent_id: gw.snapshot(a.agent_id) for a in self.agents}
        epoch = gw.epoch
        # ② LLM 호출 병렬 발사, 전부 수집
        results = await asyncio.gather(
            *(a.acall(getattr(a, "adapter", None) or self.adapter,
                      snaps[a.agent_id], r, epoch)
              for a in self.agents),
            return_exceptions=True)   # 에이전트별 어댑터 허용 → 모델 이질성 요인
        collected = []
        for agent, res in zip(self.agents, results):
            if isinstance(res, BudgetExhausted):
                self.budget_exhausted = True
                return False                     # 이번 라운드는 반입하지 않고 종료
            if isinstance(res, BaseException):
                raise res
            collected.append((agent, res[0], res[1]))
        # ③ 명시적 셔플 반입 (완료 순서 무관)
        self.shuffle_rng.shuffle(collected)
        for agent, dec, reason in collected:
            aid = agent.agent_id
            if dec is None:
                gw.abstain(aid, reason)
                continue
            self.decision_log.append({"t": r, "agent": aid, "dec": dec})
            for oid in dec.get("cancels", []):
                gw.cancel(oid, gw.epoch)
            for j, rep in enumerate(dec.get("replaces", [])):
                o = rep["order"]
                gw.cancel_replace(rep["old"], f"r{r}-{aid}-x{j}", aid,
                                  o["side"], o["price"], o["qty"], gw.epoch)
            for j, o in enumerate(dec.get("orders", [])):
                gw.submit(f"r{r}-{aid}-{j}", aid, o["side"], o["price"],
                          o["qty"], gw.epoch)
        # ④ 논리적 시간 진행
        gw.clock()
        return True

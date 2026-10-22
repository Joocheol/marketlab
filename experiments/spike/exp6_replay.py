"""실험 6: LLM 기록·재생 결정론.

진짜 LLM 대신 '통제 불가능한 비결정 원천'을 가진 모의 에이전트를 쓴다:
결정은 os.urandom 기반 난수(SystemRandom)로, 도착 순서는 실제 스레드
스케줄링과 수면 지연으로 정해진다. 즉 라이브 실행은 원리적으로 재현 불가다.

기록하는 것: 계좌 초기화 파라미터 + '엔진에 도착한 순서대로의' 응답(주문) 전부.
재생 모드: 스레드·수면·난수 없이 기록된 응답을 기록된 순서로 다시 주입.

판별 기준:
  - 재생 1·2회 모두 라이브 실행과 최종 상태 해시 일치 (기록이 충분조건)
  - 라이브 실행을 한 번 더 하면 해시 불일치 (비결정성의 존재 증명)
  - 기록 1건을 빼고 재생하면 해시 불일치 (로그 변조 탐지)
"""

import json
import queue
import random
import threading
import time

from engine import MarketEngine, state_hash

AGENTS = ["L1", "L2", "L3"]
CALLS_PER_AGENT = 50
INIT_CASH = 200_000
INIT_SHARES = 200

sysrng = random.SystemRandom()   # os.urandom: 시드 불가능 = LLM 비결정성의 대역


def mock_llm_decide(snapshot, agent):
    """스냅샷을 보고 주문을 '생각해 내는' 모의 LLM. 시드 불가능한 난수 사용."""
    best_bid, best_ask = snapshot["best_bid"], snapshot["best_ask"]
    mid = (best_bid + best_ask) // 2 if best_bid and best_ask else 100 * 100
    side = "buy" if sysrng.random() < 0.5 else "sell"
    tilt = sysrng.randint(-300, 300)
    return {"side": side, "price": max(1, mid + tilt), "qty": sysrng.randint(1, 5)}


def snapshot_of(eng, agent, lock):
    with lock:
        s = eng.state
        return {
            "best_bid": s["orders"][s["bids"][0]]["price"] if s["bids"] else None,
            "best_ask": s["orders"][s["asks"][0]]["price"] if s["asks"] else None,
            "cash": s["accounts"][agent]["cash"],
            "shares": s["accounts"][agent]["shares"],
        }


def live_run():
    """라이브 모드: 에이전트별 스레드가 지연·난수와 함께 주문을 만들어 큐로 보낸다."""
    eng = MarketEngine()
    lock = threading.Lock()
    for ag in AGENTS:
        eng.create_account(ag, INIT_CASH, INIT_SHARES)
    ingress = queue.Queue()
    done = threading.Event()
    remaining = [len(AGENTS) * CALLS_PER_AGENT]

    def agent_loop(ag):
        for i in range(CALLS_PER_AGENT):
            time.sleep(sysrng.uniform(0.001, 0.015))     # 모의 LLM 지연
            snap = snapshot_of(eng, ag, lock)
            order = mock_llm_decide(snap, ag)
            ingress.put({"agent": ag, "call": f"{ag}-c{i}", "order": order})

    threads = [threading.Thread(target=agent_loop, args=(ag,), daemon=True)
               for ag in AGENTS]
    for t in threads:
        t.start()

    record = []     # 엔진 도착 순서 그대로
    processed = 0
    while processed < remaining[0]:
        item = ingress.get()
        with lock:
            o = item["order"]
            eng.submit(item["call"], item["agent"], o["side"], o["price"], o["qty"],
                       eng.state["epoch"])
        record.append(item)
        processed += 1
    for t in threads:
        t.join()
    return eng, record


def replay_run(record):
    """재생 모드: 스레드·지연·난수 없이 기록을 그대로 주입."""
    eng = MarketEngine()
    for ag in AGENTS:
        eng.create_account(ag, INIT_CASH, INIT_SHARES)
    for item in record:
        o = item["order"]
        eng.submit(item["call"], item["agent"], o["side"], o["price"], o["qty"],
                   eng.state["epoch"])
    return eng


live1, record = live_run()
h_live1 = state_hash(live1.state)
with open("exp6-record.json", "w") as f:
    json.dump(record, f)

h_replay1 = state_hash(replay_run(record).state)
h_replay2 = state_hash(replay_run(record).state)

live2, _ = live_run()
h_live2 = state_hash(live2.state)

tampered = record[:70] + record[71:]        # 기록 1건 제거
h_tampered = state_hash(replay_run(tampered).state)

n_trades = sum(1 for ev in live1.log if ev["type"] == "trade")
print(f"calls recorded={len(record)} trades(live1)={n_trades}")
print(f"live1   = {h_live1[:16]}")
print(f"replay1 = {h_replay1[:16]}  match={h_replay1 == h_live1}")
print(f"replay2 = {h_replay2[:16]}  match={h_replay2 == h_live1}")
print(f"live2   = {h_live2[:16]}  differs-from-live1={h_live2 != h_live1}")
print(f"tampered= {h_tampered[:16]}  differs-from-live1={h_tampered != h_live1}")
ok = (h_replay1 == h_live1 and h_replay2 == h_live1
      and h_live2 != h_live1 and h_tampered != h_live1)
print("PASS" if ok else "FAIL")

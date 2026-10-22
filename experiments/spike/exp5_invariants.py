"""실험 5: 회계 불변식 속성 테스트.

시드된 난수로 무작위 시나리오(정상 주문 + 중복 제출 + 미지/기체결 취소 +
잔고 초과 주문 + epoch 리셋 후 늦은 주문)를 생성해 엔진에 주입하고,
매 명령 뒤에 불변식을 검사한다. 시나리오가 끝나면 이벤트 로그만으로
전체 재생과 무작위 접두사 재생을 수행해 상태 해시가 일치하는지 확인한다.

판별 기준: 불변식 위반 0건, 중복 제출의 상태 효과 0건, 재생 불일치 0건.
"""

import json
import random
import time

from engine import MarketEngine, replay, state_hash, check_invariants

N_SCENARIOS = 100
N_COMMANDS = 2000
AGENTS = ["A", "B", "C", "D"]
INIT_CASH = 100_000     # cents
INIT_SHARES = 100

totals = (INIT_CASH * len(AGENTS), INIT_SHARES * len(AGENTS))

violations = 0
dup_attempts = 0
dup_effects = 0
retry_after_reject = 0
stale_rejected = 0
replay_mismatch = 0
prefix_mismatch = 0
trades = 0
t_start = time.time()

for scen in range(N_SCENARIOS):
    rng = random.Random(42_000 + scen)
    eng = MarketEngine()
    for ag in AGENTS:
        eng.create_account(ag, INIT_CASH, INIT_SHARES)
    used_oids = []
    checkpoints = []
    next_oid = 0

    for i in range(N_COMMANDS):
        r = rng.random()
        epoch = eng.state["epoch"]
        if r < 0.62:                                   # 정상 범위 주문
            oid = f"s{scen}-o{next_oid}"; next_oid += 1
            used_oids.append(oid)
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(1, 10), epoch)
        elif r < 0.70 and used_oids:                   # 중복 제출 (다른 파라미터로!)
            oid = rng.choice(used_oids)
            # 엔진의 멱등성 계약: '수리(accepted)된' 명령의 재제출만 무효.
            # 거부된 주문의 재시도는 새 제출로 취급되어 효과가 있는 것이 정상이므로 구분.
            was_known = oid in eng.state["orders"]
            if was_known:
                dup_attempts += 1
                before = json.dumps((eng.state["accounts"], eng.state["orders"].get(oid)),
                                    sort_keys=True)
            else:
                retry_after_reject += 1
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(1, 10), epoch)
            if was_known:
                after = json.dumps((eng.state["accounts"], eng.state["orders"].get(oid)),
                                   sort_keys=True)
                if before != after:
                    dup_effects += 1
        elif r < 0.80 and used_oids:                   # 취소 (열림/체결/미지 섞임)
            oid = rng.choice(used_oids) if rng.random() < 0.8 else f"ghost-{i}"
            eng.cancel(oid, epoch)
        elif r < 0.90:                                 # 잔고 초과 주문
            oid = f"s{scen}-o{next_oid}"; next_oid += 1
            used_oids.append(oid)
            eng.submit(oid, rng.choice(AGENTS), rng.choice(["buy", "sell"]),
                       rng.randint(90, 110) * 100, rng.randint(500, 5000), epoch)
        else:                                          # epoch 리셋 + 늦은(stale) 주문 3건
            eng.bump_epoch()
            for _ in range(3):
                oid = f"s{scen}-o{next_oid}"; next_oid += 1
                eng.submit(oid, rng.choice(AGENTS), "buy", 100 * 100, 1, epoch)  # 옛 epoch
        errs = check_invariants(eng.state, totals)
        if errs:
            violations += len(errs)
            print(f"[scenario {scen} cmd {i}] INVARIANT VIOLATION: {errs[:3]}")
        if rng.random() < 0.002:                       # 무작위 체크포인트 (시나리오당 ~4개)
            checkpoints.append((len(eng.log), state_hash(eng.state)))

    stale_rejected += eng.state["rejections"]["stale_epoch"]
    trades += sum(1 for ev in eng.log if ev["type"] == "trade")

    # 전체 재생: 이벤트 로그의 순수 폴드가 라이브 상태와 일치하는가
    if state_hash(replay(eng.log)) != state_hash(eng.state):
        replay_mismatch += 1
        print(f"[scenario {scen}] FULL REPLAY MISMATCH")
    # 접두사 재생: 임의 시점의 상태 = 로그 접두사의 폴드
    for (k, h) in checkpoints:
        if state_hash(replay(eng.log[:k])) != h:
            prefix_mismatch += 1
            print(f"[scenario {scen}] PREFIX REPLAY MISMATCH at {k}")

elapsed = time.time() - t_start
print(f"scenarios={N_SCENARIOS} commands={N_SCENARIOS * N_COMMANDS} trades={trades} "
      f"elapsed={elapsed:.1f}s")
print(f"invariant violations      : {violations}")
print(f"duplicate submits         : attempted={dup_attempts}, with state effect={dup_effects}")
print(f"retries of rejected oids  : {retry_after_reject} (새 제출로 취급, 효과 허용)")
print(f"stale-epoch orders rejected: {stale_rejected}")
print(f"full replay mismatches    : {replay_mismatch}")
print(f"prefix replay mismatches  : {prefix_mismatch}")
print("PASS" if (violations == dup_effects == replay_mismatch == prefix_mismatch == 0)
      else "FAIL")

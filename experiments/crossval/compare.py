"""M5 교차 검증: NetLogo와 marketlab의 같은 ZI-CDA 시나리오 통계 비교.

두 구현은 난수 생성기·반입 순서가 다르므로 비트 일치가 아니라 '같은 분포'가
목표다. 런 수준 지표 4종(배분 효율, 평균 체결가, 체결 수, 런 내 가격 표준편차)
각 30런 표본에 대해 Welch t(평균 차이)와 KS 거리(분포 차이)를 계산한다.

판별 기준(공학적 교차 검증): 모든 지표에서 |t| < 2.0 이고 KS D < D_crit(5%).
주의: 유의하지 않음이 동등성의 증명은 아니다 — 효과 크기도 함께 보고한다.
"""

import csv
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from marketlab.tests.test_gode_sunder import run_market  # noqa: E402

N_RUNS = 100
ROUNDS = 100


def marketlab_runs():
    rows = []
    for seed in range(1, N_RUNS + 1):
        eng, _ = run_market(seed, ROUNDS)
        # GS 테스트는 가치·비용(50~150)을 가격 단위로 그대로 쓴다 — 스케일 변환 불필요
        prices = [ev["price"] for ev in eng.log if ev["type"] == "trade"]
        from marketlab.tests.test_gode_sunder import efficiency
        rows.append({
            "efficiency": efficiency(eng),
            "mean_price": sum(prices) / len(prices) if prices else 0,
            "n_trades": len(prices),
            "price_std": _std(prices)})
    return rows


def netlogo_runs(path):
    rows = []
    with open(path) as fp:
        for r in csv.reader(fp):
            if r and r[0].isdigit():
                rows.append({"efficiency": float(r[2]), "mean_price": float(r[3]),
                             "n_trades": float(r[4]), "price_std": float(r[5])})
    return rows


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def welch_t(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va, vb = _std(a) ** 2, _std(b) ** 2
    se = math.sqrt(va / len(a) + vb / len(b))
    return (ma - mb) / se if se > 0 else 0.0, ma, mb


def ks_distance(a, b):
    both = sorted(set(a) | set(b))
    sa, sb = sorted(a), sorted(b)
    d = 0.0
    for x in both:
        fa = sum(1 for v in sa if v <= x) / len(sa)
        fb = sum(1 for v in sb if v <= x) / len(sb)
        d = max(d, abs(fa - fb))
    return d


def main():
    nl = netlogo_runs(pathlib.Path(__file__).parent / "netlogo-results.csv")
    ml = marketlab_runs()
    assert len(nl) == len(ml) == N_RUNS
    d_crit = 1.358 * math.sqrt(2 / N_RUNS)
    print(f"runs: {N_RUNS} each | KS 5% critical D = {d_crit:.3f}")
    print(f"{'metric':<12} {'NetLogo mean':>13} {'marketlab mean':>15} "
          f"{'Welch t':>8} {'KS D':>6}  verdict")
    all_ok = True
    for key in ("efficiency", "mean_price", "n_trades", "price_std"):
        a = [r[key] for r in nl]
        b = [r[key] for r in ml]
        t, ma, mb = welch_t(a, b)
        d = ks_distance(a, b)
        ok = abs(t) < 2.0 and d < d_crit
        all_ok &= ok
        print(f"{key:<12} {ma:>13.4f} {mb:>15.4f} {t:>8.2f} {d:>6.3f}  "
              f"{'일치' if ok else '불일치'}")
    print("CROSS-VALIDATION " + ("PASS" if all_ok else "FAIL"))


if __name__ == "__main__":
    main()

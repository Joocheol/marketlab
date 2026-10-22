"""기준선 연구 실험: ZI·규칙 개체군 × 메커니즘 × 정보 공개 → 스타일라이즈드 팩트.

목적 (engine-design.md §7, 보고서 10.7): LLM 투입 전에 "지능 없는" 시장에서
메커니즘·정보 구조·개체군 구성만으로 어떤 가격 동학이 생기는지의 대조군을
확보한다. 관찰된 LLM 시장의 성질 중 이 기준선으로 설명되는 부분은 지능
효과가 아니다.

요인 (2×2×2, 반복 10 = 80런):
  mechanism   : cda | call_auction
  info_policy : best_quote_only | trades_only
                (trades_only에서는 규칙 기반 마켓메이커가 호가를 못 보므로
                 전원 기권 — 정보 차단의 효과가 혼성 개체군에서만 나타난다)
  population  : zi-only (노이즈 24) | mixed (노이즈 18 + 스프레드 개선 6)

런별 측정: 틱 경계 가격 경로의 스타일라이즈드 팩트 (초과 첨도, 자기상관,
변동성, 스프레드). 실행 후 각 런의 record.json(재현 패키지)을 재생해 계산 —
실험 실행과 분석이 완전히 분리된다.

실행:  python3 experiments/baseline/run_baseline.py [--smoke]
"""

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketlab.analysis.stylized import stylized_facts          # noqa: E402
from marketlab.gateway.ingress import replay_record             # noqa: E402
from marketlab.lab.experiment import engine_factory, run_experiment  # noqa: E402

ZI_ONLY = [{"type": "noise", "count": 24, "cash": 5000, "shares": 20, "band": 10}]
MIXED = [{"type": "noise", "count": 18, "cash": 5000, "shares": 20, "band": 10},
         {"type": "spread", "count": 6, "cash": 5000, "shares": 20}]

CONFIG = {
    "name": "baseline",
    "factors": {
        "mechanism": ["cda", "call_auction"],
        "info_policy": ["best_quote_only", "trades_only"],
        "clock": [{"mode": "sync", "rounds": 400}],
        "population": [ZI_ONLY, MIXED],
    },
    "repetitions": 10,
    "master_seed": 20261022,
}

OUT = pathlib.Path(__file__).parent / "runs"


def cell_key(factors):
    pop = "mixed" if len(factors["population"]) > 1 else "zi-only"
    return (factors["mechanism"], factors["info_policy"], pop)


def analyse(results):
    rows = []
    for r in results:
        with open(OUT / r["run_id"] / "record.json") as fp:
            record = json.load(fp)
        eng = replay_record(record, engine_factory)
        facts = stylized_facts(eng.log)
        rows.append({"cell": cell_key(r["factors"]), "run_id": r["run_id"],
                     **facts})
    return rows


def _mean_sd(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return (None, None, 0)
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0
    return (m, sd, len(xs))


def welch_t(a, b):
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    (ma, sa, na), (mb, sb, nb) = _mean_sd(a), _mean_sd(b)
    se = math.sqrt(sa * sa / na + sb * sb / nb)
    return (ma - mb) / se if se > 0 else 0.0


METRICS = ["ret_std", "ex_kurtosis", "acf1_ret", "acf1_abs",
           "mean_spread", "n_trades", "mean_price"]


def report(rows, out_path):
    cells = sorted({r["cell"] for r in rows})
    lines = ["# 기준선 실험 결과 (런 400라운드 × 반복 10)", ""]
    lines.append("## 셀별 평균 (±표준편차)")
    lines.append("")
    header = "| mechanism | info | population | " + " | ".join(METRICS) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (3 + len(METRICS)))
    for c in cells:
        sub = [r for r in rows if r["cell"] == c]
        vals = []
        for mkey in METRICS:
            m, sd, n = _mean_sd([r[mkey] for r in sub])
            vals.append("—" if m is None else f"{m:.4g} (±{sd:.2g})")
        lines.append("| " + " | ".join(c) + " | " + " | ".join(vals) + " |")

    lines.append("")
    lines.append("## 주요 대비 (Welch t, 반복 전체 풀링)")
    lines.append("")

    def contrast(name, pred_a, pred_b, metric):
        a = [r[metric] for r in rows if pred_a(r["cell"])]
        b = [r[metric] for r in rows if pred_b(r["cell"])]
        t = welch_t(a, b)
        ma = _mean_sd(a)[0]
        mb = _mean_sd(b)[0]
        if t is None or ma is None or mb is None:
            lines.append(f"- {name} [{metric}]: 표본 부족")
        else:
            lines.append(f"- {name} [{metric}]: {ma:.4g} vs {mb:.4g}, t={t:.2f}")

    is_cda = lambda c: c[0] == "cda"
    is_auc = lambda c: c[0] == "call_auction"
    for m in ("ret_std", "ex_kurtosis", "acf1_ret", "n_trades"):
        contrast("CDA vs 일괄경매", is_cda, is_auc, m)
    # 스프레드 대비는 연속 호가장이 상시 존재하는 CDA 셀로 한정해 해석을 명확히
    mixed_bq = lambda c: c[0] == "cda" and c[2] == "mixed" and c[1] == "best_quote_only"
    zi_bq = lambda c: c[0] == "cda" and c[2] == "zi-only" and c[1] == "best_quote_only"
    for m in ("mean_spread", "ret_std"):
        contrast("CDA 혼성(MM 활동) vs ZI 단독 — 호가 공개 하", mixed_bq, zi_bq, m)
    mixed_to = lambda c: c[0] == "cda" and c[2] == "mixed" and c[1] == "trades_only"
    for m in ("mean_spread", "ret_std"):
        contrast("CDA 혼성: 호가 공개 vs 차단(MM 무력화)", mixed_bq, mixed_to, m)

    text = "\n".join(lines) + "\n"
    out_path.write_text(text)
    print(text)


def main():
    smoke = "--smoke" in sys.argv
    config = dict(CONFIG)
    if smoke:
        config = json.loads(json.dumps(CONFIG))
        config["repetitions"] = 2
        config["factors"]["clock"] = [{"mode": "sync", "rounds": 100}]
        config["name"] = "baseline-smoke"
    results = run_experiment(config, str(OUT), max_workers=1 if smoke else 6)
    rows = analyse(results)
    (pathlib.Path(__file__).parent / "facts.json").write_text(
        json.dumps([{"cell": list(r["cell"]), **{k: r[k] for k in r if k != "cell"}}
                    for r in rows], indent=1))
    report(rows, pathlib.Path(__file__).parent / "RESULTS.md")


if __name__ == "__main__":
    main()

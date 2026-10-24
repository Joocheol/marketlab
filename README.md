# marketlab

이질적 LLM 에이전트들이 거래하는 주식시장을 연구하기 위한 이벤트 소싱 시장 시뮬레이션 엔진과 실험 기록.
*An event-sourced market engine for heterogeneous LLM-agent stock market research — NetLogo cross-validated, with a full experimental arc from zero-intelligence baselines to per-tick local-LLM markets.*

NetLogo(데스크톱·웹) 소스의 역공학 분석에서 설계 원칙을 도출하고(보고서), 그 원칙 위에 독립 엔진을 구현·검증한 뒤(설계안 로드맵 M0~M5), 같은 엔진에서 규칙 기반 → 클론 설계 정책 → 매 틱 로컬 LLM 판단으로 에이전트를 올려 가며 시장 실험을 수행했다. 유료 API는 사용하지 않았다.

## 핵심 설계 원칙

- **상태 변경의 문은 하나**: 모든 변경은 단일 직렬화 지점(엔진)이 계산한 이벤트의 순수 폴드로만 일어나고, 재생(replay)은 매칭 로직 없이 이벤트 로그만 다시 접는다.
- **비결정 원천 3종의 통제**: 엔진 난수는 시드로, 사건 순서는 도착 로그로, LLM 응답은 호출 로그로 — 셋이 있으면 어떤 런이든 비트 단위로 재현된다(실제 LLM 런 포함, 전 실험에서 검증).
- **멱등 주문 키 + epoch 표지 + 원자적 cancel-replace**: 재시도 중복, 리셋 후 좀비 응답, 낡은 스냅샷 기반 이중 노출을 구조적으로 차단.
- **격리 자동화**: 실험 런 = 새 프로세스/새 엔진, 시드는 마스터에서 해시 파생.
- **위험한도는 하네스(브로커)가 강제**: 프롬프트로 전달한 한도는 모델 의존적으로만 지켜진다(실측).

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `netlogo-analysis-report.md` | NetLogo·Tortoise·Galapagos 역공학 분석 (구조·실행 의미론·스레드 모델·확장 경계 + 실측 실험 6건) |
| `engine-design.md` | 엔진 설계안과 로드맵 M0~M5 완료 기록, 미결 연구 가정 |
| `marketlab/core` `mechanisms` `disclosure` | 이벤트 소싱 엔진, CDA·일괄 경매, 정보 공개 정책 |
| `marketlab/gateway` `clock` `lab` | 도착 로그(재현 패키지), 시간 모델 3종, 실험 관리자·반사실 실행기 |
| `marketlab/agents` | ZI-C(Gode-Sunder)·노이즈·규칙 기반·LLM 에이전트 |
| `marketlab/llm` | LLM 어댑터 3모드(live/replay/cache)·호출 로그·예산 가드·**Ollama 로컬 전송**·모의 LLM |
| `marketlab/tests` | 테스트 38개 (속성·전수 대조·재생 결정론) |
| `experiments/crossval` | NetLogo 7.0.4 교차 검증 (ZI-CDA 100런, 4지표 통계 일치) |
| `experiments/baseline` | 기준선: 잡음·규칙 개체군 × 메커니즘 × 정보 요인 80런 |
| `experiments/claude-pilot` | 클론 파일럿과 LLM 실험 전체: 수동 6라운드 → 정책 증류 100런 × 3정보체제 → 매 틱 로컬 LLM(모델 3종, 구조화 출력 판별까지) |

## 주요 결과 (요약)

**엔진·방법 검증**: NetLogo와의 교차 검증에서 동일 ZI-CDA 시나리오 100런의 4개 지표가 통계적으로 일치. 모든 실험 런은 회계 불변식 검사와 재생(도착 로그·LLM 호출 로그) 해시 검증을 통과.

**정보 구조가 시장 '체제'를 결정한다** (클론 설계 정책, 각 100런):
무앵커(이질 신념) → 활발한 투기·버블·자유 표류 / 확실한 공통 청산가치 → 합리적 무거래(호가장이 99/101로 영구 대치) / 불확실 V+사적 신호 → 가격발견(|종가−V| 1.89 ≈ 5신호 평균 최적치, corr 0.977). 일괄 경매는 CDA의 상방 편향을 제거하지만 이탈 크기는 못 줄인다.

**인지 능력이 '집계의 질'을 결정한다** (매 틱 로컬 LLM, 같은 신호 설계):
구조화 출력으로 형식 축을 제거한 능력 사다리 — llama3.1:8b(|종가−V| 14.2) < qwen2.5:7b(10.2) < qwen2.5:14b(4.7) < 프런티어 설계 정책(1.9). 7~8B 시장은 개별 신호보다 나쁘게 집계(정보 파괴), 14B는 자기 신호 수준, 프런티어 설계만 집계 이득 달성.

**행동 인터페이스는 제3의 축이다**: 큰 모델일수록 장황한 숙고로 엄격한 형식에서 이탈하고(qwen14 기권 51%), JSON 스키마 강제는 기권을 0으로 만들되 활동량을 3~5배 올린다 — 출력 형식 선택 자체가 처치이므로 고정·보고해야 한다. 소형 모델은 프롬프트의 위험한도도 모델 의존적으로만 준수한다(llama 위반 52%).

상세: [experiments/claude-pilot/RESULTS-100.md](experiments/claude-pilot/RESULTS-100.md)(세 정보 체제), [RESULTS-LOCAL.md](experiments/claude-pilot/RESULTS-LOCAL.md)(로컬 LLM 전 계열), [baseline/RESULTS.md](experiments/baseline/RESULTS.md)(기준선).

## 실행

```bash
python3 -m unittest discover -s marketlab/tests -t .
```

엔진·테스트는 의존성 없음(Python 3.9+). 로컬 LLM 실험은 [Ollama](https://ollama.com) + `qwen2.5:7b`·`llama3.1:8b`·`qwen2.5:14b`, NetLogo 실측·교차 검증은 [NetLogo 7.0.4 릴리스](https://github.com/NetLogo/NetLogo/releases/tag/v7.0.4)가 필요하다. 각 실험 폴더의 RESULTS 문서에 재현 명령이 있다.

## 상태와 다음 단계

로드맵 M0~M5 완료(2026-10-22) + 클론·로컬 LLM 실험 계열 완료(2026-10-23/24). 남은 큰 축: 프런티어 모델의 매 틱 판단 대조(API 승인 필요), 지평 확장·규모 실험, 실제 시장 자료와의 스타일라이즈드 팩트 대조(미결 가정 B).

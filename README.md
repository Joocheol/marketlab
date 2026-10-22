# marketlab

이질적 LLM 에이전트들이 거래하는 주식시장을 연구하기 위한 이벤트 소싱 시장 시뮬레이션 엔진.
*An event-sourced market engine for heterogeneous LLM-agent stock market research, cross-validated against NetLogo.*

NetLogo(데스크톱·웹) 소스의 역공학 분석에서 설계 원칙을 도출하고, 그 원칙 위에 독립 엔진을 구현한 뒤, 같은 Gode-Sunder ZI-CDA 시나리오를 NetLogo와 본 엔진에서 돌려 통계적으로 교차 검증했습니다.

## 핵심 설계 원칙

- **상태 변경의 문은 하나**: 모든 변경은 단일 직렬화 지점(엔진)이 계산한 이벤트의 순수 폴드로만 일어난다. 재생(replay)은 매칭 로직 없이 이벤트 로그만 다시 접는다.
- **비결정 원천 3종의 통제**: 엔진 난수는 시드로, 사건 순서는 도착 로그로, LLM 응답은 호출 로그로. 셋이 있으면 어떤 런이든 비트 단위로 재현된다.
- **멱등 주문 키 + epoch 표지 + 원자적 cancel-replace**: 재시도 중복, 리셋 후 좀비 응답, 낡은 스냅샷 기반 이중 노출을 각각 구조적으로 차단.
- **격리 자동화**: 실험 런 = 새 프로세스의 새 엔진. 시드는 마스터에서 해시 파생.
- **관측은 읽기 전용**: 메트릭은 이벤트 로그의 순수 함수, 정보 공개는 InfoPolicy가 걸러 이벤트로 기록.

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `netlogo-analysis-report.md` | NetLogo·Tortoise·Galapagos 역공학 분석 보고서 (구조·실행 의미론·스레드 모델·확장 경계·실측 실험 6건) |
| `engine-design.md` | 엔진 설계안 (모듈 구조, 일괄 경매 명세, 실험 관리자, LLM 어댑터, 로드맵 M0~M5 완료 기록) |
| `marketlab/core/` | 이벤트·상태·엔진·불변식 (CDA/경매 공용) |
| `marketlab/mechanisms/` | 연속 복식 호가(CDA), 일괄 경매(call auction) |
| `marketlab/disclosure/` | 정보 공개 정책 (full book / best quote / trades only) |
| `marketlab/gateway/` | 도착 로그(재현 패키지)와 재생 |
| `marketlab/clock/` | 시간 모델: 동기 라운드, 지연 주입, 비동기 수집 라운드 |
| `marketlab/agents/` | ZI-C(Gode-Sunder)·규칙 기반·LLM 에이전트 |
| `marketlab/llm/` | LLM 어댑터 3모드(live/replay/cache)·호출 로그·예산 가드·모의 LLM |
| `marketlab/lab/` | 실험 관리자(선언적 설정·프로세스 병렬·시드 파생)·반사실 실행기 |
| `marketlab/tests/` | 테스트 38개 (속성·전수 대조·재생 결정론·교차 검증 지원) |
| `experiments/` | NetLogo 실측 실험(재현성·동기 경계·폴링·오염), 스파이크, NetLogo 교차 검증 |

## 실행

```bash
python3 -m unittest discover -s marketlab/tests -t .
```

의존성 없음(Python 3.9+ 표준 라이브러리만). NetLogo 실측·교차 검증 실험(`experiments/`)을 재현하려면 [NetLogo 7.0.4 릴리스](https://github.com/NetLogo/NetLogo/releases/tag/v7.0.4)를 내려받아 `downloads/netlogo-7.0.4`에 두면 됩니다.

## 교차 검증 결과 요약

같은 ZI-CDA 시나리오, NetLogo 7.0.4 vs marketlab 각 100런:

| 지표 | NetLogo | marketlab | Welch t |
|---|---|---|---|
| 배분 효율 | 0.9566 | 0.9564 | 0.06 |
| 평균 체결가 | 99.72 | 100.41 | −0.97 |
| 체결 수 | 10.01 | 10.07 | −0.62 |
| 런 내 가격 표준편차 | 17.04 | 17.23 | −0.35 |

## 상태

로드맵 M0~M5 완료(2026-10-22). 남은 것: 실제 LLM API 라이브 파일럿(현재는 승인 전 차단 게이트), 규모 실험·성능 프로파일. 자세한 근거와 미결 연구 가정은 두 문서를 참조.

# NetLogo 역공학 분석 보고서
## — 이질적 LLM 에이전트 주식시장 모형 연구를 위한 기반 조사 —

작성일: 2026-10-22

---

## 0. 분석 기준과 신뢰성 표기

### 0.1 분석 대상 저장소와 기준 커밋

| 저장소 | 커밋 | 커밋 일자 | 비고 |
|---|---|---|---|
| [NetLogo/NetLogo](https://github.com/NetLogo/NetLogo) | `13a2d8f1d` | 2026-10-20 | `main` 브랜치, v7.0.4 릴리스 이후·v7.1.0-alpha1 + 219커밋 시점 |
| [NetLogo/Tortoise](https://github.com/NetLogo/Tortoise) | `ead9a014f` | 2026-10-20 | `main` 브랜치 (NetLogo Web 컴파일러·엔진) |
| [NetLogo/Galapagos](https://github.com/NetLogo/Galapagos) | `97a9fbf2e` | 2026-10-13 | `main` 브랜치 (NetLogo Web 프런트엔드) |

세 저장소 모두 로컬에 클론하여 분석했습니다(이 세션 폴더의 `repos/` 아래). NetLogo 저장소의 Git 이력은 **2011-05-08부터** 시작하며(총 8,672 커밋), 그 이전(1999~2011)의 CVS/SVN 이력은 이 저장소에 없습니다. 따라서 2011년 이전의 설계 결정은 커밋이 아니라 공개 문헌(특히 Tisue & Wilensky 2004)으로 확인했습니다.

### 0.2 신뢰성 표기 규약

본 보고서의 모든 주장에는 다음 네 등급을 붙입니다.

- **[소스]** — 위 기준 커밋의 소스 코드·테스트에서 직접 확인한 사실. 파일 경로와 행 번호를 병기.
- **[이력/문헌]** — 커밋 메시지, 공식 문서, 개발자가 쓴 논문·FAQ에서 확인한 사실.
- **[추론]** — 위 근거에서 제가 재구성한 해석. 틀릴 수 있음.
- **[미검증]** — 직접 실행·측정해야 확정되는 가설. 13장에 검증 실험으로 정리.

파일 경로는 NetLogo 저장소 루트 기준 상대 경로입니다(예: `netlogo-core/src/main/nvm/Context.java:88`).

---

## 1. 전체 지도: 코드베이스가 어떻게 나뉘어 있고 왜 그런가

### 1.1 한 장짜리 지도

```
┌─────────────────────────────── NetLogo 모노레포 ───────────────────────────────┐
│                                                                                │
│  parser-core/        언어 정의·토크나이저·파서·AST (플랫폼 중립, 데스크톱·웹 공유)   │
│   ├─ parser-jvm/     JVM용 어휘분석기 등 플랫폼 어댑터                            │
│   └─ parser-js/      Scala.js로 JS에 내보내는 어댑터  ───────┐                   │
│                                                            │                   │
│  netlogo-core/       엔진 공통부: agent(세계 상태) · nvm(가상머신) · job(스케줄러) │
│                      · compile/middle(최적화) · generate(바이트코드 생성)         │
│                      · lab(BehaviorSpace) · workspace · api(확장 인터페이스)     │
│                                                            │                   │
│  netlogo-headless/   헤드리스 엔진 조립: compile/back · prim(Scala 프리미티브)    │
│                      · workspace · headless(HeadlessWorkspace 공개 API)         │
│                                                            │                   │
│  netlogo-gui/        데스크톱 앱: app·window(Swing UI) · prim(Java 프리미티브)   │
│                      · compile(자체 백엔드) · render · gl(3D)                    │
│                                                            │                   │
└────────────────────────────────────────────────────────────┼───────────────────┘
                                                             │ parser-js 아티팩트
┌─ Tortoise ──────────────────────────────────────────────── ▼ ──────────────────┐
│  compiler/ (Scala→Scala.js)  NetLogo 코드 → JavaScript 코드 생성                 │
│  engine/   (CoffeeScript)    런타임 전체 재구현: World·Turtle·AgentSet·Updater   │
└────────────────────────────────────────────────────────────┬───────────────────┘
┌─ Galapagos ──────────────────────────────────────────────── ▼ ──────────────────┐
│  Play 앱 + 브라우저 UI: SessionLite 이벤트 루프, 위젯, netlogoweb.org             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

핵심 분리선은 세 개입니다. **[소스]**

1. **언어(파서) ↔ 엔진**: `parser-core`는 토큰화·구문분석·AST까지만 담당하고, 실행 의미는 전혀 모릅니다. 그래서 같은 파서가 JVM 데스크톱 엔진과 JS 웹 엔진 양쪽에 공급됩니다(`build.sbt:470-503` — `parser`가 sbt crossProject로 `parserJVM`/`parserJS` 두 아티팩트를 만듦).
2. **엔진 ↔ UI**: `netlogo-core`+`netlogo-headless`는 화면 없이 완결적으로 실행 가능하고, GUI는 그 위에 이벤트·렌더링을 얹습니다. 다만 뒤에 보듯 이 분리는 사후에 재구축된 것이라 `netlogo-gui`에 프리미티브·컴파일러 백엔드의 **중복 구현**이 남아 있습니다(1.3절).
3. **판단 로직 ↔ 상태 저장소**: 프리미티브(명령)는 `agent/` 패키지의 세계 상태를 조작하는 짧은 코드 조각이고, 상태 자체는 `World`가 소유합니다(4장).

### 1.2 각 구성요소가 하는 일

| 구성요소 | 역할 | 대표 소스 |
|---|---|---|
| `parser-core/core` | 언어 원형: 토큰, AST 노드, 문법(Syntax), 에이전트 종류 | `core/AstNode.scala`, `core/Syntax.scala` |
| `parser-core/parse` | 프런트엔드: 구조 파서, 표현식 파서, 이름 해석, 타입 검사 | `parse/FrontEnd.scala:24-42` |
| `netlogo-core/agent` | 세계 상태: `World`, `Turtle`, `Patch`, `Link`, `AgentSet` | `agent/World.scala` |
| `netlogo-core/nvm` | 가상머신: `Context`(실행 문맥), `Job`, `Activation`(호출 프레임), `Command`/`Reporter` | `nvm/Context.java` |
| `netlogo-core/job` | 스케줄러: `JobManager`, `JobThread`(단일 엔진 스레드) | `job/JobThread.scala` |
| `netlogo-core/compile` | 미들엔드: AST 변환·최적화 | `compile/middle/MiddleEnd.scala` |
| `netlogo-core/generate` | ASM 기반 JVM 바이트코드 생성기(선택적) | `generate/Generator.scala` |
| `netlogo-core/lab` | BehaviorSpace 실험 관리 | `lab/Worker.scala` |
| `netlogo-core/api` + `workspace/ExtensionManager` | 확장(.jar) 로딩·프리미티브 등록 | 6장 |
| `netlogo-headless` | 위를 조립한 헤드리스 배포본 + 임베딩용 `HeadlessWorkspace` | `headless/HeadlessWorkspace.scala` |
| `netlogo-gui` | Swing 데스크톱 앱(+자체 prim/compile 사본) | `window/GUIWorkspace.scala` |
| Tortoise `compiler/` | NetLogo→JS 컴파일러(Scala, Scala.js로 브라우저에서도 구동) | 7장 |
| Tortoise `engine/` | JS 런타임(CoffeeScript) — 데스크톱 엔진의 **재구현** | 7장 |
| Galapagos | NetLogo Web UI·사이트 | 7장 |

### 1.3 왜 이렇게 나뉘었나 — 이력이 말해주는 것

- **[이력/문헌]** 2004년 시점의 NetLogo는 "통합 환경"을 명시적 설계 철학으로 삼았습니다. Tisue & Wilensky(2004)는 언어·컴파일러·인터프리터·UI·BehaviorSpace를 한 몸으로 묶는 "integrated approach"가 "low threshold"(초심자 진입 장벽 최소화) 목표에 필수적이라고 썼고, 동시에 "all-in-one이 all-or-nothing이 되는 함정"을 피하려고 확장 API를 두었다고 밝힙니다(논문 §3.3, §5).
- **[이력]** 2016-02-22 커밋 `9e32be023`("Add code for parser, headless, add netlogo-core")과 `633b3c357`("Isolate NetLogo-GUI into one project in preparation for adding parser")에서 현재의 모노레포 구조가 만들어졌습니다. 그 전까지 별도 저장소에서 개발되던 **헤드리스 엔진 재작성본**(개발 코드명 `hexy` 브랜치 흔적: `ea2e3188c` "hexy -> main in versions file" 등)과 파서가 본 저장소로 합쳐진 것입니다.
- **[추론]** 이 재구조화의 동인은 NetLogo Web이었다고 판단합니다. 웹 컴파일러(Tortoise)가 데스크톱과 같은 파서를 써야 하므로 파서를 플랫폼 중립(`parser-core`)으로 뽑아내야 했고, 그 과정에서 헤드리스 엔진이 Scala로 재작성되었습니다. 근거: Tortoise 빌드가 `parser-js` 아티팩트에 직접 의존하고(7장), 헤드리스 쪽 프리미티브는 Scala(`netlogo-headless/src/main/prim/_ask.scala`), GUI 쪽은 옛 Java 구현(`netlogo-gui/src/main/prim/_ask.java`)으로 남아 있습니다.
- **[소스]** 그 결과 오늘날에도 **프리미티브가 두 벌**입니다: headless 쪽 126개 파일(Scala), GUI 쪽 143개 파일(Java). 별도 조사에서 두 사본을 diff한 결과 의미 차이는 거의 없고(`_carefully`의 스코프 처리 한 곳 제외) 표기 차이뿐이었습니다. 이는 "엔진을 공유하되 완전히 통합하지는 못한" 중간 상태로, 대규모 리팩터링이 얼마나 오래 꼬리를 남기는지 보여주는 사례입니다.

**내 연구에의 함의**: 파서/엔진/UI 분리는 그대로 배울 가치가 있습니다. 반면 "같은 의미론의 구현 두 벌 유지"는 피해야 할 비용입니다. 시장 엔진을 만든다면 처음부터 *하나의* 헤드리스 코어에 UI·분석을 클라이언트로 붙이는 편이 NetLogo가 사후에 도달하려 한 구조를 선취하는 것입니다.

---

## 2. 대표 실행 한 번을 끝까지 따라가기

시나리오: 사용자가 커맨드 센터에 `ask turtles [ fd 1 ] tick`을 입력했다고 합시다. (버튼 클릭도 같은 경로를 탑니다. 차이는 JobOwner가 버튼 위젯이라는 것뿐입니다.)

### 2.1 입력 → 컴파일

1. **진입점** — `Evaluator.evaluateCommands`(`netlogo-headless/src/main/workspace/Evaluator.scala:15-24`)가 소스 문자열을 받아 ① 컴파일하고 ② `JobManager`에 잡을 제출합니다. **[소스]** 주석이 설계 규칙을 명시합니다: *"Submitting jobs through the job manager is supposed to be the only way that NetLogo code is ever run"*(같은 파일 92-98행, 112-113행). 즉 **"엔진에 들어가는 문은 하나"**가 NetLogo의 제1 불변식입니다.
2. **프런트엔드(공유 파서)** — `org.nlogo.parse.FrontEnd.frontEnd`(`parser-core/src/main/parse/FrontEnd.scala:24-42`): 토큰화 → 구조 파싱(프로시저 선언) → 표현식 파싱 → `LetVerifier`·`AgentTypeChecker`(이 코드가 터틀용인지 패치용인지 정적 검사) → `ControlFlowVerifier`. 산출물은 플랫폼 중립 AST입니다.
3. **미들엔드** — `FrontMiddleBridge`가 중립 AST를 JVM 엔진용 AST로 변환하고, `MiddleEnd`(`netlogo-core/src/main/compile/middle/MiddleEnd.scala`)가 최적화(상수 접기, `with` 융합 등 `compile/middle/optimize/`)를 수행합니다.
4. **백엔드** — `BackEnd.backEnd`(`netlogo-headless/src/main/compile/back/BackEnd.scala:12-34`): `ArgumentStuffer`가 인자 배열을 채우고, `Assembler`가 **트리를 명령 배열로 평탄화**하며, 선택적으로 `org.nlogo.generate.Generator`(ASM 사용, `netlogo-core/src/main/generate/Generator.scala`)가 각 프리미티브의 `perform_1` 특수화 메서드를 엮어 **JVM 바이트코드를 직접 생성**합니다. 산출물은 `Procedure`(그 안의 `code: Array[Command]`)입니다.
   - **[이력/문헌]** 2004년 논문은 당시 인터프리터의 성능 한계를 논하며 "NetLogo 코드를 Java 바이트코드로 컴파일하는 것이 가장 유망, 비공식 테스트로 2배 이상 개선 예상"이라고 썼고(§Future work), 이후 실제로 그렇게 구현되었습니다. 4.1 FAQ도 "컴파일러가 Java 바이트코드를 생성하되 전체 언어를 지원하지는 않아 일부는 해석 실행"이라고 확인합니다.

### 2.2 잡 제출 → 엔진 스레드 실행

5. **잡 생성** — 커맨드 센터 입력은 `ConcurrentJob`으로 만들어져 `jobManager.addJob(..., waitForCompletion)`으로 제출됩니다(`Evaluator.scala:21-23`). 실행은 **GUI 이벤트 스레드가 아니라 전용 엔진 스레드(JobThread)에서** 일어납니다(5장).
6. **`ask`의 실행** — 컴파일된 코드에서 `_ask.perform`(`netlogo-headless/src/main/prim/_ask.scala:20-50`)이 호출되면:
   - 인자(에이전트셋)를 평가하고, 관찰자가 아닌 에이전트가 `turtles` 전체를 ask하는 것을 금지하는 검사를 한 뒤,
   - `context.runExclusiveJob(agents, next)`로 **자식 ExclusiveJob을 만들어 그 자리에서 끝까지 실행**합니다(`nvm/Context.java:154-168`).
7. **에이전트 순회** — `ExclusiveJob.run`(`nvm/ExclusiveJob.scala:19-56`):
   ```scala
   val it = agentset.shufflerator(random)   // 난수로 섞은 '복사본' 반복자
   while (it.hasNext) {
     context.agent = it.next()
     ...
     context.runExclusive()                 // 이 에이전트가 블록 전체를 끝까지 실행
   }
   ```
   - 복사본이므로 순회 중 `hatch`로 태어난 터틀은 이번 ask에 포함되지 않습니다(19-24행 주석이 이를 명시). **[소스]**
   - `Context.runExclusive`(`nvm/Context.java:114-135`)는 `activation.code[ip]`를 하나씩 `perform`하는 단순 루프입니다. `fd 1`은 `_fd`→`_fdinternal`이 터틀 좌표를 갱신합니다.
8. **`tick`** — `_tick.perform`(`netlogo-headless/src/main/prim/etc/_tick.scala`) → `workspace.tick`(`netlogo-headless/src/main/workspace/AbstractWorkspace.scala:119-128`): 틱 카운터 미시작이면 오류, 아니면 `tickCounter.tick()` → 플롯 갱신 → `requestDisplayUpdate(true)`.

### 2.3 화면 갱신

9. **뷰 갱신(GUI)** — `GUIWorkspace.requestDisplayUpdate`(`netlogo-gui/src/main/window/GUIWorkspace.scala:634-645`). 주석이 규칙을 요약합니다: tick-기반 갱신에서는 `_tick`·`_display`가 강제 갱신을 요청하고, 연속(continuous) 모드에서는 엔진이 주기적으로 "숨을 쉬는"(`breathe`, 608-620행) 지점에서 갱신합니다. `breathe`는 `switches = true`인 명령 뒤에서만 호출되며(아래 3.2절의 '턴' 경계와 같은 지점), 보조 잡 실행·일시정지도 여기서 처리됩니다. 렌더링 자체는 이벤트 스레드가 세계 락을 잡고 수행합니다(5장).

### 2.4 이 경로에서 읽어야 할 설계 원리

- **컴파일 단계 분리(프런트/미들/백)**: 프런트엔드는 공유 자산, 백엔드는 실행기마다 교체. 덕분에 같은 언어가 JVM 엔진·JS 엔진 두 곳에서 돌아갑니다. — *배울 것*.
- **"엔진에 들어가는 문은 하나"(JobManager)**: UI·플롯·모니터·확장 등 코드 실행을 원하는 모든 주체가 잡 제출로 수렴. 슬라이더 경계값처럼 이 규칙을 어긴 코드에는 개발자들이 직접 "beware" 경고를 남겨 두었고 실제 데드락 사례를 언급합니다(`Evaluator.scala:88-98`). — *배울 것*.
- **컴파일 결과는 불변, 상태는 Context/World에**: `Procedure`는 재사용되는 순수 코드이고, 어떤 에이전트가 어디까지 실행했는지는 전부 `Context`(ip, activation)에 있습니다. 실행 중단·재개·동시 잡이 가능한 이유입니다. — *배울 것*.

---

## 3. 실행 의미론: ask, ask-concurrent, tick, 난수

### 3.1 `ask` — 순차 실행이 공식 의미론이다

**[소스]** 위 2.2절의 코드가 보여주듯 `ask`는:

1. 에이전트셋의 **난수 셔플 복사본**을 만들고(`shufflerator`),
2. 에이전트 하나가 블록 **전체를 끝까지** 실행한 뒤 다음 에이전트로 넘어갑니다(run-to-completion).

따라서 **뒤 순번 에이전트는 앞 순번 에이전트가 바꿔 놓은 세계를 봅니다.** 이것은 버그가 아니라 보장된 의미론입니다. 공유 상태에 대한 경합은 "매번 다른 난수 순서"로 공평성을 확보할 뿐, 동시성은 없습니다.

- 순서의 난수성: 5.3.1 프로그래밍 가이드 — "agentset은 항상 난수 순서이며, 쓸 때마다 다른 순서다. 누구도 항상 먼저 가지 못하게 하기 위함" **[이력/문헌]**
- 셔플 순서는 (시드, id 정렬된 구성원) 의 결정적 함수입니다. `TreeAgentSet`이 id 순서 TreeMap을 쓰는 이유가 "넣은 순서와 무관하게 같은 순서로 나오게"라고 주석에 명시 — export/import 재현성 때문(`agent/TreeAgentSet.scala:13-23`). **[소스]**

### 3.2 `ask-concurrent` — '동시성'이 아니라 결정적 턴테이킹

**[소스]** `_askconcurrent`(`netlogo-headless/src/main/prim/_askconcurrent.scala:17-36`)는 `ConcurrentJob`을 만들어 잡 큐에 넣습니다. `ConcurrentJob.step`(`nvm/ConcurrentJob.scala:52-85`)은 에이전트별 `Context` 배열을 돌면서 각 컨텍스트를 `stepConcurrent`로 **한 '턴'씩** 전진시킵니다. 턴의 경계는 `Context.stepConcurrent`(`nvm/Context.java:88-111`)의 종료 조건 `while (!command.switches && !finished)`가 정의합니다. 즉 **`switches = true`로 표시된 명령 하나를 실행하고 나면 다음 에이전트로 제어가 넘어갑니다.**

- 어떤 명령이 턴 경계인가: headless 프리미티브 중 77개가 `switches = true`입니다. 변수 대입(`_setturtlevariable` 등), 이동(`_fd1`, `_jump`), 생성(`_hatch`, `_sprout`, `_createturtles`), `_ask` 자신, `_tick` 등 — 대체로 **세계에 보이는 상태 변경**을 일으키는 명령들입니다. **[소스]**
- 이 메커니즘은 스레드가 아니라 단일 스레드 협조적 스케줄링입니다. 2004년 논문이 정확히 이렇게 설명합니다: "각 에이전트가 최소 작업 단위('턴')를 수행한 뒤 결정적 시점에 컨텍스트 스위치… 운영체제의 협조적 멀티태스킹 스케줄러에 가깝다"(§Concurrency). **[이력/문헌]**

**발전 과정이 주는 교훈** **[이력/문헌]**:

- 2004년까지는 이 "시뮬레이션된 병렬"이 **기본** 의미론이었고, 재현성(결정론)이 핵심 설계 목표였습니다(논문 §4.3 "Reproducibility": "시드가 같으면 어떤 컴퓨터에서든 같은 순서로 같은 결과").
- NetLogo 4.0(2007)에서 `ask`가 순차로 바뀌었습니다. 4.1 전환 가이드의 공식 사유: *"사용자들이 시뮬레이션된 동시성 때문에 예상 밖으로 동작하는 모델을 자주 만들었지만, 그로부터 득을 보는 모델은 드물었다."* 옛 동작은 `ask-concurrent`로 격리.
- 2014년 커밋 `6b5ee2f50` "ask-concurrent was only 'concurrent' in a strange and limited sense" 및 `0136b40d0`(문서에서 사용 자제 경고 강화). 현재 7.x 사전은 "하위 호환용으로만 유지, 새 모델에서 쓰지 말 것"이라고 명시하고, 공식 포럼에서는 "더 이상 지원하지 않으며 버그도 고치지 않을 것"이라고 답합니다.

**내 연구에의 함의**: "모든 에이전트가 같은 시점 정보를 보고 판단"하는 시장 모형(동시 호가 후 일괄 체결)과 "순차 갱신 정보를 보는" 모형(도착 순 연속 체결)의 구분은 NetLogo에선 `ask-concurrent` 류의 턴테이킹이 아니라, **"판단 단계와 적용 단계를 명시적으로 분리한 2단계(stage) 패턴"**으로 구현하는 것이 정석입니다(NetLogo 모델들이 흔히 쓰는 수법: 먼저 모두가 의도를 변수에 기록하는 ask, 그다음 일괄 적용하는 ask). NetLogo의 역사는 '암묵적 인터리빙'이 사용자 오류의 온상이었음을 보여줍니다 — 시장 모형에서는 정보 공개 시점을 스케줄러의 암묵 규칙이 아니라 **명시적 모형 가정**으로 두어야 합니다(10장).

### 3.3 `tick` — 시계가 아니라 카운터

**[소스]** `tick`은 `world.tickCounter`를 1 올리고 플롯·화면 갱신을 트리거할 뿐입니다(`AbstractWorkspace.scala:119-128`). 시간 진행과 에이전트 스케줄링 사이에 아무런 내재적 결합이 없습니다. 이산 사건 스케줄러가 필요하면 `time` 확장을 써야 합니다(기본 엔진엔 없음). 화면 갱신 모드(tick-based vs continuous)는 **표시**의 문제이지 의미론의 문제가 아닙니다 — 단, continuous 모드에선 `breathe`가 턴 경계에서 화면을 갱신하므로 사용자가 중간 상태를 봅니다(2.3절).

### 3.4 난수 — 재현성의 실제 구현과 그 한계

**[소스]** (별도 상세 조사로 확인)

- `World`가 RNG를 소유합니다: `mainRNG`(모형 결과에 영향을 주는 모든 것), `auxRNG`(모니터 등 결과에 영향을 없어야 하는 것), 그리고 플롯 전용 `plotRNG`(mainRNG의 클론). `agent/World.scala:56-62`의 주석이 이 구분을 명시합니다.
- 각 `Job`이 `random` 필드로 RNG 참조를 들고 다니며(`nvm/Job.java:28`), 자식 잡은 부모의 RNG를 상속합니다. 버튼·커맨드 센터·BehaviorSpace는 mainRNG, 모니터·슬라이더는 auxRNG 소유자입니다.
- `ask` 순서(shufflerator), `create-turtles`의 색·방향, `one-of` 등이 전부 `context.job.random`에서 나오므로, **mainRNG 시드 + 코드 + (단일 스레드 실행)이 모형 전체를 결정**합니다. 이것이 NetLogo 재현성의 전부이며, 동시에 그 전제조건입니다.
- `with-local-randomness`는 mainRNG 클론으로 블록을 실행해 난수 소비를 격리합니다(`prim/etc/_withlocalrandomness.java:25-32`).
- BehaviorSpace는 측정(metrics) 평가를 mainRNG의 **클론**에서 수행해 "측정이 실행을 교란하지 않게" 합니다(`lab/Worker.scala:185-225`). — *배울 것: 관측은 복제된 난수원에서.*
- `export-world`는 mainRNG의 전체 상태(624워드 메르센 트위스터 상태 포함)를 내보내고 import가 복원하므로, 세계 스냅샷에서 재개해도 난수열이 이어집니다(`agent/Exporter.scala:87-91`, `api/MersenneTwisterFast.java:188-201`). 단 auxRNG·plotRNG는 내보내지 않습니다.
- 한계: 공식 문서 스스로 "같은 난수열은 같은 NetLogo 버전에서만 보장"이라고 명시합니다(5.3.1 프로그래밍 가이드). 버전이 바뀌면 프리미티브의 난수 소비 횟수가 달라질 수 있기 때문입니다. **[이력/문헌]**

**내 연구에의 함의**: 재현성의 단위를 "시드 하나"가 아니라 **"시드 + 엔진 버전 + 사건 순서 로그"**로 잡아야 합니다. LLM이 끼면 LLM 응답 자체가 비결정적이므로, NetLogo가 난수에 대해 한 일(소유자 분리, 상태 export, 관측용 클론)을 **LLM 응답 로그**에 대해 해야 합니다(10장).

---

## 4. 상태 관리: 소유권, 생성·소멸, 초기화, 오류 시 보존되는 것

(이 장의 세부 근거는 별도 심층 조사로 확인한 것입니다. 모두 **[소스]** 등급.)

### 4.1 소유권 구조

- 에이전트 상태 = 비정형 `Object[] _variables` 배열 + `long _id`(`agent/AgentJ.java:7-14`). 터틀은 xcor/ycor/heading을 필드로 중복 캐시(`Turtle.java:64-80`).
- 전역 변수는 **Observer의 변수 배열**에 삽니다(`agent/ObserverManagement.scala:18-39`). World가 Observer·터틀/패치/링크 집합·RNG·틱 카운터·`nextTurtleIndex`를 소유합니다.
- 실행 문맥(어느 에이전트가 어느 명령까지 실행했는가)은 전부 `nvm.Context`/`Activation`에 있고 World는 모릅니다. — *판단 상태와 세계 상태의 분리.*

### 4.2 생성과 소멸 — who 번호는 재활용되지 않는다

- `who`는 단조 증가 카운터에서 발급(`agent/TurtleManagement.scala:84-88`)되고 **런 중 재활용되지 않습니다**. `die`는 객체를 파괴하지 않고 집합들에서 제거한 뒤 `_id = -1`로 표시합니다(`Turtle.java:135-155`).
- 죽은 에이전트를 가리키는 참조는 그대로 남을 수 있고, 프리미티브가 접근 시 "That turtle is dead" 오류를 내거나 `nobody`로 취급합니다. 저장된 `ArrayAgentSet`은 죽은 에이전트를 지연 스킵합니다(`agent/ArrayAgentSet.scala:206-259`).
- *배울 것*: 식별자 불변·비재활용 + "죽음은 표시이지 삭제가 아님" + 모든 접근 지점에서의 사망 검사. 시장 모형의 주문·계좌에도 같은 원칙(취소된 주문 id는 영구 결번, 참조는 안전하게 무효화)이 필요합니다.

### 4.3 `clear-all` — 무엇이 남는가

지워지는 것: 터틀·링크, 코드 선언 전역(기본값으로), 틱(-1, '미시작'), 플롯, 출력, 그림, 확장 상태(단, 각 확장이 `clearAll()`을 구현한 만큼만 — 기본은 no-op, `api/DefaultClassManager.scala:41`).
남는 것: **인터페이스 전역(슬라이더 등)**, **RNG 상태**(시드는 `random-seed`로만 바뀜), 세계 크기·토폴로지.

- *함정*: 확장이 들고 있는 외부 자원(소켓, 프로세스)은 확장이 스스로 치우지 않으면 `clear-all` 후에도 살아 있습니다. LLM 연동처럼 외부 상태가 큰 시스템에서 "초기화의 경계"를 엔진이 강제할 수 없다는 뜻입니다.

### 4.4 `carefully` — 오류는 잡지만 롤백은 없다

`_carefully`(`netlogo-headless/src/main/prim/_carefully.scala:18-32`)가 복원하는 것은 **let 변수 스코프뿐**입니다. 세계 상태 스냅샷·롤백 메커니즘은 엔진 어디에도 없습니다. 언어 테스트가 이를 명문화합니다(`test/commands/Errors.txt:5-7`):

```
O> carefully [ crt 2 crt __boom crt 1 ] [ crt 5 ]
count turtles => 7     ;; 오류 전에 만든 2마리가 살아남고, 핸들러가 5마리 추가
```

런타임 오류로 잡이 죽을 때도 마찬가지로 **부분 갱신된 세계가 그대로 남습니다**(`ConcurrentJob.scala:72-82` → `JobThread.scala:133-141`: 오류를 잡 결과에 저장하고 해당 소유자의 잡들을 종료할 뿐). `halt`도 잡만 멈추고 상태는 중단 시점 그대로입니다.

- *함의*: NetLogo는 "오류 = 실험 폐기 후 setup부터 재시작"이라는 사용 관행 위에 서 있습니다. 교육·탐색용으로는 충분하지만, **회계 일관성이 요구되는 시장 모형에는 부족**합니다. 주문 접수→체결→계좌 반영이 중간에 끊겨도 불변식(현금+보유주식 가치 보존, 주문-체결 대응)이 깨지지 않으려면 트랜잭션적 적용(모아서 원자적으로 반영) 또는 이벤트 소싱(장부는 체결 이벤트의 순수 함수)이 필요합니다(10장).

### 4.5 스냅샷: export-world / import-world

내보내는 것: mainRNG 전체 상태, 전역(틱·`nextTurtleIndex` 포함), 터틀·패치·링크(id 순), 그림, 출력, 플롯, 확장별 섹션(확장이 구현한 만큼). auxRNG·plotRNG는 제외. import는 먼저 `clearAll()` 후 복원하며, 실패 시 **빈 세계**가 남습니다(`agent/ImporterJ.java:125-176`).

- *배울 것*: "세계 = CSV 한 장"이라는 단순한 전체 직렬화는 재현·디버깅·회귀 테스트(체크섬)의 기반입니다. NetLogo의 언어 회귀 테스트와 모델 체크섬 테스트가 이 위에 서 있습니다.
- *경계*: 확장 상태는 계약상 "확장 책임"입니다. 전체 상태의 일부가 엔진 밖에 있으면 스냅샷의 완전성은 협약으로만 보장됩니다.

---

## 5. 스레드 모델과 세 가지 병렬성

귀하가 요구하신 대로 세 층위 — ① 독립 실험의 병렬 실행, ② 한 세계 내부의 병렬 계산, ③ 외부 요청의 동시 처리 — 를 구별해서 정리합니다. (이 장의 세부 근거는 잡 스케줄러·BehaviorSpace 심층 조사로 확인. 모두 **[소스]**, 별도 표기 시 제외.)

### 5.1 워크스페이스 하나 = 엔진 스레드 하나, 락은 World 자체

- `JobManager` 생성자가 곧바로 전용 `JobThread`를 만듭니다(`job/JobManager.scala:13-16`). 워크스페이스는 `(this, world, world)`로 매니저를 만드는데 **세 번째 인자(락)가 World 객체 자신**입니다(`netlogo-headless/src/main/workspace/AbstractWorkspace.scala:590-596`).
- 실행 루프(`job/JobThread.scala:64-79`)는 primary 잡들을 라운드로빈으로 돌며, 각 `job.step()`을 `lock.synchronized { ... }` 즉 **World 모니터를 쥔 채** 수행합니다(133행). 잡이 없으면 최대 200ms 대기.
- GUI(이벤트 스레드)는 뷰를 그릴 때 `synchronized(workspace.world())`로 같은 락을 잡습니다(`window/View.java:170,242,285`). 즉 **"World 락을 쥔 자만 세계를 읽고 쓴다"**가 데스크톱의 동시성 규율 전부입니다.
- 엔진 스레드가 이벤트 스레드에 일을 시킬 때는 `ThreadUtils.waitFor`가 **World 락을 `world.wait(50)` 루프로 내려놓고** 기다립니다 — 주석: "이벤트 스레드를 데드락 없이 기다리려면 wait()로 World 락을 양보해야 한다"(`window/ThreadUtils.scala:39-80`).
- 버튼 여러 개가 눌리면 `activeButton`과 `buttonTurnIsOver` 플래그로 **포에버 버튼은 '루프 1회전' 단위로 교대**합니다(`JobThread.scala:123-145`, `prim/etc/_foreverbuttonend.java`). 모니터는 secondary 잡으로 분리되어 스로틀링됩니다.
- 중단(halt)은 전부 협조적입니다: `jobManager.interrupt()` + 10ms마다 `comeUpForAir` 플래그를 세우는 "Lifeguard" 스레드(`GUIWorkspace.scala:90-117`) + 명령과 명령 사이에서만 검사(`Context.java:302-312`). **명령 하나가 안에서 블로킹하면 halt도 멈춥니다**(6장).

### 5.2 ① 독립 실험의 병렬 실행 — 지원됨, 단 함정과 함께

- BehaviorSpace는 고정 스레드풀(`Executors.newFixedThreadPool`, `lab/Worker.scala:47`)을 쓰고, **워크스페이스(=World+JobThread) 풀을 스레드 수만큼 만들어 큐로 돌립니다**(`lab/Lab.scala:25-224`). 실행 단위 격리는 "공유 금지 + 완전 복제"입니다: World, RNG, 컴파일러, 확장 클래스로더까지 런별 워크스페이스 소유.
- 기본 스레드 수는 `floor(cores × 0.75)`(`api/LabDefaultValues.scala:21-23`). 2023년에 병렬이 기본값이 되었습니다(커밋 `e1185fe67`, PR #2160). **[이력]**
- 공유되는 것은 결과 수집기(exporter)뿐이고 `listeners.synchronized`로 직렬화합니다. 테이블 출력은 완료 순서라 뒤섞이고, 스프레드시트는 런 번호로 정렬합니다(`Worker.scala:128-132`, `SpreadsheetExporter.scala:45`).
- **함정 1 — 워크스페이스 재사용**: 풀의 워크스페이스는 런마다 새로 만들지 않고 **재사용**되며 BehaviorSpace가 자동으로 clear하지 않습니다. 공식 문서가 2020년에 이를 명시했습니다(커밋 `25a8bd62b`): 앞 런이 칠한 patch 색이 다음 런에 남을 수 있으니 setup에서 `clear-all` 하라. 재사용 로직의 버그 회귀 테스트도 있습니다(#114, `TestBehaviorSpace.scala:212-227`). **[이력+소스]**
- **함정 2 — 시드 충돌**: 같은 문서 커밋이 "매우 빠른 프로세서에서 병렬 런들이 같은 순간 시작하면 같은 RNG 상태를 가질 가능성"을 경고하고 `random-seed new-seed`를 권합니다. 기본 시드가 시각 기반이기 때문입니다(`MersenneTwisterFast.java:238-240`은 `System.nanoTime()`). **[이력+소스]**
- **함정 3(추정)**: 1코어 환경에서 기본값이 `floor(0.75)=0`이 되는데 하한 보정이 보이지 않습니다(`LabDefaultValues.scala`). **[추론/미검증]**
- GUI에서는 BehaviorSpace를 **별도 JVM 프로세스**(`bsapp.BehaviorSpaceApp`)로 띄워 소켓 IPC로 통신합니다(`lab/gui/Supervisor.scala:88-166`) — UI와 실험의 자원 격리.
- 병렬 실행의 결정론은 테스트로 뒷받침됩니다(`TestGasLabInParallel.scala`: 10스레드에서 같은 결과 기대). 다만 체크섬 리포트 도구는 "병렬로는 왜인지 제대로 안 된다"는 2025년 주석이 남아 있습니다(`ChecksumReport.scala:12-14`) — 병렬 안전성이 '거의' 확보된 상태임을 보여주는 정직한 흔적. **[소스]**

### 5.3 ② 한 세계 내부의 병렬 계산 — 없음

`netlogo-core`/`netlogo-headless`/`parser-core` 전체에서 스레드 생성 지점은 JobThread, BehaviorSpace 풀, HubNet 네트워킹, 라이브러리 다운로드뿐입니다. `ask`는 같은 스레드에서 순차 실행, `ask-concurrent`도 같은 스레드의 턴테이킹입니다. **한 World 안의 에이전트 계산을 여러 코어로 나누는 메커니즘은 존재하지 않습니다.** 성능 한계의 '측정'은 하지 않았으므로(12장), 여기서 말할 수 있는 것은 구조적 사실뿐입니다: 한 세계의 처리량 상한은 단일 코어 성능이고, NetLogo의 결정론(3.4)은 바로 이 단일 스레드 직렬화에 기대고 있습니다.

### 5.4 ③ 외부 요청의 동시 처리 — 엔진은 모른다

엔진에 외부 이벤트 큐는 없습니다. 외부 세계가 엔진에 접근하는 경로는 두 가지뿐입니다(6장에서 상세):

1. **폴링**: 외부 스레드가 큐에 쌓고, 모형 코드가 프리미티브로 꺼내 감(HubNet 패턴).
2. **잡 제출**: 외부 스레드가 컴파일된 명령을 잡으로 제출(내부 API, CommandServer·LevelSpace 패턴).

둘 다 "엔진은 단일 스레드 결정론을 지키고, 동시성은 전부 경계 밖에서 처리하라"는 같은 원칙의 표현입니다.

---

## 6. 확장 경계: 엔진이 보장하는 것과 확장 개발자가 책임지는 것

(이 장의 세부 근거는 확장 API 심층 조사로 확인. 모두 **[소스]**, 별도 표기 시 제외.)

### 6.1 계약의 실체

- 확장 프리미티브는 `api.Command.perform(args, context)` / `api.Reporter.report(args, context)` 하나짜리 동기 호출입니다(`api/Command.scala:23-24`). 컴파일 시 `_extern`/`_externreport`로 감싸져(`compile/Backifier.scala:142-143`) **엔진 스레드에서, World 락을 쥔 채** 실행됩니다.
- `api.Context`가 노출하는 것: 현재 에이전트, world, RNG(`getRNG` = 그 잡의 RNG), 작업 디렉터리, workspace. **스케줄링·콜백·이벤트·타임아웃·취소 API는 없습니다.**
- 수명주기: `runOnce`(인스턴스당 1회) → `load`(모델 컴파일마다) → `unload`(모델 교체·종료·재컴파일 탈락 시). `clear-all`은 `classManager.clearAll()`만 부르고 **unload하지 않습니다** — 소켓·프로세스 같은 외부 자원은 `clear-all`을 살아 넘깁니다. `unload`에서 난 예외는 **조용히 무시**됩니다(`ExtensionManager.scala:131-133`).

### 6.2 엔진이 보장하는 것 / 확장이 책임지는 것

| 엔진이 보장 | 확장이 책임 |
|---|---|
| 프리미티브는 항상 엔진 스레드에서, World 락 하에 호출됨(동시 접근 없음) | 블로킹하지 않기 — 블로킹하면 엔진 전체·뷰·halt가 멈춤 |
| 오류 전파: `ExtensionException` → NetLogo 스택트레이스가 붙은 런타임 오류로 변환(`_extern.java:38-41`) | 늦은 응답·취소·실패·재시도·중복: **전부 확장 몫** (엔진에 해당 개념 없음) |
| halt 신호: 스레드 interrupt + 명령 사이 `comeUpForAir` 검사 | interrupt를 감지해 `HaltException`으로 바꾸는 일(안 하면 halt가 영원히 기다림) |
| 수명주기 훅 호출(runOnce/load/unload/clearAll/import/export) | 외부 자원 정리, clear-all 시 내부 상태 리셋 여부 결정, export/import 직렬화 구현 |

### 6.3 비동기 작업의 실존 패턴 세 가지

엔진이 비동기를 모르기 때문에, 저장소 안의 실제 코드들은 세 가지 우회로를 씁니다.

1. **폴링 큐(HubNet)**: 접속 스레드들이 `LinkedBlockingQueue`에 메시지를 넣고, 모형이 `hubnet-message-waiting?` / `hubnet-fetch-message`로 꺼냅니다(`hubnet/server/HubNetManager.scala:40-79`). 오래 기다려야 할 때는 `workspace.world.synchronized { world.wait(25) }` 루프로 **World 락을 주기적으로 양보**하면서 기다립니다(241-265행) — 저장소에서 유일하게 타임아웃 의미론을 가진 프리미티브이기도 합니다.
2. **락 양보 대기(LevelSpace의 `UnlockAndBlock`)**: 작업을 다른 스레드의 Future로 보내고, 엔진 스레드는 `unlock.synchronized { unlock.wait(0,1) }` 루프(unlock = World)로 기다리며 interrupt를 `HaltException`으로 변환합니다(`extensions/ls/src/main/UnlockAndBlock.scala:21-44`). — 외부 호출 중에도 뷰가 그려지고 halt가 먹히게 하는 레시피.
3. **잡 제출(CommandServer·LevelSpace)**: 외부 스레드가 코드를 컴파일해 `jobManager.addJob(..., waitForCompletion=false)`로 밀어 넣습니다(`app/common/CommandServer.scala:150-152`는 소켓→이벤트 스레드→잡 스레드로 홉; `extensions/ls/src/main/Evaluator.scala:113-114`). 단 이는 안정 API가 아니라 `nvm` 내부에 캐스팅해 들어가는 준내부 경로입니다.

**[추론]** 이 세 패턴의 공통점: **외부 비동기성이 엔진의 결정론을 뚫고 들어오지 못하게, '엔진이 꺼내 가는' 구조로 뒤집는 것**입니다. 외부가 임의 시점에 세계를 바꾸는 경로는 없습니다. LLM 연동 시장 모형에서 그대로 번역하면 — "LLM 응답이 도착하는 순간 체결하는" 설계가 아니라, "체결 엔진이 자기 시간표에 따라 도착한 주문을 꺼내 가는" 설계가 NetLogo적 정답입니다.

### 6.4 취소·중복·좀비 응답에 대해 엔진이 주는 답: 없음

- 실행 중 프리미티브에 대한 타임아웃·취소 훅은 없습니다. 유일한 신호는 Java thread interrupt이고, 인터럽트 불가능한 I/O에 박히면 halt 다이얼로그가 영원히 돕니다. **[소스+추론]**
- 초기화(모델 교체) 때는 `haltPrimary()` 후 `reset()`(전 확장 unload)이 돌지만, 블로킹된 프리미티브가 있으면 모델 열기 자체가 막힙니다.
- 재시도·중복 처리 개념은 API 어디에도 없습니다. NetLogo가 이 문제를 풀지 않은 것은 설계 태만이 아니라 **동기 세계관에서는 문제가 성립하지 않기 때문**입니다. 즉, 귀하의 모형이 비동기 LLM을 쓰는 순간, NetLogo에서 '배워 올' 답이 없는 첫 번째 영역이 바로 여기입니다(10장 4번).

---

## 7. 웹과 데스크톱: 무엇을 공유하고 무엇을 다시 만들었나

(이 장의 세부 근거는 Tortoise/Galapagos 심층 조사로 확인. 모두 **[소스]**, 별도 표기 시 제외. 주의: Galapagos는 Tortoise HEAD가 아니라 발행 아티팩트 `1.0-6168dd2`에 고정되어 있는데, 이는 Tortoise HEAD 바로 1커밋 전이라 사실상 동기 상태입니다.)

### 7.1 공유되는 것은 '언어', 다시 만든 것은 '세계'

- **공유**: 파서 프런트엔드 전체. 데스크톱 저장소의 `parser-core`가 sbt crossProject로 `parser-js`(Scala.js) 아티팩트로 발행되고, Tortoise 컴파일러가 이를 그대로 의존합니다(`Tortoise/build.sbt:7,113`; `Compiler.scala:18,59`가 `org.nlogo.parse.FrontEnd`를 직접 호출). 토큰·AST·Syntax·프리미티브 '선언'까지 한 벌입니다.
- **재구현**: 백엔드(AST→JS 문자열 생성: `Handlers`/`Prims`/`SimplePrims`)와 **런타임 전체**(CoffeeScript: `engine/core/world.coffee`, `turtle.coffee`, agentset, 토폴로지, prim, 플롯). 데스크톱 JVM 엔진 코드는 한 줄도 브라우저로 가지 않습니다.
- **비트 호환 난수**: 메르센 트위스터만은 Scala 원본을 Scala.js로 포팅해 `engine-scala.js`로 번들합니다(`engine/src/main/scala/MersenneTwisterFast.scala`). **[추론]** 데스크톱과 난수열 비트 호환을 유지해 같은 시드로 같은 결과를 내기 위함 — "의미론의 금본위는 난수"라는 방증.
- 컴파일러 자체가 Scala.js로 브라우저에서 돌므로(`BrowserCompiler.scala:34` `@JSExportTopLevel`), netlogoweb.org는 서버 없이 클라이언트에서 컴파일·실행까지 끝냅니다.

### 7.2 실행 모델: requestAnimationFrame 협조 루프

Galapagos의 `SessionLite.eventLoop`(`beak/session-lite.coffee:166-206`)가 데스크톱 JobThread의 역할을 합니다: 프레임마다 ①속도 슬라이더로 계산한 횟수만큼, 100ms 예산 안에서 포에버 버튼들을 **동기 호출**로 돌리고 ② `Updater`에 쌓인 변경분(dirty-variable diff)을 걷어 뷰를 다시 그립니다. 엔진은 뷰에 푸시하지 않고 **뷰가 당겨 갑니다**(`engine/updater.coffee:52-55`의 `collectUpdates()`).

- JS 단일 스레드이고 Web Worker를 쓰지 않으므로(grep으로 부재 확인), **`go` 한 번이 길면 탭이 얼고, 무한 루프는 중단 불가**입니다. 공식 차이 문서가 명시합니다: "브라우저에는 모든 것을 위한 스레드가 하나뿐…`display` 같은 프리미티브는 기대대로 동작할 수 없다"(`app/views/differences.scala.html:48-52`).

### 7.3 비동기 경계: 콜백 연속 전달(CPS), 그리고 그 대가

- 비동기가 필요한 프리미티브는 **마지막 인자로 NetLogo 익명 커맨드(콜백)를 받고 즉시 반환**합니다: `fetch:url-async url [ resp -> ... ]`(`extensions/fetch.coffee`). 동기 버전은 아예 금지("not supported in NetLogo Web. Use 'fetch:user-file-async'")하거나, `http-req:get`처럼 **deprecated 동기 XHR**로 때웁니다 — 주석: "NetLogo 모델 코드에는 async 실행 개념이 없으므로 이게 최선"(`extensions/http-req.coffee:20-27`).
- 엔진에 중단·재개(코루틴/제너레이터) 장치가 없으므로 **프리미티브는 엔진을 suspend할 수 없습니다**. 콜백은 나중에, 원래의 ask 문맥·버튼 오류 처리 바깥에서 실행됩니다. `import-world`가 뒤 코드보다 늦게 실행되는 역전 현상을 공식 문서가 직접 경고합니다(`differences.scala.html:40-44`). `wait`는 2021년에 아예 no-op으로 바뀌었습니다(커밋 `710bd9af`: "현재 런타임에서 wait는 아무 일도 일어나게 할 수 없고 락업까지 유발하므로 기다리지 않는다"). **[이력]**
- 별도 잡 개념도 없습니다 — 언어 테스트 면제 목록에 "NetLogo Web does not support distinct jobs"가 명시(`TortoiseFinder.scala:141`).

### 7.4 미지원 기능과 그 이유

공식 목록(`differences.scala.html:19-35`): HubNet, 파일 프리미티브, `ask-concurrent`/`without-interruption`, `display`/`no-display`, `inspect`, 다수 확장, 3D, BehaviorSpace(브라우저엔 간이 BabyBehaviorSpace만, 동기 실행), Shapes Editor, 시스템 다이내믹스. 컴파일러 소스와 대조하면 미참조 프리미티브가 "unimplemented primitive" 오류를 내는 구조입니다(`Prims.scala:312-313`). 이유는 세 갈래로 정리됩니다:

1. **브라우저 샌드박스**(파일 I/O, 디렉터리) — 대체 프리미티브(`*-from-string`, fetch)로 우회.
2. **단일 스레드 + suspend 불가**(`wait`, `display`, `every`의 잡 의미론, `ask-concurrent`) — 구조적 비호환.
3. **JVM 부재**(Python·R 연동, LevelSpace 등 JVM 확장) — 웹 확장은 빌드 시점에 고정된 CoffeeScript 모듈 집합(`ExtDefReader` 매크로가 JSON 스펙을 컴파일러에 인라인).

**교훈**: "오래된 플랫폼이니 비동기도 잘 풀었겠지"라는 가정은 사실과 반대입니다. **동기·결정론 엔진에 비동기를 뒤늦게 접붙인 결과가 NetLogo Web의 가장 약한 부분**이고, 그 균열(콜백의 문맥 이탈, 실행 순서 역전, 동기 XHR 땜질)은 귀하의 모형이 처음부터 비동기를 1급 개념으로 설계해야 할 이유를 보여줍니다.

---

## 8. 발전 과정에서 배우는 것: 사례와 언어 선택

### 8.1 구조 변경 사례 모음

| 시기 | 사건 | 교훈 |
|---|---|---|
| ~2004 | "시뮬레이션된 병렬"이 기본 의미론. 결정론·재현성이 명시적 설계 목표(Tisue & Wilensky 2004 §4.3) | 재현성은 처음부터 1급 목표였다 |
| 2007 (4.0) | `ask` 순차화, `without-interruption` 사실상 폐기, 옛 동작은 `ask-concurrent`로 격리. 공식 사유: "사용자가 동시성 때문에 틀린 모델을 자주 만들었고 득 보는 모델은 드물었다"(4.1 전환 가이드) | **암묵적 인터리빙은 사용자 오류의 온상** — 의미론은 단순하게, 동시성은 명시적으로 |
| 2014 | 커밋 `6b5ee2f50` "ask-concurrent was only 'concurrent' in a strange and limited sense" — 문서에서 강하게 비권장 | 잘못 이해되는 기능은 이름부터 바꾸거나 숨겨라 |
| ~2014-16 | 헤드리스 엔진 Scala 재작성(`hexy`) 후 2016-02 모노레포 통합(`9e32be023`, `633b3c357`). GUI에는 옛 Java 프리미티브가 지금도 병존 | UI와 엉킨 엔진의 분리는 사후에는 수년짜리 작업이고 끝내 완전해지지 않는다 |
| 2020 | BehaviorSpace 병렬 함정 문서화(`25a8bd62b`: 워크스페이스 재사용 비초기화, 시드 충돌) | 병렬 실험에서 '런 간 격리'와 '시드 관리'는 명시적 계약이어야 한다 |
| 2021 | 웹 `wait` no-op화(`710bd9af`) | 동기 의미론을 비동기 플랫폼에 이식할 때 깨지는 첫 번째가 시간 프리미티브 |
| 2023 | BehaviorSpace 병렬 실행이 기본값으로(`e1185fe67`, PR #2160) | 독립 복제 병렬화는 성숙하면 기본값이 될 만큼 안전해진다 |
| 2025 | HubNet 디스플레이 데드락 수정(`b02c2b777`): 잡 스레드에서 직접 하던 뷰 갱신을 `EventQueue.invokeLater`로 이벤트 스레드에 위임 | 20년 된 코드베이스에서도 스레드 경계 위반은 계속 데드락을 만든다 — 경계는 적을수록 좋다 |

그 밖에 코드 안의 정직한 주석들이 좋은 사료입니다: 슬라이더 경계값 코드의 "실제로 데드락 난다" 경고(`Evaluator.scala:88-98`), JobThread의 lost-wakeup 방지 주석(`JobThread.scala:70-71`), 체크섬 병렬 실행이 "왜인지 안 된다"는 2025년 주석(`ChecksumReport.scala:12-14`), 워크스페이스 재사용 버그 #114 회귀 테스트(`TestBehaviorSpace.scala:212-227`).

### 8.2 왜 Java, 왜 Scala — 사실과 추정의 구분

**확인된 사실 [이력/문헌]**
- Java 선택(1999~): "모든 주요 플랫폼에서 돌게 하려고 Java로 작성"(2004 논문). 재현성 절은 "Java의 플랫폼 독립적 수학 라이브러리가 일관성 확보를 돕는다"고 덧붙입니다.
- 성능 전략: 인터프리터 → 커스텀 중간표현 → **Java 바이트코드 직접 생성**으로 진화. 2004 논문이 "바이트코드 컴파일이 가장 유망(2배 이상 개선 예상)"이라 예고했고, 4.1 FAQ가 "컴파일러가 Java 바이트코드 생성(전체 언어는 아직 미지원)"으로 확인하며, 현재 소스의 `generate/Generator.scala`(ASM 사용)가 그 구현입니다.
- Scala 도입 시기·범위: 4.1 FAQ는 "대부분 Java, **컴파일러와 BehaviorSpace는 Scala**"라고 썼고, 현재 7.x FAQ는 "대부분 Scala, 일부 Java"입니다. 즉 **컴파일러부터 Scala로 들어와 점진적으로 전체를 잠식**했습니다. 당시 수석 개발자 Seth Tisue의 공개 약력도 "NetLogo의 컴파일러와 도구들을 Scala로 만들었다"고 확인합니다.
- Scala 코드가 Java 바이트코드로 컴파일되어 기존 Java와 완전 상호운용된다는 점을 FAQ가 반복 강조합니다.

**제 추정 [추론]** — 개발팀의 명시적 '왜 Scala' 선언문은 공개 자료에서 찾지 못했습니다. 정황으로 재구성하면: ① JVM 상호운용 덕에 20만 줄 Java 코드베이스를 버리지 않고 파일 단위로 점진 이식 가능했고(2008년 채용 공고가 "Java와 Scala 혼합, Scala 비중을 점차 늘리는 중"이라 기술), ② 컴파일러는 대수적 자료형·패턴 매칭이 결정적으로 유리한 영역이라 첫 투입처로 자연스러웠으며, ③ 결과적으로(의도였는지는 불명) Scala.js의 등장이 파서를 웹과 공유하는 길을 열었습니다. ③이 사후의 행운인지 선견이었는지는 커밋만으로 판별할 수 없습니다.

**귀하의 프로젝트에 주는 시사점 [추론]**: 언어 자체보다 "숙주 플랫폼(JVM)과의 상호운용을 유지한 점진 이식"과 "컴파일러·실험 관리처럼 득이 큰 곳부터"라는 **이행 전략**이 배울 점입니다. LLM 생태계가 Python/TypeScript 중심인 지금, 같은 논리는 "에이전트·LLM 연동부는 그 생태계의 언어로, 체결·회계 코어는 성능과 불변식 검증에 유리한 언어로, 경계는 직렬화된 메시지로"라는 다언어 구성을 지지합니다.

---

## 9. 라이선스와 소스 재사용 가능성

구성요소별로 LICENSE 파일을 직접 확인했습니다. **[소스]**

| 구성요소 | 라이선스 | 재사용 함의 |
|---|---|---|
| NetLogo 본체(파서·엔진·GUI 포함 저장소 전체) | **GPL-2.0 이상**(`LICENSE`; about.txt에 상업 라이선스 병행 안내) | 코드를 가져다 결합하면 파생물도 GPL. 학술 연구·내부 사용은 문제없으나, 비GPL 배포를 원하면 코드 재사용 불가(원리만 차용) |
| Tortoise(웹 컴파일러·엔진) | **GPL-2.0 이상** + 상업 라이선스 병행(`LICENSE.md`) | 동일 |
| Galapagos(웹 UI) | **GPL-2.0 이상**(`LICENSE.txt`; 상업 조항 없음) | 동일 |
| 번들 확장 다수(table, nw 등) | 대부분 퍼블릭 도메인/CC0 (공식 FAQ; 각 확장 README 확인 필요) | **자유롭게 재사용 가능** — 확장 코드는 예제·패턴 소스로 가장 부담 없는 부분 |
| 모델 라이브러리 | Code Examples는 퍼블릭 도메인, 나머지 다수는 CC BY-NC-SA(비상업) | 모델 코드 인용 시 주의 |

**[추론]** 파서(`parser-core`)가 GPL이므로 "NetLogo 언어 파서만 떼어 내 독립 엔진에 붙이는" 선택지도 GPL 전파를 받습니다. 연구 소프트웨어를 GPL로 공개할 계획이면 무방하고, 그렇지 않다면 재사용은 '설계 원리'와 '퍼블릭 도메인 확장 코드' 수준으로 한정하는 것이 안전합니다. (라이선스 해석은 최종적으로 소속 기관 법무 확인이 필요합니다.)

---

## 10. 내 시장 모형으로 연결: 일곱 가지 질문에 대한 NetLogo발(發) 답

이하는 구현이 아니라 설계 원칙입니다. 각 항목에서 "NetLogo가 주는 답 / NetLogo에 없는 답"을 구분합니다.

### 10.1 판단 기능과 주문 접수·체결·회계의 분리

- **NetLogo가 주는 답**: "세계 상태를 바꾸는 문은 하나"(JobManager 원칙, 2.4절). 번역하면 — **시장 상태(호가장·체결·계좌)를 바꾸는 유일한 주체는 체결 엔진**이고, 에이전트의 판단 기능(LLM 호출 포함)은 상태를 직접 못 만지고 **주문(메시지)을 제출**할 수만 있어야 합니다. NetLogo에서 프리미티브가 세계를 직접 변이하는 것과 달리, 귀하의 모형에서 '프리미티브'에 해당하는 것은 주문 접수 API 하나로 좁혀야 합니다.
- 또 하나: BehaviorSpace가 측정을 RNG 클론에서 수행하는(3.4절) 것처럼, **관측·로깅·지표 계산은 시장 상태의 읽기 전용 스냅샷에서** 수행해 관측이 실행을 교란하지 못하게 해야 합니다.
- **NetLogo에 없는 답**: NetLogo의 에이전트는 판단과 행동이 한 호출 안에 붙어 있습니다(ask 블록). LLM처럼 판단이 느리고 실패할 수 있는 경우의 분리 계약(주문의 유효기간, 거부 사유 반환)은 새로 설계해야 합니다.

### 10.2 동시 정보 모형 vs 순차 정보 모형의 구분

- **NetLogo가 주는 답**: 이 구분을 스케줄러의 암묵 규칙에 맡기면 안 된다는 것 — 4.0 전환의 교훈(8.1) 그대로입니다. NetLogo 모델러들이 쓰는 2단계 패턴(모두가 의도를 기록 → 일괄 적용)이 "동시 정보" 모형의 정석 구현입니다.
- **설계 제안 [추론]**: 정보 공개 시점을 **시장 메커니즘의 명시적 파라미터**로 두십시오. (a) *일괄 경매(call auction)* = 모든 에이전트가 같은 스냅샷 t를 보고 주문 → t+1에 일괄 체결: '동시 정보' 모형이며 재현·분석이 쉬움. (b) *연속 복식 호가(CDA)* = 주문이 도착 순서로 체결되고 호가장이 즉시 갱신: '순차 정보' 모형이며 도착 순서 규칙(무엇이 순서를 정하는가 — 5.3의 단일 직렬화 지점이 필수)이 곧 모형 가정이 됩니다. 두 메커니즘을 같은 엔진의 교체 가능한 모듈로 두면 "관찰된 차이가 메커니즘 때문인지"를 실험 요인으로 분리할 수 있습니다(10.7).

### 10.3 LLM 응답 시간과 경제적 시간의 분리

- **NetLogo가 주는 답(소극적)**: `tick`은 시계가 아니라 카운터이며(3.3), 논리적 시간과 벽시계 시간의 분리는 NetLogo가 잘한 부분입니다. 반면 NetLogo Web은 동기 의미론에 실시간을 접붙이다 `wait`를 no-op으로 만들었습니다(7.3) — 두 시간을 섞으면 어느 쪽도 지킬 수 없다는 반면교사.
- **설계 제안 [추론]**: 모형 시간은 **이산 사건 스케줄(이벤트 시각의 전순서)**로만 정의하고, LLM 호출의 벽시계 지연은 별도 계층에서 처리합니다. 선택지는 명시적 연구 가정입니다: (a) *동기 라운드*: 라운드마다 모든 에이전트의 응답을 기다렸다가(타임아웃 시 기권 처리) 모형 시간을 진행 — 지능 비교 연구에 적합, 속도 효과 제거. (b) *지연 주입*: 측정된(또는 모형화된) 응답 지연을 모형 시간의 도착 지연으로 사상 — '속도도 능력이다'를 연구할 때. 어느 쪽이든 **벽시계가 모형 시간을 암묵적으로 결정하는 설계(도착한 순서대로 그냥 처리)는 재현 불가능**하므로 배제해야 합니다.

### 10.4 느린·실패한 에이전트, 초기화 후 도착한 응답, 재시도 중복

- **NetLogo가 주는 답**: 죽은 에이전트 처리(4.2)가 모범입니다 — 삭제가 아니라 표시(id=-1), 모든 접근 지점에서 검사, id 영구 결번. 번역: **주문·요청에 전역 유일 id와 세대(epoch) 표지**를 붙이고, 세계가 리셋되면 epoch를 올려 **이전 epoch의 응답은 도착해도 무시**(NetLogo Web의 '문맥 잃은 콜백' 문제(7.3)의 해독제).
- **NetLogo에 없는 답**: 재시도·중복입니다(6.4). 분산 시스템의 표준 해법을 가정으로 명시해야 합니다: 주문 제출은 **멱등 키**(같은 키 재제출은 무시), 타임아웃된 에이전트는 '기권'으로 기록(응답이 늦게 오면 폐기 + 로그), 실패는 결측이 아니라 **데이터**(LLM 실패율 자체가 시장 변수가 될 수 있음).

### 10.5 현금·수량·주문·체결의 일관성

- **NetLogo가 주는 답(반면교사 포함)**: `carefully`는 롤백하지 않고(4.4), 오류 난 잡은 부분 갱신 상태를 남깁니다. 탐색용 ABM에서는 용인되지만 회계에는 안 됩니다. 한편 단일 스레드 직렬화(5.1)는 **원자성을 공짜로** 줍니다 — 체결 엔진을 단일 쓰기 스레드로 두면 락 없이 "주문 검증→체결→계좌 반영"을 원자 단위로 만들 수 있습니다.
- **설계 제안 [추론]**: **이벤트 소싱** — 장부의 진실은 '체결 이벤트의 추가 전용 로그'이고, 계좌·호가장은 그 로그의 순수 함수(파생 뷰). 이렇게 하면 (i) `carefully` 없는 세계에서도 중간 실패가 불변식을 못 깨고(이벤트는 통째로 기록되거나 안 되거나), (ii) export-world에 해당하는 스냅샷이 자동으로 생기며(로그 접두사), (iii) NetLogo의 체크섬 회귀 테스트에 해당하는 **불변식 검사**(총현금+총주식가치 보존, 주문-체결 대응)를 로그 위에서 상시 돌릴 수 있습니다.

### 10.6 기록과 재생: 무엇을 남겨야 같은 실험을 다시 돌리나

- **NetLogo가 주는 답**: 재현성의 실체는 "시드 + 단일 직렬화 + 전체 상태 직렬화(RNG 상태 포함)"였습니다(3.4, 4.5). 그리고 그 보장조차 "같은 엔진 버전"이라는 단서가 붙습니다.
- **번역 [추론]**: LLM 에이전트 시장에서 '난수원'에 해당하는 비결정 원천이 셋입니다 — ① 엔진 난수(시드로 통제), ② 사건 순서(단일 직렬화 지점의 로그로 통제), ③ **LLM 응답**(통제 불가 → 기록으로 대체). 따라서 기록 단위는: {엔진 버전·설정, 시드, 에이전트별 LLM 모델 버전·샘플링 파라미터, 각 호출의 입력 프롬프트·출력 전문, 전체 사건 로그(주문 도착·체결·정보 공개의 전순서)}. **재생 모드**에서는 LLM 호출을 로그된 응답으로 치환해 전체 실험이 비트 단위로 재현되게 합니다. 이것이 BehaviorSpace의 "측정은 클론에서"에 해당하는, 비교 연구의 전제 조건입니다.

### 10.7 관찰된 차이의 원인 분리: 지능·이질성 vs 메커니즘·순서

- **NetLogo가 주는 답**: BehaviorSpace의 본질은 "실험 = 요인 공간 위의 프로토콜"이라는 것(5.2), 그리고 병렬 복제 시 격리와 시드 관리가 명시적 계약이어야 한다는 것입니다.
- **설계 제안 [추론]**: 에이전트 유형(LLM A/B, 규칙 기반, 제로 지능(ZI))과 시장 파라미터(정보 공개 방식, 체결 규칙, 순서 규칙)를 **같은 실험 관리자 안의 직교 요인**으로 두십시오. 특히 **같은 하네스에 규칙 기반·ZI 에이전트를 넣을 수 있어야** 합니다 — Gode-Sunder류 ZI 기준선과의 비교가 "지능 때문인가, 메커니즘 때문인가"를 가르는 고전적 판별 도구이고, NetLogo가 다양한 모델을 한 엔진에서 돌리듯 에이전트 인터페이스를 LLM 전용으로 좁히지 않는 것이 그 전제입니다. 또한 10.6의 재생 모드가 있으면 "같은 사건 순서에서 에이전트만 바꾸는" 반사실(counterfactual) 실험이 가능해져 순서 효과와 지능 효과를 분리할 수 있습니다.

---

## 11. 전략 옵션 비교: NetLogo를 어떻게 쓸 것인가

결론을 미리 정하지 말라는 요청에 따라, 조사에서 확인된 사실로부터 각 옵션의 적합 조건을 평가합니다.

### 옵션 A — NetLogo(데스크톱/헤드리스)를 그대로 실행기로 사용

- **근거 사실**: 엔진은 워크스페이스당 단일 스레드(5.1); 확장 프리미티브는 동기 호출로 엔진과 World 락을 점유(6.1); 외부 비동기는 폴링 또는 락 양보 대기로만 처리 가능(6.3); BehaviorSpace로 독립 런 병렬화는 성숙(5.2); GPL(9장).
- **평가**: 소수 에이전트(수십)·동기 라운드 가정·tick당 LLM 일괄 호출이라면 **지금도 가능**합니다(확장이 tick 사이에 모든 프롬프트를 비동기로 병렬 발사하고, HubNet식 폴링으로 회수). 그러나 에이전트 수·비동기성·체결 규칙의 정밀 통제가 커지는 순간 6.4의 공백(취소·중복·타임아웃)과 5.3의 상한(세계당 1코어)에 부딪히며, 이는 귀하가 피하려는 "나중에 전부 다시 만드는" 시나리오입니다.
- **적합 용도**: 메커니즘 교육·시연, 규칙 기반 기준선 모형의 빠른 탐색, 커뮤니티와의 소통.

### 옵션 B — NetLogo 엔진 + 외부 의사결정 시스템 연결

- **근거 사실**: 전례가 셋 있습니다 — py/sr 확장(동기 서브프로세스), CommandServer(소켓→이벤트 스레드→잡), LevelSpace(잡 제출 + 락 양보 대기)(6.3). 전부 "엔진의 한 문"을 통과하며, 백프레셔·타임아웃·중복 처리는 전부 다리(bridge) 몫.
- **평가**: 옵션 A의 한계를 그대로 상속하면서 운영 복잡도(두 시스템, 준내부 API 의존)를 더합니다. LevelSpace의 `UnlockAndBlock` 같은 코드는 참고 가치가 높지만, 이 경로를 본선으로 삼으면 가장 어려운 문제(비동기 경계)를 가장 제약 많은 환경에서 풀게 됩니다.
- **적합 용도**: 옵션 A를 쓰다가 LLM 호출부만 외부화하는 과도기.

### 옵션 C — 일부 구성요소만 재사용

- **근거 사실**: 재사용 가능한 단위는 (i) 파서(NetLogo 언어를 쓸 때만 의미, GPL 전파), (ii) 퍼블릭 도메인 확장 코드(패턴 소스), (iii) 그리고 무형 자산인 테스트 자료(언어 테스트, 체크섬 방식). 엔진 코어는 World·Job·Context가 강하게 결합되어 있어 "체결 엔진만 떼 오기" 같은 절단면이 없습니다(1~5장 전체). **[소스+추론]**
- **평가**: 코드 재사용의 실익은 작습니다. 귀하의 모형은 NetLogo 언어가 필요 없고(에이전트가 LLM이므로), 시장 로직은 NetLogo에 없으므로.
- **적합 용도**: 테스트 방법론(언어 테스트 형식, 세계 체크섬, 병렬 결정론 테스트)의 이식.

### 옵션 D — 설계 원리를 차용한 독립 엔진

- **근거 사실**: 조사 전체가 가리키는 방향입니다. 가져올 원리(요약): **엔진에 들어가는 문 하나**(2.4) / **상태 변경의 단일 직렬화 지점**(5.1) / **판단 문맥과 세계 상태의 분리**(4.1) / **난수 소유권 명시(main/aux 분리, 관측은 클론)**(3.4) / **공평성은 명시적 셔플로**(3.1) / **id 영구 결번 + 접근 지점 사망 검사**(4.2) / **전체 상태 직렬화와 체크섬 회귀 테스트**(4.5) / **독립 복제 병렬화는 '공유 금지+완전 복제'로**(5.2) / **파서(언어)와 실행기의 분리**(1.1). 버릴 것: 비롤백 오류 모델(4.4), 협조적 halt뿐인 취소(6.4), 동기 확장 경계(6장), 의미론 이중 구현(1.3), 동기 엔진에 비동기 접붙이기(7.3).
- **평가**: LLM의 비동기성·실패·비결정성이 모형의 1급 요소인 이상, NetLogo가 **풀지 않은**(풀 필요가 없었던) 문제들이 귀하 설계의 중심이 됩니다. 이 문제들은 처음부터 설계에 넣는 비용이 가장 쌉니다.

### 종합 판단

**이분법이 아니라 병행**을 권합니다: (1) 시장 메커니즘·기준선(규칙 기반/ZI) 검증은 당분간 NetLogo(옵션 A)로 — 빠르고, 커뮤니티 검증이 쉬우며, 나중에 독립 엔진의 **교차 검증 대조군**이 됩니다(같은 시나리오를 두 엔진에서 돌려 결과 일치 확인). (2) LLM 에이전트 본 실험용 엔진은 옵션 D로, 10장의 원칙과 13장의 검증 실험을 앞세워 작게 시작하되 **경계(주문 API, 사건 로그, 재생 모드)부터** 설계합니다. 이것은 "일단 작은 것부터"라는 일반론이 아니라, 이번 조사에서 확인된 NetLogo의 공백(비동기 경계·회계 일관성·LLM 기록 재생)이 코어 요구라는 판단에 따른 순서입니다.

---

## 12. 아직 결정하지 않은 연구 가정과 미검증 사항

### 연구 가정(귀하가 명시적으로 정해야 할 것)

1. **지연-시간 사상**: LLM 응답 속도를 시장 참여 속도로 반영할지(10.3의 (a) vs (b)). 반영한다면 측정 지연인지 모형화된 지연인지.
2. **정보 공개 체제**: 일괄 경매 vs 연속 호가, 호가장 공개 수준(전체/최우선/체결가만), 공개 지연.
3. **비교 대상**: 실제 시장 자료 vs 인간 피험자 실험 vs 규칙 기반(ZI 포함) 대조군 — 셋은 요구하는 로깅·설계가 다르므로 엔진 요구사항에 영향.
4. **에이전트 이질성의 차원**: 모델(서로 다른 LLM)·프롬프트(목표/제약)·기억(컨텍스트 관리)·정보 접근 중 무엇을 요인으로 삼을지.
5. **실패의 지위**: LLM 호출 실패·타임아웃을 잡음으로 볼지 연구 대상으로 볼지(10.4).

### 미검증 사항(이번 조사의 한계)

- 성능 실측은 13.1의 범위(폴링 처리량, halt 지연)까지만 수행했습니다. 실제 모형 규모(에이전트 수 × tick/초, 대규모 세계의 메모리·GC 거동)는 여전히 미측정.
- `ask-concurrent`의 현재 동작 정합성(개발팀 스스로 비지원 선언; 코드가 남아 있다는 것과 올바르게 동작한다는 것은 다름).
- GUI/headless 프리미티브 이중 구현의 의미 차이는 표본 diff로만 확인(한 곳 외 차이 없음) — 전수 검증 아님. 다만 실측에서 실제 차이 1건 확인: 릴리스(GUI 빌드)에는 `__checksum`이 아예 없음(13.1).
- py 확장의 서브프로세스 계층(`languagelibrary` 외부 의존성)의 블로킹·타임아웃 동작 — 저장소 밖 코드라 미확인.
- BehaviorSpace 1코어 기본값 0 문제(5.2 함정 3)는 코드 독해 추론이며 실행 재현 안 함.
- 웹 확장에서 `time` 확장이 빠진 이유 — 코드에서 설명을 찾지 못함.
- 2011년 이전 설계 이력은 커밋이 없어 문헌 의존.

---

## 13. 다음 단계: 최소 검증 실험과 판별 기준

구현 착수 전, 아래 실험들이 설계 가정을 가장 싸게 검증합니다. (1~4는 NetLogo 실측 — 수 시간 규모, 5~6은 독립 엔진 스파이크 — 수일 규모.)

| # | 실험 | 방법 | 판별 기준 |
|---|---|---|---|
| 1 | **재현성 기준선** | HeadlessWorkspace로 같은 모델·시드를 2회 실행, export-world 체크섬 비교. 이어 BehaviorSpace threads=1 vs N에서 런별 체크섬 비교 | 체크섬 완전 일치 → "시드+직렬화=재현" 확인. N스레드에서 불일치 발생 시 병렬 격리 가정 기각 |
| 2 | **동기 경계 실측** | 2초 sleep하는 더미 확장 프리미티브(모의 LLM 호출)를 tick마다 호출. UI 응답성·halt 소요시간·뷰 갱신 측정. `UnlockAndBlock` 패턴 적용 전후 비교 | halt 지연 ≥ 호출 시간이면 동기 경계 확인. 락 양보 패턴으로 뷰·halt가 살아나면 옵션 A의 실용 한계치 산출 |
| 3 | **폴링 처리량** | HubNet식 큐에 외부 스레드 N개가 모의 주문을 주입, 단일 JobThread가 소화하는 주문/초 측정(N=10/100/1000) | 처리량이 N에 무관하게 평탄하면 "세계당 1코어" 상한 정량화 → 목표 에이전트 수와 비교해 옵션 A/D 분기점 결정 |
| 4 | **런 간 오염 재현** | BehaviorSpace 병렬 실험에서 setup의 `clear-all`을 뺀 채 전역·patch 상태를 남기고, 결과가 런 배정 순서에 의존하는지 확인 | 의존 발생 → "격리는 사용자 책임" 확인, 내 실험 관리자의 자동 격리 요구사항 확정 |
| 5 | **회계 불변식 스파이크** | 이벤트 소싱 주문장 프로토타입(단일 쓰기 스레드) + 속성 기반 테스트: 무작위 주문·취소·실패·중복 제출 주입 | 총현금+총주식 보존, 멱등 키 중복 0건, 임의 접두사 로그 재생=동일 상태. 하나라도 깨지면 설계 수정 |
| 6 | **LLM 기록·재생** | 에이전트 2~3개로 소형 시장 1회 실행하며 전체 로그(프롬프트·응답·사건 순서) 기록 → 재생 모드로 재실행 | 재생 결과가 원 실행과 비트 단위 일치. 불일치 지점은 미기록 비결정 원천의 존재 증거 |

### 13.1 실측 결과 (2026-10-22 수행)

실행 환경: NetLogo **7.0.4 공식 릴리스**(aarch64 dmg, GitHub Releases에서 입수)의 `netlogo-headless.sh` + 번들 JRE(OpenJDK 17.0.2), macOS(10코어/64GB). 실험 2·3용 모의 외부호출 확장(`mock.jar`: block/sleep/yield/주문큐 프리미티브)과 임베딩 드라이버(Java)는 이 세션 폴더 `experiments/` 아래에 있어 재현 가능합니다. 분석 기준 커밋(13a2d8f1d)이 아닌 최신 안정 릴리스로 실측했음을 유의해 주십시오.

**실험 1 — 재현성: 통과 (24/24 해시 일치).** Wolf Sheep Predation 모델, 런별 `random-seed (1000 + 런번호)`, 100 tick 후 `postRun`에서 `export-world`. threads=1 두 번 + threads=6 두 번 = 4개 패스 × 6런의 세계 덤프(전 에이전트·전역·mainRNG 상태 포함)를 타임스탬프 헤더 3줄 제거 후 SHA-256으로 비교한 결과, **같은 런 번호는 4개 패스에서 전부 동일, 다른 런끼리는 전부 상이**했습니다. 런별 시드를 고정하면 6스레드 병렬에서도 런 단위 결정론이 유지됩니다(5.2의 가정 실증).
- 부수 발견 ①: 릴리스 jar(GUI 빌드)에는 headless 트리에 있는 `__checksum` 프리미티브가 **없습니다**("Nothing named __checksum has been defined"). 1.3절에서 지적한 프리미티브 이중 구현이 실제 동작 차이로 나타난 사례입니다.
- 부수 발견 ②: `export-world`의 상대 경로는 프로세스 작업 디렉터리가 아니라 **모델 파일의 위치** 기준으로 해석됩니다 — 파일 I/O가 모델에 정박된 설계.

**실험 4 — 런 간 오염: 재현됨, 그리고 병렬 전용 문제가 아님.** `clear-all` 없이 setup마다 `patch 0 0`의 pcolor를 +1 하는 최소 모델로 12회 반복 실험. threads=1에서 측정값이 1→12로 누적 — **직렬 실행에서도 워크스페이스 하나가 모든 런에 재사용되고 BehaviorSpace는 아무것도 지우지 않습니다.** threads=4에서는 각 런의 값이 "배정된 워크스페이스가 몇 번째로 쓰였는가"가 되어 완료 순서대로 뒤섞였고, **같은 실험을 두 번 실행하자 run 12의 값이 4→3으로 달라졌습니다** — 격리를 setup이 책임지지 않으면 결과가 스케줄링에 의존함을 그대로 재현했습니다.

**실험 2 — 동기 경계와 halt 지연.** 5초짜리 모의 외부 호출(LLM 호출 대역)을 걸고 1초 뒤 다른 스레드에서 halt 호출 + World 락 획득 시도(뷰 스레드 대역):

| 호출 방식 | World 락 대기 | halt 반환 | 엔진 점유 |
|---|---|---|---|
| `wait 5` (엔진 협조적 대기) | 0ms | 0ms | 즉시 중단(~1.0s 종료) |
| `mock:sleep` (인터럽트 허용 블로킹) | 3ms | 3ms | 즉시 중단 |
| `mock:block` (인터럽트 무시 블로킹 = 비중단 I/O 모사) | **4017ms** | **4017ms** | **5초 전부 점유** |
| `mock:yield` (LevelSpace식 락 양보 대기) | 0ms | 2ms | 즉시 중단 |

6장의 추론이 수치로 확정됐습니다: 인터럽트에 반응하지 않는 외부 호출 하나가 **남은 시간 내내 엔진·뷰 락·halt를 전부 봉쇄**합니다. 반대로 락 양보 패턴은 같은 5초 작업 중에도 락 대기 0ms, halt 2ms — 옵션 A(NetLogo 직접 사용)를 택한다면 이 패턴이 필수 전제입니다.

**실험 3 — 폴링 처리량(주문 20만 건 소비, 2회 반복).** 외부 주입 스레드 N개가 동시 큐에 주문을 넣고 모델이 `mock:fetch`로 소비:

| 조건 | 처리량(주문/초) |
|---|---|
| (기준선) 빈 `repeat` 20만 회 | 25~26ms 소요 |
| 주입 스레드 1 | 217만~294만 |
| 주입 스레드 10 | 163만~200만 |
| 주입 스레드 100 (10코어 과점유) | **34만~40만** |

단일 엔진 스레드의 소비 속도는 생산자 수로 **늘지 않으며**(5.3의 구조 그대로), 생산자가 코어 수를 크게 초과하면 큐 경합·CPU 선점으로 오히려 5~7배 하락합니다. 다만 절대치가 초당 수백만 폴링이므로, 현실적 에이전트 수에서 병목은 폴링 오버헤드가 아니라 "주문당 실제 처리(체결·회계·로깅)가 전부 한 스레드를 공유한다"는 구조입니다. (한계: 주입 스레드가 거의 스핀 루프여서 N=100은 의도적 과부하 조건이며, 실제 LLM 응답자는 이런 부하 패턴이 아닙니다.)

**판별 기준 대조 요약**: ① 통과 — "시드+직렬화=재현" 가정 유지, 병렬 격리도 시드 고정 시 성립. ② 동기 경계 확정 — 비중단 블로킹 1건이 엔진 전체를 세움; 락 양보 패턴 유효성 실증. ③ 상한 정량화 — 폴링 자체는 수천 에이전트 규모까지 문제 아님; 구조적 제약은 단일 소비 스레드. ④ 오염·순서 의존 재현 — 내 실험 관리자에는 **런마다 새 워크스페이스 또는 강제 초기화**가 요구사항으로 확정.

### 13.2 독립 엔진 스파이크 실측 결과 (2026-10-22 수행)

10.5(이벤트 소싱 장부)·10.6(기록·재생)의 설계 원칙을 그대로 구현한 최소 시장 엔진(Python, 표준 라이브러리만, `experiments/spike/engine.py` 약 230줄)으로 실험 5~6을 수행했습니다. 엔진 구조: 지정가 CDA 호가장 + 계좌(현금·주식·예약분), 모든 상태 변경은 명령 처리기가 계산한 **이벤트의 순수 폴드(apply)** 로만 발생, 멱등 주문 키, epoch 표지. 재생은 매칭 로직을 전혀 거치지 않고 이벤트 로그만 다시 폴드합니다.

**실험 5 — 회계 불변식: 통과.** 시드된 난수로 100개 시나리오 × 2,000개 명령(총 20만 명령, 체결 21,563건, 4.3초 소요)을 주입 — 정상 주문, 중복 제출, 미지/기체결 주문 취소, 잔고 초과 주문, epoch 리셋 직후의 늦은(stale) 주문 포함. **매 명령 뒤** 불변식 검사:

| 판별 기준 | 결과 |
|---|---|
| 보존 법칙(총현금+예약현금, 총주식+예약주식 불변) 및 음수 잔고·예약액 정합·호가장 비교차 | 위반 **0건** / 20만 검사 |
| 수리(accepted)된 주문의 중복 제출 7,660건의 상태 효과 | **0건** |
| epoch 리셋 후 도착한 옛 세대 주문 | 60,090건 전부 거부 |
| 전체 로그 재생 = 라이브 상태 (해시 비교, 시나리오 100개) | 불일치 **0건** |
| 무작위 접두사 재생 = 체크포인트 상태 | 불일치 **0건** |

- 부수 발견(정직하게 기록): 첫 실행은 FAIL이었습니다. 원인은 엔진이 아니라 테스트의 개념 혼동 — "**거부된** 주문의 재시도"(멱등 키를 기억하지 않으므로 새 제출로 수리되어 상태 효과가 있는 것이 정상)와 "**수리된** 주문의 중복"(효과 0이어야 함)을 구분하지 않았습니다. **멱등성의 범위(수리된 명령만 기억할지, 거부 시도까지 기억할지)는 명시적 설계 결정**이며, 이번 스파이크는 전자를 채택했습니다(거부는 무효과이므로 재시도 허용이 안전하고 바람직). 수정 후 재시도-후-수리 8,319건은 허용된 효과로 분리 집계.
- 처리량 참고치: 매 명령 전체 불변식 검사를 포함하고도 비최적화 인터프리터(Python)에서 약 4.7만 명령/초 — 실험 3의 NetLogo 폴링 상한과 마찬가지로, 이 규모의 연구에서 체결·회계 처리 자체는 병목이 아닙니다.

**실험 6 — 기록·재생 결정론: 통과.** 모의 LLM 에이전트 3개 × 50호출(총 150건, 체결 84건). 비결정 원천을 실제로 심었습니다: 판단은 시드 불가능한 `os.urandom` 난수, 도착 순서는 실제 스레드 스케줄링과 1~15ms 무작위 지연. 기록은 **엔진 도착 순서대로의 응답(주문) 전부**(`exp6-record.json`)뿐입니다.

| 판별 기준 | 결과 |
|---|---|
| 재생 1회·2회 = 라이브 실행 최종 상태 해시 | **일치** (기록이 재현의 충분조건) |
| 라이브 실행을 한 번 더 수행 | 해시 **불일치** (비결정성이 실재함의 증명 — 기록 없이는 재현 불가) |
| 기록 1건을 제거한 재생 | 해시 **불일치** (로그 변조·누락 탐지 가능) |

**종합**: 10장에서 도출한 설계(단일 직렬화 체결 엔진 + 이벤트 소싱 장부 + 멱등 키 + epoch 표지 + 도착 순서 로그)가 ① NetLogo가 풀지 않은 세 공백(비동기 실패·중복·회계 일관성)을 모두 막아내고 ② LLM급 비결정성 아래서도 비트 단위 재현을 제공함을 소규모로 실증했습니다. 남은 확장 방향: 일괄 경매 모듈 추가(10.2의 메커니즘 요인화), 실제 LLM 어댑터와 프롬프트·모델 버전 로깅, 성능이 필요해질 때의 코어 재작성.

---

## 부록: 참고 자료

**소스 저장소** (기준 커밋은 0.1절): [NetLogo](https://github.com/NetLogo/NetLogo) · [Tortoise](https://github.com/NetLogo/Tortoise) · [Galapagos](https://github.com/NetLogo/Galapagos) — 모두 로컬 `repos/` 아래에 클론됨.

**문헌·문서**
- Tisue, S. & Wilensky, U. (2004), [NetLogo: Design and implementation of a multi-agent modeling environment](https://ccl.northwestern.edu/2013/netlogo-agent2004c.pdf) — 설계 목표·동시성·재현성·확장성의 1차 사료.
- [NetLogo 4.1 Transition Guide](https://ccl.northwestern.edu/netlogo/4.1/docs/transition.html) — 4.0의 ask 순차화 사유.
- [NetLogo 4.1 FAQ](https://ccl.northwestern.edu/netlogo/4.1/docs/faq.html) · [현행 FAQ](https://docs.netlogo.org/faq) — 구현 언어·바이트코드 컴파일러·라이선스.
- [NetLogo 5.3.1 Programming Guide](https://ccl.northwestern.edu/netlogo/5.3.1/docs/programming.html) — ask/agentset/난수 공식 의미론.
- [ask-concurrent 사전 항목(7.0.3)](https://docs.netlogo.org/dict/ask-concurrent) · [공식 포럼: ask-concurrent 비지원 답변](https://forum.netlogo.org/t/strange-errors-with-the-combination-of-foreach-and-ask-concurrent/785)
- [Tortoise 아키텍처 위키](https://github.com/NetLogo/Tortoise/wiki/Architecture) · [NetLogo Web 위키](https://github.com/NetLogo/NetLogo/wiki/NetLogo-Web)
- Seth Tisue 약력(Scala로 NetLogo 컴파일러 개발): [Scale By the Bay 2018](https://scalebythebay2018.sched.com/list/descriptions/type/functional)

**주요 커밋** (NetLogo 저장소): `9e32be023`·`633b3c357`(2016 모노레포), `6b5ee2f50`(2014 ask-concurrent), `e1185fe67`(2023 병렬 기본화), `25a8bd62b`(2020 병렬 함정 문서), `b02c2b777`(2025 데드락 수정), Tortoise `710bd9af`(2021 wait no-op).


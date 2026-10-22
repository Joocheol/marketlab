# 신호 변형 정책 수정 전문 (클론 응답, 2026-10-23)

고지: V~U[80,120] 런별 추출, 알 수 없는 시점에 V로 청산. 사적 신호
s=V+ε(ε~U[-8,8]) 1회. 구조는 공통 지식. 전원 AMEND. 구현: ../policies_signal.py

## momentum
1) v̂: 체결 전 clamp(s,82,118); 체결 후 w·s+(1-w)·mean(recent), w=max(0.3, 0.8-0.1·len(recent))
2) BUY는 price≤v̂-2만: ask≤v̂-2면 수취, 아니면 v̂-rng(2,4) 지정가; qty 저평가 폭 비례 ≤5
3) SELL: bid≥v̂+2면 min(5,shares)@bid; 추세<0이고 last>v̂면 보유 축소
4) 확률 성분 유지(15% 불참, 미형성 40% 수취는 ask≤v̂-2 조건), 한도 동일

## value
1) v0=(max(80,s-8)+min(120,s+8))/2; v̂=round(0.6·v0+0.4·mean(recent))(없으면 v0)
2) 즉시 매매 경계 v̂±5 (신호오차·승자의 저주 대비 마진)
3) 50% 대기주문: 매도 v̂+4+rng(0,2) / 매수 v̂-4-rng(0,2)
4) 한도·나머지 동일

## mm
1) est: 0.8·s+0.2·100 시작, 체결마다 0.7·est+0.3·체결가
2) 호가 중심 0.6·시장가+0.4·est; half=rng{2,3,4}, |last-est|>6이면 rng{3,4,5}(역선택 대비)
3) 테이킹은 est±5 이상 확신 괴리만 (p=0.15, 연속 금지)
4) 수량 비대칭·skew·한도는 est 기준 동일

## conservative
1) ref=clamp(s,80,120) 고정
2) 경계 ±12%(노이즈 반영 확대): bid≥1.12ref 매도 / ask≤0.88ref 매수
3) 깊은 지정가 0.86ref/1.14ref
4) 나머지(u, 항상 유지, qty=1) 동일

## aggressive
1) v̂=round(0.5·s+0.5·(last or s)) — 체결가는 타인 신호의 집계
2) 클램프: 매수≤v̂-rng(1,3) / 매도≥v̂+rng(1,3)
3) 최우선 분기: ask≤s-6 즉시 매수 min(8,cash//ask); bid≥s+6 즉시 매도 min(8,shares)
4) 기존 분기 구조·확률·한도 유지, ref를 v̂로 치환

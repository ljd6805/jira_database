# 변경 기록

## v0.9

Reviewer를 점수 중심 평가에서 결함 탐지 중심으로 변경.

- Fact Audit 추가
- Causal Claim Audit 추가
- Evidence Audit 원자 사실 단위로 강화
- Classification Audit 강화
- Missing Knowledge Audit 추가
- Duplication/Low-value Audit 분리
- `못 찾음 != 배제`, `확인되지 않음 != 검증 미완료` 명시
- trade-off 누락을 Major 후보로 추가
- Critical 존재 시 score 최대 7.9
- Major 존재 시 score 최대 8.4
- 모든 Audit 후에만 점수 계산
- Worker 재생성 시 audit_findings까지 반영

Knowledge Schema v0.1은 유지.

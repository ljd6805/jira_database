---
name: html-diagram-visual-qa
description: HTML/SVG flowchart와 관계도의 화살표·노드·edge label 겹침을 예방하고 시인성을 검수하며, 시각화 개선 중 기존 설명의 정보 손실을 막는다.
compatibility: opencode
metadata:
  language: ko
  skill-version: "1.1"
---

# HTML Diagram Visual QA Skill v1.1

## 언제 사용하나

HTML 문서에서 flowchart, architecture map, relationship map, SVG diagram을 새로 만들거나 수정할 때 사용한다.

## 기본 선택

1. 2~5개 수준의 단순 직선 흐름은 CSS Grid/Flex를 우선한다.
2. 분기·회귀·다대다 연결이 있는 경우에만 SVG network를 사용한다.
3. 복잡한 SVG에서는 obstacle-aware orthogonal routing을 우선한다.

## Content Preservation 규칙

- **시각화는 설명을 대체하지 않고 보강한다.** 다이어그램 추가나 디자인 개선은 기존 설명 위에 이해를 돕는 시각 계층을 추가하는 작업이다.
- 문서에 이미 있던 **기존의 유효한 설명**, 표, 예시, 주의사항, 관계 설명, Source of Truth 링크를 시각화 개선만을 이유로 삭제하거나 과도하게 축약하지 않는다.
- 기본 읽기 순서는 가능하면 **그림 → 상세 설명 → 관계/표 → 쉬운 예시 → Source of Truth** 로 구성한다.
- 복잡한 그림은 설명을 없애는 대신 여러 diagram으로 분리하고, 상세 정보는 카드/표로 내려서 역할을 나눈다.
- 내용 삭제/축약은 **사용자가 명시적으로 삭제/축약을 요청**했거나, 코드/DDL/검증과 비교해 **오래되어 틀린 내용**임이 확인된 경우에만 허용한다.
- 오래된 내용을 제거하거나 대체할 때는 무엇을 왜 바꿨는지 **삭제 이유를 문서에 남긴다**. historical 가치가 있으면 삭제보다 superseded/historical 표기를 우선한다.
- Visual QA는 모양뿐 아니라 정보 coverage도 비교한다. 정당한 이유 없는 설명 손실은 0건이어야 한다.

## Connector 규칙

- 화살표는 source/target 이외의 node bounding box를 통과하지 않는다.
- node 외곽에 최소 clearance를 둔다.
- 임의의 cubic Bézier와 고정 control point만으로 dense graph를 해결하지 않는다.
- 선끼리 교차가 불가피하면 배경색 halo를 먼저 그려 교차점을 분리한다.
- 긴 우회 경로가 생겨도 node 관통보다 우선한다.

## Edge label 규칙

- 경로의 단순 midpoint에 label을 자동 배치하지 않는다.
- label rectangle과 모든 node/기존 label의 충돌을 검사한다.
- 공간이 부족하면 label을 빈 annotation lane으로 옮기고 leader line으로 연결한다.
- label은 불투명한 배경 tag 위에 그려 뒤쪽 connector가 글자를 가리지 않게 한다.
- 의미가 이미 양쪽 node에 명확히 적혀 있으면 불필요한 edge label은 제거한다.

## 반응형 규칙

- 큰 network SVG를 모바일 폭에 억지로 축소해 글자를 작게 만들지 않는다.
- 최소 너비 + horizontal scroll을 허용한다.
- 단순 flow는 모바일에서 행→열 구조로 전환한다.

## Visual QA

완료 전에 최소한 다음을 확인한다.

1. connector → 제3 node 내부 교차 0건
2. edge label → node 겹침 0건
3. edge label → edge label 겹침 0건
4. 텍스트가 connector 뒤에 묻히지 않음
5. 복잡한 graph에서 한 node의 연결만 focus할 수 있음
6. 1280px 데스크톱과 좁은 화면에서 모두 읽을 수 있음
7. before/after 비교에서 기존 설명·표·예시·주의사항의 정당한 이유 없는 정보 손실 0건

## 프로젝트 적용 원칙

Jira Knowledge DB의 current 관계도는
`docs/architecture/jira_data_relationship_router.js`를 공통 router로 사용한다.

완료된 historical archive는 시각 스타일 개선만을 이유로 소급 수정하지 않는다.

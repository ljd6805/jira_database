# M8 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE**

M8 · Embedding Unit / Chunk + BGE-M3 단계에서 합의한 결정을 시간 순서대로 기록한다.

---

## M8-01 · Active Accepted Corpus / Embedding Unit Baseline

상태: **DECIDED**

### 1. M8 corpus의 authoritative source

M8 기본 corpus는 M7 SQLite의 모든 Knowledge가 아니다.

```text
knowledge_generation.state = 'active'
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Historical / candidate / review_required Generation과 accepted되지 않은 Attempt는 기본 embedding corpus에서 제외한다.

### 2. 기본 Embedding Unit

Pilot baseline은 다음으로 고정한다.

```text
Knowledge Item 1개
→ Embedding Unit 1개
```

근거:

```text
Knowledge Item       285
statement mean       114.01 chars
statement p95        206.4 chars
statement max        447 chars
```

현재 데이터에서는 이미 Knowledge Item이 짧은 atomic semantic unit으로 유지되고 있다.
모든 Item을 다시 Chunk하면 identity / Evidence mapping과 재현성만 복잡해질 가능성이 높다.

따라서 **기본 Chunk는 사용하지 않는다.**

### 3. Chunk를 추가할 수 있는 조건

Chunk는 기본 구조가 아니라 검증 결과에 따른 예외다.

다음 중 하나가 실데이터에서 확인될 때만 Chunk profile을 추가 검토한다.

- 실제 BGE-M3 tokenizer 기준으로 Item이 지나치게 길다.
- 한 statement가 독립 검색 의도를 여러 개 포함한다.
- Retrieval sanity test에서 분할이 일관되게 더 좋은 후보를 만든다.

단순 문자 길이 임계값만으로 현재 285 Item을 선제 분할하지 않는다.

### 4. Baseline Embedding Text

첫 text profile은 다음으로 고정한다.

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
```

이유:

- Knowledge Item 자체가 이미 검색용 의미 압축 결과다.
- Category나 Issue Summary를 모든 Item에 붙이면 같은 Issue의 Item들이 과도하게 비슷해질 수 있다.
- 원문 context를 임의로 늘리기보다 atomic statement의 검색성을 먼저 검증하는 편이 원인 분석이 쉽다.

다음 profile은 **후속 비교 실험 후보**이며 기본값이 아니다.

```text
category_statement_v1
issue_summary_category_statement_v1
```

실험 결과가 baseline보다 명확히 좋을 때만 기본 text profile 변경을 검토한다.

### 5. Corpus query 계약

논리 SQL:

```sql
SELECT
    ki.knowledge_item_id,
    ki.knowledge_attempt_id,
    ka.knowledge_generation_id,
    kg.issue_version_id,
    kg.jira_id,
    ki.category,
    ki.ordinal,
    ki.statement
FROM knowledge_generation AS kg
JOIN knowledge_attempt AS ka
  ON ka.knowledge_attempt_id = kg.accepted_attempt_id
JOIN knowledge_item AS ki
  ON ki.knowledge_attempt_id = ka.knowledge_attempt_id
WHERE kg.state = 'active'
  AND kg.accepted_attempt_id IS NOT NULL
  AND ka.content_available = 1;
```

Exporter는 DB row 순서에 의존하지 않고 deterministic sort를 적용한다.

```text
jira_id
→ category canonical order
→ ordinal
→ knowledge_item_id
```

Category canonical order:

```text
issue_summary
problem_or_goal
key_findings
actions_and_decisions
outcomes
open_items
```

### 6. Corpus artifact v0.1

Vector를 만들기 전 deterministic corpus row의 최소 계약:

```text
corpus_schema_version
text_profile
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
issue_version_id
jira_id
category
ordinal
embedding_text
embedding_text_hash
```

`embedding_text_hash`는 UTF-8 `embedding_text`의 SHA-256 lowercase hex다.

이 artifact에는 아직 vector를 넣지 않는다.
Corpus correctness와 text identity를 먼저 검증한 뒤 BGE-M3 adapter를 연결한다.

### 7. M8-01 Gate

```text
[ ] active accepted corpus exporter 구현
[ ] synthetic test에서 historical/candidate/review_required 제외 확인
[ ] accepted Attempt가 아닌 Item 제외 확인
[ ] deterministic ordering 확인
[ ] statement_v1 text canonicalization/hash 확인
[ ] 실제 M7 DB에서 corpus row = 285 확인
```

M8-01 Gate가 통과한 뒤 BGE-M3 request/response contract(M8-02)로 이동한다.

---

## 아직 결정하지 않은 것

다음은 M8-01에서 확정하지 않는다.

- Chunk size / overlap
- BGE-M3 축소 dimension
- embedding vector 영구 저장 형식
- FAISS index structure
- retrieval top-k

특히 FAISS는 M9 책임이다.

# M8 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE**

M8 · Embedding Unit / Chunk + BGE-M3 단계에서 합의한 결정을 시간 순서대로 기록한다.

---

## M8-01 · Active Accepted Corpus / Embedding Unit Baseline

상태: **PASS / DONE**

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

후속 비교 실험 후보:

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
 AND ka.knowledge_generation_id = kg.knowledge_generation_id
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

### 7. M8-01 Real DB Gate

최종 사용자 로컬 실행 결과:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

초기에 `corpus_rows: 28`로 전달된 값은 사용자의 복사/붙여넣기 과정에서 잘못 전달된 값이었고, 동일 명령의 실제 출력은 `285`임이 바로 정정됐다. 프로젝트 결함으로 취급하지 않는다.

최종 판정:

```text
[x] active accepted corpus exporter 구현
[x] synthetic test에서 historical/candidate/review_required 제외 확인
[x] accepted Attempt가 아닌 Item 제외 확인
[x] deterministic ordering 확인
[x] statement_v1 text canonicalization/hash 확인
[x] 실제 M7 DB에서 corpus row = 285 확인

M8-01 = PASS / DONE
```

---

## M8-02 · Deterministic Embedding Contract / BGE-M3 Adapter

상태: **DECIDED / IMPLEMENTATION NEXT**

### 1. Embedding Contract v0.1

Embedding artifact는 Knowledge identity와 분리한다.

```text
Knowledge identity
→ knowledge_item_id (ki_)

Embedding contract
→ ec_

Embedding artifact
→ emb_
```

Embedding Contract v0.1의 identity 입력:

```text
embedding_contract_version = 0.1
text_profile               = statement_v1
embedding_model            = BAAI/bge-m3
embedding_model_profile    = runtime supplied
embedding_dimension        = 1024
```

`embedding_model_profile`은 같은 model name 아래 실제 serving revision/deployment가 달라질 가능성을 구분하기 위한 필드다. 사내 API가 revision metadata를 제공하지 않는 경우 Pilot에서는 명시적으로 `internal-bge-m3-unversioned`처럼 "version metadata를 알 수 없음"을 기록한다.

Endpoint URL은 배포 위치 정보이므로 embedding logical identity에는 넣지 않는다.

### 2. Deterministic ID

공통 canonical JSON + SHA-256 규칙을 재사용한다.

```text
embedding_contract_hash
= ec_ + SHA256({
    id_schema_version,
    kind="embedding_contract",
    embedding_contract_version,
    text_profile,
    embedding_model,
    embedding_model_profile,
    embedding_dimension
  })

embedding_id
= emb_ + SHA256({
    id_schema_version,
    kind="embedding",
    knowledge_item_id,
    embedding_text_hash,
    embedding_contract_hash
  })
```

Vector 값 자체와 API endpoint는 `embedding_id` material에 넣지 않는다.

### 3. Request Contract

사내 API는 OpenAI-compatible embeddings API로 취급한다.

```json
{
  "model": "BAAI/bge-m3",
  "input": ["text1", "text2", "..."]
}
```

Endpoint는 코드에 하드코딩하지 않는다.

```text
BGE_M3_ENDPOINT
→ local .env / runtime environment

BGE_M3_API_KEY
→ 필요할 때만 local .env / Secret
```

API key가 제공되면 `Authorization: Bearer <token>`을 사용한다. 인증 방식이 다른 배포에서는 adapter의 header injection으로 분리한다.

### 4. Batch Contract

확인된 최대 HTTP batch size는 64다.

```text
285 corpus rows
→ 64 + 64 + 64 + 64 + 29
→ 총 5 requests
```

기본 batch size는 64로 두되 runtime에서 더 작은 값으로 낮출 수 있다. 64를 초과하는 값은 시작 전에 거부한다.

### 5. Response Mapping

OpenAI-compatible response의 `data[].index`를 authoritative input mapping으로 사용한다.

```text
request input position 0..N-1
↔ response data[].index
```

응답 배열의 물리 순서에 의존하지 않는다.

반드시 확인:

- index 누락 없음
- index 중복 없음
- 범위 밖 index 없음
- vector 개수 = request input 개수
- 각 vector dimension = 1024

### 6. Retry / Failure Contract

재시도 대상:

```text
network/timeout
HTTP 429
HTTP 500/502/503/504
```

재시도하지 않는 오류:

```text
HTTP 400/401/403/404 등 명백한 request/auth/config 오류
response schema 오류
vector dimension 오류
index mapping 오류
```

기본 총 시도 횟수는 3회로 둔다.

### 7. Publish Contract

Pilot 규모에서는 partial vector artifact를 최종 산출물로 publish하지 않는다.

```text
모든 batch 성공
→ 전체 mapping/dimension 검증
→ temp artifact 작성
→ atomic replace
→ final embedding artifact publish

중간 batch 실패
→ final artifact publish 금지
```

Resume/checkpoint는 M8에서 과설계하지 않고 후속 orchestration 단계에서 다룬다.

### 8. Embedding Artifact v0.1

M8-03에서 생성할 JSONL row 후보:

```text
embedding_schema_version
embedding_contract_version
embedding_contract_hash
embedding_id
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
issue_version_id
jira_id
category
ordinal
text_profile
embedding_text_hash
embedding_model
embedding_model_profile
embedding_dimension
vector
```

M9는 `embedding_id ↔ knowledge_item_id` mapping을 유지한 채 FAISS index를 만든다.

### 9. M8-02 Gate

```text
[ ] embedding contract / deterministic ID module 구현
[ ] OpenAI-compatible BGE-M3 client 구현
[ ] batch <= 64 강제
[ ] response index mapping 검증
[ ] 1024 dimension 검증
[ ] retry 대상/비대상 test
[ ] atomic publish helper 구현
[ ] CI PASS
```

---

## 아직 결정하지 않은 것

- Chunk size / overlap
- BGE-M3 축소 dimension
- FAISS index structure
- retrieval top-k
- production incremental embedding/resume orchestration

특히 FAISS는 M9 책임이다.

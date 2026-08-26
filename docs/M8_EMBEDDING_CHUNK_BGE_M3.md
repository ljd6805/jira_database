# M8 Embedding Unit / Chunk + BGE-M3

기준일: 2026-08-26  
상태: **CURRENT / M8-01 CORPUS BASELINE DECIDED**

M8은 M7 SQLite의 **active accepted Knowledge**를 검색용 embedding artifact로 변환하기 위한 단계를 설계하고 검증한다.

M8은 FAISS Retrieval 단계가 아니다. **Embedding Unit, Chunk 필요 조건, BGE-M3 호출/저장 계약**을 먼저 고정한다.

상세 결정 이력: `docs/M8_DECISION_LOG.md`

---

## 1. 입력 경계 · DECIDED

M8 입력은 M7 DB 전체가 아니라 기본 Retrieval 대상이다.

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Historical / candidate / review_required Generation과 accepted되지 않은 Attempt는 기본 embedding corpus에 넣지 않는다.

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

Exporter는 DB의 물리 row 순서에 의존하지 않고 deterministic ordering을 적용한다.

```text
jira_id
→ category canonical order
→ ordinal
→ knowledge_item_id
```

---

## 2. 기본 Embedding Unit · DECIDED

M8 Pilot baseline:

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

각 Item은 이미 검색 가치가 있는 atomic statement로 설계됐고 Evidence와 직접 연결돼 있다.

따라서 **M8 baseline에서는 Chunk를 사용하지 않는다.**

---

## 3. Chunk 책임 · BASELINE NO-CHUNK

Chunk는 기본 구조가 아니라 검증 결과에 따른 예외다.

다음 중 하나가 확인될 때만 Chunk profile을 추가 검토한다.

- 실제 BGE-M3 tokenizer 기준으로 Item이 지나치게 길다.
- 하나의 statement가 독립 검색 의도를 여러 개 포함한다.
- Retrieval sanity test에서 분할이 일관되게 더 좋은 후보를 만든다.

단순 문자 길이 임계값만으로 현재 285 Item을 선제 분할하지 않는다.

Chunk identity는 Knowledge identity를 대체하지 않는다.

```text
knowledge_item_id
→ authoritative Knowledge identity

embedding/chunk id
→ vector artifact identity
→ knowledge_item_id로 반드시 역참조 가능
```

---

## 4. BGE-M3 현재 확인 계약

사내 embedding API:

```text
Model
BAAI/bge-m3

Serving
Hugging Face Text Embeddings Inference (TEI)
OpenAI-compatible text embeddings API

Request max batch size
64

Dense embedding dimension
1024
```

축소 dimension 지원 여부는 아직 확정하지 않는다. 확인 전까지 1024-dim을 authoritative output으로 취급한다.

---

## 5. Corpus Artifact v0.1 · DECIDED

Vector를 만들기 전에 deterministic corpus를 먼저 만든다.

최소 row contract:

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

`embedding_text_hash`:

```text
UTF-8 embedding_text
→ SHA-256
→ lowercase hex
```

Corpus 단계에는 아직 vector를 넣지 않는다.

이유:

```text
DB corpus correctness
→ text identity
→ BGE-M3 adapter
```

순으로 문제를 분리하면, API 오류와 DB/query 오류를 섞지 않고 진단할 수 있다.

---

## 6. Baseline Embedding Text · DECIDED

첫 profile:

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
```

이유:

- Knowledge Item 자체가 이미 검색용 의미 압축 결과다.
- Category나 Issue Summary를 모든 Item에 붙이면 같은 Issue의 Item들이 과도하게 비슷해질 수 있다.
- atomic statement baseline을 먼저 잡아야 후속 text composition 효과를 해석하기 쉽다.

후속 비교 실험 후보:

```text
category_statement_v1
issue_summary_category_statement_v1
```

이 둘은 아직 기본값이 아니다.

---

## 7. M8 Validation 축

### A. Corpus correctness

- active accepted Knowledge만 포함
- historical/candidate/review_required 제외
- accepted Attempt가 아닌 Item 제외
- 실제 Pilot corpus row = 285 확인

### B. Identity

- 같은 input + 같은 text profile → 같은 `embedding_text_hash`
- 향후 같은 embedding contract → 같은 embedding identity
- embedding artifact에서 `knowledge_item_id`로 항상 역참조 가능

### C. API contract

- batch 최대 64 준수
- 실패/재시도 정책 정의
- 1024 dimension 검증
- 입력 순서와 응답 순서 mapping 보존

### D. Reproducibility

- embedding text canonicalization 고정
- model/contract metadata 보존
- partial failure 시 완료/미완료 구분 가능

### E. Quality sanity check

작은 실데이터 샘플로:

- 유사 Knowledge는 상대적으로 가까운지
- 무관 Knowledge는 분리되는지
- text profile 차이가 검색 후보 품질에 어떤 영향을 주는지 확인

M8에서는 대규모 Retrieval benchmark를 과설계하지 않는다.

---

## 8. M8 Gate

### M8-01 · Corpus Baseline

```text
[x] active accepted corpus query/contract 확정
[x] Knowledge Item = Embedding Unit 결정
[x] baseline Chunk 없음 결정
[x] statement_v1 text profile 결정
[ ] active accepted corpus exporter 구현
[ ] synthetic filtering/order/hash test
[ ] 실제 M7 DB에서 corpus row = 285 확인
```

### M8-02 · BGE-M3 Contract

```text
[ ] deterministic embedding contract / embedding_id 확정
[ ] BGE-M3 request/response adapter 구현
[ ] batch <= 64 검증
[ ] output dimension = 1024 검증
[ ] partial failure / retry 계약 확정
```

### M8-03 · Real Embedding Gate

```text
[ ] 실데이터 embedding 생성 성공
[ ] Knowledge Item ↔ Embedding mapping 무결성 확인
[ ] 재실행 시 identity/mapping 재현성 확인
[ ] 작은 quality sanity check
[ ] 문서/HTML 동기화
```

---

## 9. M9와의 경계

M8 출력:

```text
검증된 embedding artifact
+ Knowledge mapping
+ model/contract metadata
```

M9 입력:

```text
M8 embedding artifact
→ FAISS index
→ active Retrieval
→ Top-k
```

따라서 M8에서는 FAISS index/retrieval을 구현하지 않는다.

---

## 10. 현재 다음 액션

M8-01 구현 순서:

```text
1. active accepted corpus query를 Python module로 구현
2. deterministic corpus row / hash 생성
3. JSONL exporter 구현
4. synthetic test로 filtering/order/hash 검증
5. 실제 M7 SQLite에서 285 row 확인
6. M8-01 Gate PASS 후 BGE-M3 adapter contract로 이동
```

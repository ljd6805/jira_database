# M8 Embedding Unit / Chunk + BGE-M3

기준일: 2026-08-26  
상태: **CURRENT / DESIGN KICKOFF**

M8은 M7 SQLite의 **active accepted Knowledge**를 검색용 embedding artifact로 변환하기 위한 단계를 설계하고 검증한다.

M8은 FAISS Retrieval 단계가 아니다. **Embedding Unit, Chunk 필요 조건, BGE-M3 호출/저장 계약**을 먼저 고정한다.

---

## 1. 입력 경계

M8 입력은 M7 DB 전체가 아니라 기본 Retrieval 대상이다.

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
    ↓
knowledge_item
```

Historical Generation/Attempt는 기본 embedding corpus에 넣지 않는다.

---

## 2. 기본 Embedding Unit 후보

우선 검토 기본안:

```text
Knowledge Item 1개
→ Embedding Unit 1개
```

이유:

- M5 Pilot 기준 Knowledge Item 285개로 규모가 작다.
- 각 Item은 이미 검색 가치가 있는 atomic statement로 설계됐다.
- 각 Item에 Evidence가 연결돼 있다.
- 너무 이른 Chunk 분할은 identity/Evidence mapping을 복잡하게 만들 수 있다.

M8에서 검증할 질문:

```text
Knowledge Item 자체로 충분한가?
문장이 너무 길거나 복합적인 Item만 Chunk가 필요한가?
검색 문맥을 위해 category / issue summary를 text에 보강할 필요가 있는가?
```

모든 Item을 무조건 Chunk하지 않는다.

---

## 3. Chunk 책임

Chunk가 필요하다고 판단될 때만 추가한다.

Chunk 후보 조건 예:

- 단일 statement가 지나치게 길다.
- 하나의 Item이 독립 검색 단위를 여러 개 포함한다.
- embedding 품질 실험에서 분할이 유의미한 개선을 보인다.

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

## 5. M8에서 결정해야 할 데이터 계약

최소 artifact 필드 후보:

```text
embedding_id
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
jira_id / issue_version_id locator
category
ordinal
embedding_text
embedding_text_hash
embedding_model
embedding_dimension
embedding_contract_version
vector
```

실제 저장 형식은 설계 후 확정한다.

중요:

```text
Vector position / FAISS index
≠ Knowledge identity
```

M9가 index를 다시 만들어도 Knowledge/Embedding mapping을 복원할 수 있어야 한다.

---

## 6. Embedding Text 후보

최소안:

```text
statement
```

검토안:

```text
category + statement
```

또는 필요 시:

```text
issue summary context + category + statement
```

어떤 text composition이 검색 품질에 유리한지는 M8 실험으로 결정한다. 원문 전체를 무조건 붙이지 않는다.

---

## 7. M8 Validation 축

### A. Corpus correctness

- active accepted Knowledge만 포함
- historical/candidate/review_required 제외
- Knowledge Item count와 corpus mapping 검증

### B. Identity

- 같은 input + 같은 embedding contract → 같은 embedding identity
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
- Chunk/Text composition 차이가 검색 후보 품질에 어떤 영향을 주는지 확인

M8에서는 대규모 Retrieval benchmark를 과설계하지 않는다.

---

## 8. M8 Gate 초안

M8을 DONE으로 닫기 위한 최소 조건 초안:

```text
[ ] active accepted corpus 추출 query/contract 확정
[ ] embedding unit 결정
[ ] Chunk 적용 조건 확정
[ ] deterministic embedding identity 확정
[ ] BGE-M3 request/response adapter 구현
[ ] batch <= 64 검증
[ ] output dimension = 1024 검증
[ ] 실데이터 embedding 생성 성공
[ ] Knowledge Item ↔ Embedding 1:N mapping 무결성 확인
[ ] 재실행 시 identity/mapping 재현성 확인
[ ] 문서/HTML 동기화
```

Gate는 M8 설계/실험을 진행하며 수정할 수 있다. 변경 이유는 문서에 남긴다.

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

## 10. 첫 액션

M8은 구현 전에 다음 순서로 시작한다.

```text
1. M7 SQLite에서 active accepted Knowledge를 어떤 SQL/query로 꺼낼지 확인
2. 285 Knowledge Item 분포를 다시 확인
3. Embedding Text 후보 2~3개 정의
4. Chunk 필요 조건 가설 수립
5. BGE-M3 adapter contract 설계
6. 작은 샘플로 embedding 실험
7. 결과를 보고 최종 M8 contract 고정
```

# M9 FAISS + Active Retrieval

기준일: 2026-08-26  
상태: **CURRENT / M9-01 DESIGN FROZEN / M9-02 IMPLEMENTED · CI PASS / M9-03 REAL-RUN NEXT**

M9는 M8에서 검증된 285개의 BGE-M3 dense embedding을 **검색 가능한 active retrieval index**로 만들고, 사용자 질문을 같은 embedding 공간에 투영해 Top-k Knowledge 후보를 반환하는 단계다.

M9에서는 아직 Evidence Builder/MCP를 만들지 않는다. 책임은 다음까지다.

```text
질문
→ 같은 BGE-M3 query embedding
→ FAISS Top-k
→ score + embedding_id + knowledge_item_id
```

상세 결정 이력: `docs/M9_DECISION_LOG.md`

---

## 1. 입력 · M8 validated embedding artifact

M9의 authoritative input은 M8 final embedding JSONL이다.

```text
M7 SQLite active accepted Knowledge
    ↓
M8 corpus 285
    ↓
BGE-M3 1024-d embedding 285
    ↓
M8 artifact integrity PASS
    ↓
M9 FAISS
```

M8 최종 Gate:

```text
corpus_rows                  285
embedding_rows               285
unique knowledge_item_id     285
unique embedding_id          285
embedding contract             1
mapping failure                0
identity failure               0
dimension failure              0
non-finite vector              0
zero-norm vector               0
leftover temp artifact      false
```

M9 build는 이 상태를 과거 기록으로만 믿지 않는다. `corpus + embeddings`를 다시 읽어 M8 integrity Gate를 재실행한 뒤에만 index를 만든다.

---

## 2. M9-01 · Retrieval Contract — DESIGN FROZEN

### 2.1 Index type

```text
IndexFlatIP
```

현재 285개 Pilot에서는 exact exhaustive search를 baseline으로 사용한다.

이유:

- 285 × 1024 float32 ≈ 1.11 MiB
- training 불필요
- approximate recall 손실 없음
- 향후 ANN의 recall을 비교할 exact test oracle 확보

### 2.2 Similarity

```text
cosine similarity
= L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product search
```

M8 API vector가 이미 normalize됐다고 가정하지 않는다.

```text
M8 vector
→ float32 copy
→ L2 normalize
→ IndexFlatIP.add()

query
→ BGE-M3 1024-d
→ L2 normalize
→ IndexFlatIP.search()
```

원본 M8 embedding JSONL은 수정하지 않는다.

### 2.3 Query profile

```text
query_text_profile = raw_query_v1
query_text = user_query.strip()
model/profile/dimension = M8 source와 동일
```

query prefix/instruction은 baseline에 임의 추가하지 않는다.

### 2.4 Top-k

```text
default_top_k = 3
score_threshold = none
reranker = none
```

M8 semantic sanity에서 한 sample의 Top-3 cosine이 `0.5918 / 0.5908 / 0.5900`으로 매우 가까웠지만 후보 모두 의미상 타당했다. 따라서 Top-1 하나만 강제 선택하지 않는다.

### 2.5 Mapping

```text
faiss_position
    ↓
embedding_id (emb_)
    ↓
knowledge_item_id (ki_)
```

FAISS position은 artifact-local locator일 뿐 Knowledge identity가 아니다.

Canonical build order:

```text
embedding_id ascending
```

Source JSONL row 순서가 달라도 같은 embedding set이면 같은 mapping order를 만들기 위해서다.

### 2.6 Artifact set

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Mapping row:

```text
faiss_position
embedding_id
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
issue_version_id
category
ordinal
embedding_text_hash
```

Manifest 핵심:

```text
retrieval_schema_version
retrieval_contract_version
retrieval_contract_hash
faiss_index_id
index_type
metric
normalization
canonical_order
vector_count
dimension
source_embedding_contract_hash
source_embedding_artifact_sha256
mapping_sha256
faiss_binary_sha256
faiss_version
embedding_model
embedding_model_profile
query_text_profile
default_top_k
score_threshold_policy
rerank_policy
```

### 2.7 Identity

```text
Retrieval Contract  rc_
FAISS Index Artifact fi_
```

`rc_`는 검색 동작 계약을 식별한다.

```text
rc_ = H(
  contract version,
  index type,
  metric,
  index/query normalization,
  query text profile,
  Top-k / threshold / rerank policy,
  embedding model/profile/dimension
)
```

`fi_`는 source embedding snapshot + index build profile을 식별한다.

```text
fi_ = H(
  source_embedding_artifact_sha256,
  index_type,
  metric,
  normalization,
  dimension
)
```

FAISS binary SHA-256은 integrity metadata지만 logical `fi_` 입력은 아니다.

### 2.8 Update policy

Pilot에서는 incremental add/delete를 하지 않는다.

```text
새 active Knowledge
→ M8 validated embedding artifact 재생성
→ M9 full rebuild
```

현재 규모에서는 mutable index 관리보다 stale vector 제거와 재현성 단순화 이점이 크다.

---

## 3. Flat은 영구 고정이 아니라 Exact Baseline

`IndexFlatIP`는 최종 확장 전략이 아니라 test oracle이다.

대략적인 raw vector memory:

```text
10,000 vectors      ≈ 39 MiB
100,000 vectors     ≈ 391 MiB
1,000,000 vectors   ≈ 3.81 GiB
```

Flat 검색은 query마다 전체 vector를 비교하므로 규모와 QPS가 커지면 CPU/latency 부담이 증가한다.

ANN 검토 trigger:

```text
p95 search latency > 서비스 목표
index RAM > 운영 budget
예상 QPS에서 CPU saturation
rebuild/reload 시간 > 운영 목표
Flat search가 end-to-end query 병목
```

우선 비교 후보:

```text
IndexHNSWFlat
IndexIVFFlat
```

전환은 고정 vector 개수가 아니라:

```text
Flat exact 결과
vs
ANN 결과
→ recall@k + latency + memory
```

로 결정한다.

Index type이 바뀌어도:

```text
embedding_id → knowledge_item_id → Evidence
```

계약은 유지한다.

---

## 4. M9-02 · 구현 — IMPLEMENTED / CI PASS

### 4.1 의존성

```text
numpy >= 1.26, < 3.0
faiss-cpu >= 1.15, < 2.0
```

2026-08-26 기준 `faiss-cpu 1.15.0`은 Windows x86-64 CPython 3.11/3.12 wheel을 제공한다.

### 4.2 코드 구조

```text
src/jira_collector/retrieval/
├─ contract.py
├─ source.py
├─ artifact.py
├─ validation.py
├─ search.py
├─ query.py
└─ __init__.py

tools/jira_knowledge/
├─ build_faiss_index.py
├─ validate_m9_retrieval_artifact.py
└─ search_faiss.py
```

### 4.3 Build flow

```text
M8 corpus + embedding
→ M8 integrity 재검증
→ embedding_id ascending sort
→ float32 copy
→ L2 normalize
→ IndexFlatIP.add
→ index.faiss.tmp
→ index.mapping.jsonl.tmp
→ load / count / dimension / norm 검증
→ index + mapping replace
→ index.manifest.json LAST publish
```

Manifest가 마지막 publish marker다.

중간 crash가 나서 index만 바뀌고 old manifest가 남아도 SHA가 맞지 않으므로 loader가 해당 artifact를 거부한다.

### 4.4 Runtime validation

검색기는 artifact를 열기 전에:

```text
manifest schema
rc_ / fi_ recomputation
index SHA-256
mapping SHA-256
IndexFlatIP / METRIC_INNER_PRODUCT
ntotal / dimension
mapping count / contiguous position
embedding_id canonical order / uniqueness
knowledge_item_id uniqueness
L2 norm ≈ 1
leftover temp 없음
```

을 검사한다.

Real Gate에서는 M8 source까지 추가로 비교해 mapping이 실제 source row와 동일한지도 확인한다.

### 4.5 Query guard

실제 query API 호출 전에:

```text
manifest.embedding_model
manifest.embedding_model_profile
manifest.dimension
```

과 runtime embedding 설정이 정확히 같은지 비교한다.

다르면 다른 vector 공간을 검색하지 않도록 즉시 실패한다.

### 4.6 Search result

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M9는 candidate identity + score까지만 책임진다.

---

## 5. Synthetic CI Gate — PASS

자동 테스트:

```text
[x] rc_ deterministic
[x] fi_ deterministic
[x] source hash 변경 시 fi_ 변경
[x] baseline 외 index type 차단
[x] M8 source re-validation
[x] embedding_id canonical order
[x] L2-normalized IndexFlatIP build
[x] exact cosine Top-k ranking
[x] same source rebuild → same rc_ / fi_
[x] same source rebuild → same mapping bytes
[x] mapping corruption → hash/mapping Gate 실패
[x] query model/profile/dimension mismatch 차단
[x] GitHub Actions pytest PASS
```

FAISS binary 자체의 byte-for-byte 동일성은 logical idempotency Gate로 요구하지 않는다. library/platform serialization 차이가 있을 수 있기 때문이다.

---

## 6. M9-03 · Real Retrieval Gate — NEXT

### 6.1 Real Build

```text
[ ] vector_count = 285
[ ] dimension = 1024
[ ] mapping_rows = 285
[ ] unique embedding_id = 285
[ ] unique knowledge_item_id = 285
[ ] contract_failure_count = 0
[ ] hash_failure_count = 0
[ ] mapping_failure_count = 0
[ ] dimension_failure_count = 0
[ ] normalization_failure_count = 0
[ ] temp_artifact_exists = false
```

### 6.2 Rebuild reproducibility

```text
[ ] same M8 source → same rc_
[ ] same M8 source → same fi_
[ ] same M8 source → same canonical mapping bytes
```

### 6.3 Real query

```text
[ ] actual BGE-M3 query embedding
[ ] query L2 normalization
[ ] Top-3 exact retrieval
[ ] emb_ ↔ ki_ mapping integrity
[ ] same query 재실행 ranking 재현
[ ] 대표 query semantic sanity
[ ] dense-neighborhood case 관찰
[ ] 문서/HTML 최종 sync
```

---

## 7. 실행 명령

### Index build

```powershell
python tools/jira_knowledge/build_faiss_index.py `
  --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl `
  --embeddings data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl `
  --output-dir data/retrieval/runs/20260804T043628Z `
  --expected-count 285 `
  --expected-dimension 1024
```

### Artifact validation

```powershell
python tools/jira_knowledge/validate_m9_retrieval_artifact.py `
  --artifact-dir data/retrieval/runs/20260804T043628Z `
  --embeddings data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl `
  --expected-count 285 `
  --expected-dimension 1024
```

### Real query

```powershell
python tools/jira_knowledge/search_faiss.py `
  --artifact-dir data/retrieval/runs/20260804T043628Z `
  --query "<검색 질문>" `
  --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl
```

`--corpus`를 주면 semantic sanity를 위해 Top-k Knowledge text를 로컬 화면에 표시한다. 실제 Jira-derived text는 공개 문서에 복사하지 않는다.

---

## 8. M10과의 경계

**M9에서는 Evidence Builder/MCP를 구현하지 않는다.**

```text
M9 output
→ rank + cosine score + emb_ + ki_

M10
→ ki_ → Knowledge statement
→ ke_ → Evidence source
→ Evidence package
→ MCP
```

M9-03 real retrieval Gate를 닫은 뒤 M10으로 이동한다.

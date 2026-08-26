# M9 FAISS + Active Retrieval

기준일: 2026-08-26  
상태: **CURRENT / DESIGN / IMPLEMENTATION NOT STARTED**

M9는 M8에서 검증된 285개의 BGE-M3 dense embedding을 **정확한 active retrieval index**로 만들고, 사용자 질문을 같은 embedding 공간에 투영해 Top-k Knowledge 후보를 반환하는 단계다.

M9에서는 아직 Evidence Builder/MCP를 만들지 않는다. **검색 후보를 정확히 찾고 `FAISS → embedding_id → knowledge_item_id` mapping을 보존하는 것**이 책임이다.

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

M9는 이 검증을 통과하지 않은 embedding artifact를 index 입력으로 받지 않는다.

---

## 2. M9 목적

```text
질문 text
   ↓ same BGE-M3 model/profile
query vector 1024-d
   ↓ L2 normalize
FAISS exact cosine search
   ↓
Top-k embedding candidates
   ↓
embedding_id
   ↓
knowledge_item_id
```

M9가 보장해야 하는 것:

- 검색 대상은 M8의 active accepted Knowledge만이다.
- FAISS position은 Knowledge identity가 아니다.
- 검색 결과는 항상 `embedding_id → knowledge_item_id`로 역참조 가능하다.
- 같은 index와 같은 query contract에서 결과를 재현할 수 있어야 한다.
- M10이 Evidence를 붙일 수 있도록 candidate identity를 보존한다.

---

## 3. Index Type · PROPOSED BASELINE

### 결정안

```text
IndexFlatIP
```

이유:

- Pilot vector 수는 285개뿐이다.
- dimension은 1024다.
- 정확한 exhaustive search가 가능하다.
- training이 필요 없다.
- IVF/HNSW/PQ의 recall/parameter 복잡성을 지금 도입할 이유가 없다.
- exact baseline을 먼저 만들어야 나중에 approximate index를 도입해도 품질 손실을 측정할 수 있다.

대략적인 raw vector memory:

```text
285 × 1024 × 4 bytes
≈ 1,167,360 bytes
≈ 1.11 MiB
```

현재 규모에서는 memory 최적화가 설계 제약이 아니다.

FAISS 공식 문서도 `IndexFlatIP`를 exact inner-product search로 설명하고, normalize한 vector에서는 cosine similarity에 사용할 수 있다고 명시한다.

참고:

- https://github.com/facebookresearch/faiss/wiki/Faiss-indexes
- https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances

### 3.1 Flat은 영구 고정이 아니라 Exact Baseline

`IndexFlatIP`는 현재 Pilot의 최종 확장 전략이 아니다.

```text
현재
→ Flat exact baseline
→ recall 100% 기준선 확보

향후 규모 증가
→ Flat latency / memory / CPU / QPS 측정
→ 필요하면 ANN 후보 benchmark
→ HNSW / IVF 계열로 교체 가능
```

중요한 원칙은 **“N개가 넘으면 무조건 ANN” 같은 고정 숫자를 계약으로 박지 않는 것**이다.

1024-d float32 raw vector만 계산해도:

```text
10,000 vectors   ≈ 39 MiB
100,000 vectors  ≈ 391 MiB
1,000,000 vectors ≈ 3.81 GiB
```

Flat 검색은 query마다 모든 vector를 비교하므로 `N × dimension`에 비례해 검색 비용이 증가한다. 데이터 수뿐 아니라 동시 query 수가 늘어도 CPU 부담이 커진다.

### 3.2 ANN 전환 Trigger

다음 중 하나가 실제 운영 benchmark에서 발생하면 ANN 도입을 검토한다.

```text
p95 search latency > 서비스 목표
index RAM > 운영 memory budget
예상 QPS에서 CPU saturation 발생
index reload / rebuild 시간이 운영 요구를 초과
Flat exact search가 전체 query latency의 주요 병목이 됨
```

첫 scaling benchmark checkpoint는 corpus가 수만~수십만 단위로 커질 때 잡는 것을 권고하지만, **전환 여부는 개수 자체가 아니라 측정값으로 결정**한다.

### 3.3 우선 비교할 ANN 후보

#### HNSWFlat

장점:

- 별도 training 없이 graph index 구성 가능
- 높은 recall과 빠른 query latency를 얻기 쉬움
- `efSearch`로 speed/accuracy trade-off 조정 가능

단점:

- Flat보다 추가 memory가 필요함
- FAISS HNSW는 vector remove를 직접 지원하지 않으므로 update 전략에 제약이 있음

#### IndexIVFFlat

장점:

- query 시 일부 inverted list만 검색해 큰 N에서 검색량 감소
- 원 vector를 그대로 보존하므로 PQ보다 정확도 손실 원인이 단순함
- `nprobe`로 speed/accuracy trade-off 조정 가능

단점:

- training 필요
- `nlist`, `nprobe` tuning 필요
- recall이 Flat exact보다 낮아질 수 있음

M9 baseline의 Flat 결과를 **정답 기준(test oracle)** 으로 보존하면 이후:

```text
ANN Top-k
vs
Flat Top-k
```

를 비교해 recall@k와 latency를 함께 측정할 수 있다.

### 3.4 Retrieval Contract는 index 교체 가능하게 설계

따라서 M9 contract에서 `index_type`을 identity에 포함한다.

```text
rc_ / fi_
├─ index_type = IndexFlatIP
├─ metric = cosine
└─ normalization = l2
```

향후:

```text
IndexFlatIP
→ IndexHNSWFlat
또는
→ IndexIVFFlat
```

로 바뀌어도 `embedding_id → knowledge_item_id` mapping과 M10 인터페이스는 유지한다.

즉 **검색 엔진 내부 구조만 교체하고 상위 Knowledge/Evidence 계약은 흔들리지 않게 하는 것**이 M9 설계 목표다.

---

## 4. Similarity Metric · PROPOSED BASELINE

M8 semantic sanity는 cosine similarity로 확인했다. M9도 같은 의미를 유지한다.

```text
metric = cosine similarity
```

FAISS에서는:

```text
DB vector
→ float32 copy
→ L2 normalize
→ IndexFlatIP.add()

query vector
→ float32
→ L2 normalize
→ IndexFlatIP.search()
```

따라서 FAISS가 반환하는 inner product score를 cosine similarity로 해석한다.

중요:

- M8 API가 이미 normalize된 vector를 반환한다고 가정하지 않는다.
- M9 index build에서 항상 copy를 만들고 L2 normalize한다.
- 원본 M8 embedding JSONL의 vector 값은 수정하지 않는다.

---

## 5. Query Embedding Contract · PROPOSED

질문도 Knowledge와 **같은 BGE-M3 model/profile/dimension**을 사용한다.

```text
query_text_profile = raw_query_v1
query_text = user_query.strip()
model = BAAI/bge-m3
model_profile = M8과 동일
dimension = 1024
```

현재 baseline에서는 query prefix/instruction을 임의로 추가하지 않는다.

이유:

- 현재 M8 baseline이 `statement_v1`로 검증됐다.
- query instruction 효과를 검증하지 않은 상태에서 추가하면 원인 분리가 어렵다.
- 필요하면 M9 quality experiment에서 별도 query profile로 비교한다.

---

## 6. Top-k Policy · PROPOSED BASELINE

```text
default_top_k = 3
score_threshold = 없음
reranker = 없음
```

근거:

- 초기 Retrieval 계획도 Top-3 후보를 LLM에 전달하는 방향이었다.
- M8 semantic sanity의 Sample 3에서 Top-3 cosine이 `0.5918 / 0.5908 / 0.5900`으로 매우 가까웠지만 세 후보 모두 의미상 타당했다.
- 따라서 Top-1 하나만 강제 선택하면 의미적으로 유효한 후보를 버릴 수 있다.
- cosine absolute score의 전역 threshold는 아직 실측 근거가 없다.

M9 baseline에서는 **Top-3를 그대로 반환**하고, threshold/reranking은 후속 실측 결과가 필요할 때만 도입한다.

---

## 7. FAISS Position / Mapping Contract · PROPOSED

FAISS가 반환하는 숫자 label/position은 artifact-local locator일 뿐 Knowledge identity가 아니다.

```text
faiss_position
    ↓ mapping sidecar
embedding_id (emb_)
    ↓
knowledge_item_id (ki_)
```

### Canonical index order

M9 build 시 embedding row를 다음으로 정렬한다.

```text
embedding_id ascending
```

같은 embedding set이면 source JSONL row 순서와 무관하게 같은 mapping order를 만들기 위해서다.

### Mapping JSONL

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

Mapping에는 vector나 raw statement를 중복 저장하지 않는다.

Knowledge statement/Evidence가 필요하면 `knowledge_item_id`로 SQLite를 조회한다.

---

## 8. Retrieval Artifact · PROPOSED

M9 index artifact는 세 파일로 구성한다.

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

### Manifest 최소 계약

```text
retrieval_schema_version
retrieval_contract_version
retrieval_contract_hash
faiss_index_id
index_type
metric
normalization
vector_count
dimension
source_embedding_contract_hash
source_embedding_artifact_sha256
mapping_sha256
faiss_binary_sha256
faiss_version
query_text_profile
default_top_k
score_threshold_policy
rerank_policy
```

`index.manifest.json`은 **publish marker** 역할도 한다.

```text
index.tmp + mapping.tmp 작성
→ load/search/mapping validation
→ index/mapping replace
→ manifest를 마지막에 atomic publish
```

manifest가 없거나 hash가 맞지 않으면 검색기는 index를 유효한 artifact로 취급하지 않는다.

---

## 9. Deterministic Identity · PROPOSED

M9도 logical artifact identity를 분리한다.

```text
Retrieval Contract  rc_
FAISS Index Artifact fi_
```

### Retrieval Contract

```text
rc_ = H(
  retrieval_contract_version,
  index_type,
  metric,
  index_normalization,
  query_normalization,
  query_text_profile,
  default_top_k,
  score_threshold_policy,
  rerank_policy,
  embedding_model,
  embedding_model_profile,
  dimension
)
```

### FAISS Index Artifact

```text
fi_ = H(
  source_embedding_artifact_sha256,
  index_type,
  metric,
  normalization,
  dimension
)
```

`faiss_position`은 identity material이 아니다.

FAISS binary byte hash는 reproducibility metadata로 기록하되, library/platform에 따라 serialization 차이가 생길 수 있으므로 logical `fi_`의 직접 입력으로 사용하지 않는다.

---

## 10. Active-only / Rebuild Policy · PROPOSED

Pilot에서는 **incremental add/delete를 하지 않는다.**

```text
새 active Knowledge / 새 embedding 발생
→ M8 validated embedding artifact 재생성
→ M9 index 전체 rebuild
```

이유:

- 현재 285개라 전체 rebuild 비용이 매우 작다.
- stale/historical vector를 제거하는 로직이 단순해진다.
- mutable index 상태보다 immutable source artifact 기반 재현성이 높다.

M9 search 시 SQLite의 active state를 매 query마다 재필터링하지 않는다.

대신:

```text
M8 artifact = build 시점의 active accepted snapshot
M9 index    = 그 artifact의 immutable search representation
```

production incremental indexing은 별도 규모/운영 근거가 생길 때 설계한다.

---

## 11. Search Result Contract · PROPOSED

M9 retrieval 결과 최소 형태:

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M9는 candidate 검색까지만 책임진다.

```text
M9
→ Top-k candidate identity + score

M10
→ SQLite Knowledge/Evidence resolve
→ Evidence package
→ MCP
```

M9에서 LLM reranking이나 Evidence package를 미리 구현하지 않는다.

---

## 12. Reproducibility / Idempotency Gate

같은 validated embedding artifact + 같은 M9 contract에서:

```text
vector_count 동일
mapping order 동일
retrieval_contract_hash 동일
faiss_index_id 동일
같은 query → 같은 Top-k identity 순서
score는 float tolerance 안에서 동일
```

FAISS binary file 자체의 byte-for-byte 동일성은 필수 Gate로 두지 않는다.

---

## 13. M9 Gate Proposal

### M9-01 · Design Freeze

```text
[ ] IndexFlatIP baseline 확정
[ ] Flat은 exact baseline이며 ANN 확장 가능하다는 scaling policy 확정
[ ] cosine = L2 normalize + inner product 확정
[ ] canonical embedding_id order 확정
[ ] mapping / manifest contract 확정
[ ] rc_ / fi_ identity 확정
[ ] default Top-3 / no threshold / no reranker 확정
[ ] full rebuild / active snapshot 정책 확정
```

### M9-02 · Index Build

```text
[ ] faiss-cpu dependency 추가
[ ] validated M8 artifact loader
[ ] L2 normalization
[ ] IndexFlatIP build
[ ] mapping JSONL
[ ] manifest + hash validation
[ ] atomic publish marker
[ ] ntotal = 285 / d = 1024
[ ] rebuild semantic idempotency
```

### M9-03 · Real Retrieval Gate

```text
[ ] 실제 query BGE-M3 embedding
[ ] query normalization
[ ] Top-3 exact retrieval
[ ] emb_ ↔ ki_ mapping 무결성
[ ] 같은 query 재실행 ranking 재현
[ ] 대표 query semantic sanity
[ ] dense-neighborhood case 관찰
[ ] 문서/HTML 최종 sync
```

---

## 14. M10과의 경계

**M9에서는 Evidence Builder/MCP를 구현하지 않는다.**

```text
M9 output
→ rank + cosine score + emb_ + ki_

M10
→ ki_ → Knowledge statement
→ ke_ → Evidence source
→ Agent/MCP용 evidence package
```

---

## 15. 구현 전 확인할 결정

현재 권고 baseline:

```text
Index       IndexFlatIP (exact baseline)
Metric      cosine
Normalize   DB/query 모두 L2
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Update      full rebuild
Mapping     FAISS position → emb_ → ki_
Publish     index + mapping + manifest-last
Scaling     latency/RAM/QPS 기준 충족 못하면 HNSW/IVF benchmark 후 전환
```

이 계약을 확정한 뒤 M9-02 구현으로 이동한다.

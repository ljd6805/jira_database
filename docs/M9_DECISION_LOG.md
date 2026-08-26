# M9 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE / M9-01 APPROVED / M9-02 IMPLEMENTED · CI PASS**

M9 · FAISS + Active Retrieval에서 합의한 검색 계약과 구현 결정을 기록한다.

---

## M9-01 · Exact Retrieval Baseline

상태: **APPROVED / DESIGN FROZEN**

### D1. Index type

```text
IndexFlatIP
```

Pilot 285개에서는 exact exhaustive search를 baseline으로 사용한다.

근거:

- 285 × 1024 float32 ≈ 1.11 MiB
- training 불필요
- approximate recall 손실 없음
- 향후 ANN recall을 비교할 exact test oracle 확보

### D1-A. Scaling policy

`IndexFlatIP`는 영구 고정 구조가 아니라 **exact baseline / test oracle**이다.

```text
현재 285
→ Flat exact

향후 규모 증가
→ Flat latency / RAM / QPS / rebuild benchmark
→ 필요하면 HNSW / IVF benchmark
→ recall@k + latency + memory를 보고 전환
```

고정 vector 개수만으로 ANN 전환을 결정하지 않는다.

ANN 검토 trigger:

```text
p95 search latency가 서비스 목표 초과
index RAM이 운영 budget 초과
예상 QPS에서 CPU saturation
rebuild/reload 시간이 운영 목표 초과
Flat search가 end-to-end query 병목
```

우선 비교 후보:

- `IndexHNSWFlat`: training 없이 높은 recall/빠른 검색을 얻기 쉽지만 memory overhead와 remove 제약이 있다.
- `IndexIVFFlat`: 큰 N에서 일부 inverted list만 검색할 수 있지만 training과 `nlist/nprobe` tuning이 필요하다.

중요:

```text
IndexFlatIP → HNSW/IVF로 교체되어도
embedding_id → knowledge_item_id → Evidence 계약은 유지
```

### D2. Similarity

```text
cosine similarity
= L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product search
```

M8 vector가 이미 normalized라고 가정하지 않는다. M9에서 복사본을 normalize한다.

### D3. Query profile

```text
query_text_profile = raw_query_v1
query_text = query.strip()
```

모델/프로필/차원은 M8과 동일한 BGE-M3 contract를 사용한다. query prefix는 baseline에 추가하지 않는다.

### D4. Top-k

```text
default_top_k = 3
score_threshold = none
reranker = none
```

M8 dense-neighborhood 사례에서 Top-3가 거의 동률이지만 모두 의미상 타당했다. Top-1만 강제하지 않는다.

### D5. Mapping

```text
faiss_position
→ embedding_id
→ knowledge_item_id
```

Canonical build order:

```text
embedding_id ascending
```

FAISS position은 Knowledge identity가 아니다.

### D6. Artifact set

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

manifest는 마지막에 publish해 완료 marker로 사용한다.

### D7. Identity

```text
Retrieval Contract  rc_
FAISS Index Artifact fi_
```

`rc_`는 검색 동작 계약, `fi_`는 source embedding snapshot + index build profile을 식별한다.

### D8. Active policy

Pilot은 incremental add/delete를 하지 않는다.

```text
새 active embedding artifact
→ M9 full rebuild
```

### D9. M10 boundary

M9 output은 candidate identity + score까지다.

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

Knowledge statement/Evidence resolve와 MCP는 M10 책임이다.

### M9-01 승인 결과

```text
[x] D1 IndexFlatIP exact baseline 승인
[x] D1-A 측정 기반 ANN scaling policy 승인
[x] D2 cosine/L2 normalize 승인
[x] D3 raw_query_v1 승인
[x] D4 Top-3 / no threshold / no reranker 승인
[x] D5 embedding_id canonical order / mapping 승인
[x] D6 index+mapping+manifest artifact 승인
[x] D7 rc_ / fi_ identity 승인
[x] D8 full rebuild active snapshot 승인
[x] D9 M10 boundary 승인

M9-01 = DESIGN FROZEN
```

---

## M9-02 · Index Build / Search Implementation

상태: **IMPLEMENTED / CI PASS**

### I1. Dependency

```text
numpy >= 1.26, < 3.0
faiss-cpu >= 1.15, < 2.0
```

2026-08-26 확인 기준 `faiss-cpu 1.15.0`은 Windows x86-64 CPython 3.11/3.12 wheel을 제공한다.

### I2. Source Gate

M9 build는 M8 완료 기록만 믿지 않고 현재 입력 파일을 다시 검증한다.

```text
M8 corpus + M8 embeddings
→ validate_embedding_artifact()
→ PASS일 때만 build
```

### I3. Canonical build

```text
embedding_id ascending
→ float32 copy
→ L2 normalize
→ IndexFlatIP.add()
```

원본 M8 vector JSONL은 변경하지 않는다.

### I4. Atomic artifact

```text
index.faiss.tmp
index.mapping.jsonl.tmp
→ load/count/dimension/norm validation
→ index / mapping replace
→ index.manifest.json LAST publish
```

manifest에는 source/index/mapping SHA-256과 `rc_`, `fi_`, FAISS version을 저장한다.

### I5. Runtime validation

검색기는 artifact open 시:

```text
manifest contract
rc_ / fi_ recomputation
index SHA-256
mapping SHA-256
IndexFlatIP / METRIC_INNER_PRODUCT
count / dimension
canonical mapping order
ID uniqueness
L2 normalization
leftover temp
```

을 검증한다.

### I6. Query contract guard

query embedding API 호출 전에:

```text
embedding_model
embedding_model_profile
dimension
```

이 manifest와 runtime 설정에서 동일한지 확인한다. 다른 vector space는 즉시 거부한다.

### I7. 구현 위치

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

### I8. Synthetic CI Gate

```text
[x] deterministic rc_ / fi_
[x] source SHA 변경 시 fi_ 변경
[x] unapproved index type 차단
[x] M8 source integrity re-validation
[x] embedding_id canonical order
[x] L2-normalized IndexFlatIP build
[x] exact cosine Top-k search
[x] rebuild → same rc_ / fi_ / mapping bytes
[x] mapping corruption detection
[x] query model/profile/dimension mismatch 차단
[x] GitHub Actions pytest PASS

M9-02 = IMPLEMENTED / CI PASS
```

---

## M9-03 · Real Retrieval Gate

상태: **NEXT**

실제 Pilot에서 확인할 항목:

```text
[ ] vector_count = 285
[ ] dimension = 1024
[ ] mapping_rows = 285
[ ] unique embedding_id = 285
[ ] unique knowledge_item_id = 285
[ ] contract/hash/mapping failure = 0
[ ] dimension/normalization failure = 0
[ ] temp artifact = false
[ ] same source rebuild → same rc_ / fi_ / mapping
[ ] actual BGE-M3 query → Top-3 exact retrieval
[ ] same query ranking reproducibility
[ ] representative semantic sanity
[ ] dense-neighborhood case observation
[ ] documentation final sync
```

---

## External verification

FAISS 공식 문서 기준:

- `IndexFlatIP`는 exact inner-product search다.
- database/query vector를 normalize하면 cosine similarity search로 사용할 수 있다.
- Flat index는 training이 필요 없다.
- IVF/HNSW는 non-exhaustive search이며 `nprobe` / `efSearch`로 speed-accuracy trade-off를 조절한다.

참고:

- https://github.com/facebookresearch/faiss/wiki/Faiss-indexes
- https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances
- https://github.com/facebookresearch/faiss/wiki/FAQ
- https://pypi.org/project/faiss-cpu/

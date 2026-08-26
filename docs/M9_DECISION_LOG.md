# M9 Decision Log

기준일: 2026-08-26  
상태: **DONE / PASS**

M9 · FAISS + Active Retrieval에서 합의한 검색 계약, 구현 결정, 실환경 검증, 정식 서비스 확장 방향을 기록한다.

---

## D1 · Pilot Index

```text
IndexFlatIP
```

Pilot 285개에서는 exact exhaustive search를 사용한다. 현재 규모에서 approximate recall 손실을 도입할 이유가 없고, 향후 ANN 품질을 비교할 exact test oracle이 필요하기 때문이다.

---

## D2 · Similarity

```text
cosine
= L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product
```

M8 vector가 이미 normalized라고 가정하지 않는다. FAISS용 복사본만 normalize한다.

---

## D3 · Query Contract

```text
query_text_profile = raw_query_v1
query_text = query.strip()
model/profile/dimension = M8과 동일
```

---

## D4 · Candidate Policy

```text
default_top_k = 3
score_threshold = none
reranker = none
```

실제 두 query case에서 Rank 1/2는 유효했고 Rank 3에는 noise가 있었다. Case 2는 Rank 2와 Rank 3 score 차이가 작지만 의미 품질은 달랐다. 따라서 global cosine threshold를 임의 도입하지 않는다.

---

## D5 · Mapping

```text
faiss_position
→ embedding_id
→ knowledge_item_id
```

Pilot canonical order:

```text
embedding_id ascending
```

FAISS position은 stable identity가 아니다.

---

## D6 · Artifact / Publish

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Manifest를 마지막에 publish해 완료 marker로 사용한다. Index/mapping SHA가 manifest와 다르면 검색기가 거부한다.

---

## D7 · Retrieval Identity

```text
Retrieval Contract  rc_
FAISS Index Artifact fi_
```

- `rc_`: 검색 동작 계약 identity
- `fi_`: source embedding snapshot + build profile identity
- `faiss_position`: identity material 아님
- FAISS binary SHA: 물리 integrity metadata

---

## D8 · Pilot Update Policy

Pilot에서는 full rebuild를 사용한다.

```text
same source + same contract
→ full rebuild
→ same rc_ / fi_ / mapping 확인
```

이 정책은 deterministic/integrity/reproducibility 검증을 위한 Pilot baseline이다.

---

## D9 · M10 Boundary

M9 output:

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M10 responsibility:

```text
ki_ → Knowledge statement
ke_ → Evidence source
→ Evidence package
→ MCP
```

---

## D10 · Production Update Policy — DELTA FIRST

상태: **DIRECTION APPROVED / IMPLEMENTATION LATER**

정식 서비스에서는 전체 Knowledge를 매번 embedding하거나 FAISS 전체를 매번 rebuild하지 않는다.

```text
unchanged
→ 기존 embedding/index 유지

added
→ vector cache 확인
→ 필요 시 BGE-M3
→ index add

changed
→ old remove/tombstone
→ cache/embed
→ new add

removed/inactive
→ remove/tombstone
```

Vector cache 후보:

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

Incremental exact index 후보:

```text
IndexIDMap2(IndexFlatIP)
+ stable int64 vector_id
```

Stable `vector_id`는 SQLite에서 collision 없이 관리하는 방식을 우선한다.

Full rebuild는 유지한다.

```text
평상시       delta update
주기적/필요시 full rebuild
```

Full rebuild 용도:

- tombstone / fragmentation 정리
- mapping/index integrity 재검증
- index type migration
- embedding contract 변경
- 대규모 backfill
- 장애 복구

---

## D11 · Scaling / ANN

`IndexFlatIP`는 exact test oracle이다.

규모가 커져 다음이 문제가 되면 ANN을 benchmark한다.

```text
p95 latency
RAM
QPS / CPU saturation
rebuild/reload time
```

우선 후보:

```text
IndexHNSWFlat
IndexIVFFlat
```

전환은 Flat 대비 `recall@k + latency + memory + throughput` 측정으로 결정한다.

HNSW는 FAISS에서 vector remove를 직접 지원하지 않으므로 tombstone/filter + periodic rebuild 전략이 필요할 수 있다.

---

## M9-02 · Implementation Result

```text
[x] M8 source integrity re-validation
[x] canonical embedding_id order
[x] L2-normalized IndexFlatIP
[x] deterministic rc_ / fi_
[x] manifest-last publish
[x] index/mapping SHA validation
[x] exact cosine Top-3
[x] mapping corruption detection
[x] query model/profile/dimension guard
[x] synthetic rebuild reproducibility
[x] GitHub Actions pytest PASS
```

---

## M9-03 · Real Validation Result

### Real Build

```text
[x] vector_count = 285
[x] dimension = 1024
[x] mapping_failure_count = 0
[x] hash_failure_count = 0
[x] normalization_failure_count = 0
```

### Rebuild

```text
[x] same rc_
[x] same fi_
[x] same source SHA
[x] same mapping SHA
[x] same binary SHA · same environment observation
```

### Real Query

```text
[x] distinct query Case 1
[x] distinct query Case 2
[x] Rank 1/2 semantic quality acceptable
[x] Top-3 noise observation
```

### Same-query Reproducibility

```text
vector_exact_equal=True
max_abs_diff=0
cosine=1.000000000
ranking_equal=True
scores_exact_equal=True
```

---

## Final Decision

```text
M9-01 DESIGN       PASS
M9-02 IMPLEMENT    PASS
M9-03 REAL RUN     PASS

M9 = DONE / PASS
M10 = NEXT / DESIGN NOT STARTED
```

새 세션은 `docs/status/M10_START_HERE.html`부터 읽고 M10 설계를 시작한다.

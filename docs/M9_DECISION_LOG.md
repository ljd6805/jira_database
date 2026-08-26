# M9 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE / DESIGN**

M9 · FAISS + Active Retrieval에서 구현 전에 합의할 검색 계약을 기록한다.

---

## M9-01 · Exact Retrieval Baseline

상태: **PROPOSED / REVIEW BEFORE IMPLEMENTATION**

### D1. Index type

```text
IndexFlatIP
```

Pilot 285개에서는 exact exhaustive search를 baseline으로 사용한다. IVF/HNSW/PQ는 현재 도입하지 않는다.

근거:

- 285 × 1024 float32 ≈ 1.11 MiB
- training 불필요
- approximate recall 손실 없음
- 나중에 approximate index를 비교할 exact 기준점 확보

### D2. Similarity

```text
cosine similarity
= L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product search
```

M8 vector가 이미 normalized라고 가정하지 않는다. M9에서 원본을 복사한 뒤 normalize한다.

### D3. Query profile

```text
query_text_profile = raw_query_v1
query_text = query.strip()
```

모델/프로필/차원은 M8과 동일한 BGE-M3 contract를 사용한다. query instruction/prefix는 baseline에 추가하지 않는다.

### D4. Top-k

```text
default_top_k = 3
score_threshold = none
reranker = none
```

M8 semantic sanity에서 의미상 타당한 Top-3가 매우 가까운 점수를 가진 dense-neighborhood 사례가 확인됐다. 따라서 Top-1만 강제 선택하지 않는다.

### D5. Mapping

```text
faiss_position
→ embedding_id
→ knowledge_item_id
```

FAISS position은 artifact-local locator이며 Knowledge identity가 아니다.

Canonical build order:

```text
embedding_id ascending
```

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

`rc_`는 index/search 동작 계약을 식별하고, `fi_`는 source embedding artifact와 index build profile을 식별한다.

### D8. Active policy

Pilot은 incremental add/delete를 하지 않는다.

```text
새 active embedding artifact
→ M9 full rebuild
```

현재 규모에서는 full rebuild가 단순하고 stale vector 제거에도 안전하다.

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

---

## External verification

FAISS 공식 문서 기준:

- `IndexFlatIP`는 exact inner-product search다.
- database/query vector를 normalize하면 cosine similarity search로 사용할 수 있다.
- Flat index는 training이 필요 없다.

참고:

- https://github.com/facebookresearch/faiss/wiki/Faiss-indexes
- https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances

2026-08-26 확인 기준 PyPI `faiss-cpu 1.15.0`은 Windows x86-64 CPython 3.11/3.12 wheel을 제공한다.

- https://pypi.org/project/faiss-cpu/

---

## 구현 전 Gate

```text
[ ] D1 IndexFlatIP 승인
[ ] D2 cosine/L2 normalize 승인
[ ] D3 raw_query_v1 승인
[ ] D4 Top-3 / no threshold / no reranker 승인
[ ] D5 embedding_id canonical order / mapping 승인
[ ] D6 index+mapping+manifest artifact 승인
[ ] D7 rc_ / fi_ identity 승인
[ ] D8 full rebuild active snapshot 승인
[ ] D9 M10 boundary 승인
```

승인 후 M9-02 implementation을 시작한다.

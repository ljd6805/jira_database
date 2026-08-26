# M9 FAISS + Active Retrieval

기준일: 2026-08-26  
상태: **DONE / PASS**

M9는 M8에서 검증된 BGE-M3 embedding을 검색 가능한 active retrieval index로 만들고, 질문을 같은 vector space에 투영해 Top-k Knowledge 후보를 반환하는 단계다.

```text
질문
→ 같은 BGE-M3 query embedding
→ FAISS Top-3
→ score + embedding_id + knowledge_item_id
```

M10에서 Knowledge/Evidence resolve와 MCP를 구현한다.

---

## 1. Pilot Retrieval Contract · FINAL

```text
Index       IndexFlatIP
Metric      cosine
Normalize   DB/query 모두 L2
Query       raw_query_v1 = query.strip()
Order       embedding_id ascending
Top-3       exact candidates
Threshold   none
Reranker    none
Update      full rebuild · Pilot only
```

Cosine은 DB/query vector를 L2 normalize한 뒤 `IndexFlatIP` inner product로 계산한다. 원본 M8 embedding artifact는 수정하지 않는다.

---

## 2. Identity / Artifact

```text
Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_
```

```text
faiss_position
→ embedding_id (emb_)
→ knowledge_item_id (ki_)
```

`faiss_position`은 stable identity가 아니다.

Artifact:

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Manifest는 `rc_`, `fi_`, source embedding SHA-256, mapping/index SHA-256, FAISS version, vector_count/dimension, query profile을 기록하고 마지막에 publish된다.

---

## 3. M9-02 Implementation · PASS

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
├─ search_faiss.py
└─ diagnose_query_reproducibility.py
```

검증:

```text
[x] M8 source integrity re-validation
[x] embedding_id canonical order
[x] L2-normalized IndexFlatIP
[x] deterministic rc_ / fi_
[x] exact cosine Top-3
[x] manifest/hash/mapping validation
[x] mapping corruption detection
[x] query model/profile/dimension guard
[x] synthetic rebuild reproducibility
[x] GitHub Actions pytest PASS
```

---

## 4. M9-03 Real Gate · PASS

### Real Build

```text
vector_count: 285
dimension: 1024
mapping_failure_count: 0
hash_failure_count: 0
normalization_failure_count: 0
```

### Same-source Rebuild

```text
same rc_        PASS
same fi_        PASS
same source SHA PASS
same mapping SHA PASS
```

### Real Query Semantic Sanity

```text
Case 1
rank1 좋음 / rank2 좋음 / rank3 어색함

Case 2
rank1 좋음 / rank2 괜찮음 / rank3 어색함
```

두 사례 모두 Rank 1/2는 유효했고 Rank 3에는 noise가 있었다. 특히 Case 2는 Rank 2와 Rank 3 score가 가까웠지만 의미 품질은 달랐다. 따라서 global cosine threshold를 근거 없이 추가하지 않는다.

### Same-query Reproducibility

```text
vector_exact_equal=True
max_abs_diff=0
cosine=1.000000000
ranking_equal=True
scores_exact_equal=True
```

따라서 동일 질문 → 동일 vector → 동일 ranking → 동일 score가 재현된다.

```text
M9 = DONE / PASS
```

---

## 5. 정식 서비스 · DELTA-FIRST 방향

Pilot full rebuild는 운영 기본 정책이 아니다.

```text
unchanged → reuse
added     → cache check → embed if needed → add
changed   → old remove/tombstone → cache/embed → add
removed   → remove/tombstone
```

같은 text + 같은 embedding contract vector는 재사용 가능하도록 다음 cache key를 후속 production-hardening에서 검토한다.

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

Incremental exact index 후보:

```text
IndexIDMap2(IndexFlatIP)
+ stable int64 vector_id
```

`IndexHNSWFlat` / `IndexIVFFlat` 전환은 p95 latency, RAM, QPS, rebuild 시간, recall@k 측정 후 결정한다. `IndexFlatIP`는 exact test oracle로 유지한다.

```text
운영 기본 = delta-first
full rebuild = maintenance / recovery / migration / backfill
```

---

## 6. M10 Boundary

M9 output:

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M10:

```text
ki_ → Knowledge statement
ke_ → Evidence source
→ Evidence package
→ MCP
```

M10은 새 세션에서 DESIGN부터 시작한다. 공식 인수인계 문서:

```text
docs/status/M10_START_HERE.html
```

---

## 7. FAISS 운영 근거

- `IndexFlatIP`: exact inner-product search, L2 normalize 시 cosine 사용 가능
- `IndexIDMap` / `IndexIDMap2`: explicit ID 추가 가능
- sequential Flat remove: 뒤 번호 이동 가능
- `IndexIDMap2` / IVF: explicit ID 기반 remove 가능
- HNSW: vector remove 직접 지원하지 않음

향후 index 구현이 바뀌어도 `embedding_id → knowledge_item_id → Evidence` 계약은 유지한다.

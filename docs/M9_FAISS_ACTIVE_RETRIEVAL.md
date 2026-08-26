# M9 FAISS + Active Retrieval

기준일: 2026-08-26  
상태: **CURRENT / M9-01 DESIGN FROZEN / M9-02 IMPLEMENTED · CI PASS / M9-03 REAL BUILD PASS / REBUILD NEXT**

M9는 M8에서 검증된 BGE-M3 embedding을 검색 가능한 active retrieval index로 만들고, 질문을 같은 vector space에 투영해 Top-k Knowledge 후보를 반환하는 단계다.

```text
질문
→ 같은 BGE-M3 query embedding
→ FAISS Top-k
→ score + embedding_id + knowledge_item_id
```

M10에서 Knowledge/Evidence resolve와 MCP를 구현한다.

---

## 1. Pilot Retrieval Contract · FROZEN

```text
Index       IndexFlatIP
Metric      cosine
Normalize   DB/query 모두 L2
Query       raw_query_v1 = query.strip()
Order       embedding_id ascending
Top-3       exact candidates
Threshold   none
Reranker    none
Update      full rebuild (Pilot only)
```

Cosine은 DB/query vector를 L2 normalize한 뒤 `IndexFlatIP`의 inner product로 계산한다. 원본 M8 embedding artifact는 수정하지 않는다.

---

## 2. Identity / Artifact

```text
Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_
```

Pilot mapping:

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

## 3. M9-02 · IMPLEMENTED / CI PASS

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

자동 검증:

```text
[x] M8 source integrity re-validation
[x] embedding_id canonical order
[x] L2-normalized IndexFlatIP
[x] deterministic rc_ / fi_
[x] exact cosine Top-3
[x] manifest/hash/mapping validation
[x] same-source synthetic rebuild reproducibility
[x] mapping corruption detection
[x] query model/profile/dimension mismatch guard
[x] GitHub Actions pytest PASS
```

---

## 4. Pilot Full Rebuild의 의미

현재 Pilot에서는 새 active snapshot이 생기면 전체 index를 다시 만든다.

```text
new active snapshot
→ full M8 embedding artifact
→ full M9 rebuild
```

이 방식은 **정식 서비스 운영 정책이 아니다.** 파일럿에서 full rebuild를 쓰는 목적은 동일 입력의 결정성, mapping/identity 무결성, stale vector 제거 단순화, exact baseline 확보에 있다.

---

## 5. 정식 서비스 · DELTA-FIRST Update Policy

정식 서비스에서는 신규/변경/비활성분만 처리한다.

```text
변경 없음
→ 아무 작업 없음

새 Knowledge
→ 새 embedding만 생성
→ index add

변경 Knowledge
→ old 검색 entry 제거/비활성
→ 필요한 embedding만 생성 또는 재사용
→ new entry add

삭제/비활성 Knowledge
→ index entry 제거/비활성
```

변경 감지는 기존 구조를 활용한다.

```text
jira_id
→ source_hash / issue_version
→ active knowledge_generation
→ accepted knowledge_attempt
→ knowledge_item
→ embedding_text_hash
```

변경되지 않은 Issue/Knowledge는 다시 처리하지 않는다.

### Embedding vector cache

같은 text + 같은 embedding contract라면 BGE-M3 vector는 재사용할 수 있다.

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

```text
새 ki_ / 새 emb_ lineage
+ 같은 text hash + 같은 ec_
→ 기존 vector 재사용
→ BGE-M3 API 호출 생략
```

`emb_`는 lineage identity, vector cache는 계산 비용 절감 계층이다.

### Incremental FAISS ID

현재 bare `IndexFlatIP`는 순차 position을 사용하므로 remove 시 뒤 번호가 이동할 수 있다. 운영형 exact 후보는 다음이다.

```text
IndexIDMap2(IndexFlatIP)
+ stable int64 vector_id

vector_id
↔ embedding_id
↔ knowledge_item_id
```

Stable `vector_id`는 SQLite에서 collision 없이 관리하는 방식을 우선한다.

`IndexIVFFlat`로 확장해도 explicit ID mapping을 유지할 수 있다. `IndexHNSWFlat`은 FAISS에서 vector remove를 직접 지원하지 않으므로 HNSW를 선택할 경우 tombstone/active filter + periodic rebuild가 필요하다.

### Production delta flow

```text
Jira delta 수집
→ changed issue/version만 Knowledge pipeline
→ old active vs new active diff
   ├─ unchanged → reuse
   ├─ added     → cache check → embed if needed → add
   ├─ changed   → old remove/tombstone → cache/embed → add
   └─ removed   → remove/tombstone
```

---

## 6. Full Rebuild의 정식 서비스 역할

정식 서비스에서도 full rebuild는 유지한다.

```text
평상시        delta update
주기적/필요시 full rebuild
```

용도:

- tombstone/fragmentation 정리
- index/mapping integrity 재검증
- embedding contract 변경
- index type migration
- 대규모 backfill
- 장애 복구

```text
운영 기본 = delta-first
full rebuild = maintenance / recovery / migration
```

---

## 7. Scaling / ANN

`IndexFlatIP`는 exact baseline/test oracle이다. 규모가 커져 p95 latency, RAM, QPS, rebuild 시간이 목표를 넘으면 `IndexHNSWFlat` / `IndexIVFFlat`을 benchmark한다.

```text
Flat Top-k = exact reference
ANN Top-k  = candidate
→ recall@k + latency + memory + throughput
```

Index 구현이 바뀌어도 `embedding_id → knowledge_item_id → Evidence` 계약은 유지한다.

---

## 8. M9-03 Real Gate

첫 실제 Build:

```text
validation: PASS
vector_count: 285
dimension: 1024
retrieval_contract_hash: rc_6b9fc7222abbf08ff5861fbb73ab31cc37a12cd78585313d05e2645e7603dd77
faiss_index_id: fi_b544c57a560cec99069be46b6ee8f2047841b522ddf81681d3cd6027baa65b2d
source_embedding_artifact_sha256: 45c363194defbb0e7095c32ecd462e749c943d4524ec7dd6acda093260abe2f8
mapping_sha256: 9e546845b97307d095dd1ff3ec3ab3e4262dcf9b0a1444cbcd4391e0837e947b
mapping_failure_count: 0
hash_failure_count: 0
normalization_failure_count: 0
```

```text
M9-03 Real Build = PASS
```

### NEXT · Rebuild reproducibility

```text
[ ] same source rebuild → same rc_
[ ] same source rebuild → same fi_
[ ] same source rebuild → same mapping_sha256
```

그 다음:

```text
[ ] actual BGE-M3 query → Top-3 exact retrieval
[ ] same query ranking reproducibility
[ ] representative semantic sanity
[ ] dense-neighborhood observation
[ ] documentation final sync
```

---

## 9. M10 경계

```text
M9 output
→ rank + cosine score + emb_ + ki_

M10
→ ki_ → Knowledge statement
→ ke_ → Evidence source
→ Evidence package
→ MCP
```

---

## 10. FAISS 운영 근거

FAISS 공식 문서 기준:

- `IndexFlatIP`는 exact inner-product search이며 L2 normalize한 vector에서는 cosine에 사용 가능
- Flat은 자체 explicit ID를 저장하지 않지만 `IndexIDMap` / `IndexIDMap2`로 explicit ID 추가 가능
- sequential Flat의 remove는 뒤 번호를 이동시킬 수 있음
- `IndexIDMap2` / IVF는 explicit ID 기반 remove 가능
- HNSW는 vector remove를 직접 지원하지 않음

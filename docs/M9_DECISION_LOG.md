# M9 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE / M9-01 APPROVED / M9-02 IMPLEMENTED · CI PASS / M9-03 REAL BUILD PASS**

M9 · FAISS + Active Retrieval에서 합의한 검색 계약, 구현 결정, 실환경 검증, 정식 서비스 확장 정책을 기록한다.

---

## M9-01 · Exact Retrieval Baseline

상태: **APPROVED / DESIGN FROZEN**

### D1. Pilot index

```text
IndexFlatIP
```

Pilot 285개에서는 exact exhaustive search를 사용한다.

근거:

- 285 × 1024 float32 ≈ 1.11 MiB
- training 불필요
- approximate recall 손실 없음
- 향후 ANN recall을 비교할 exact test oracle 확보

`IndexFlatIP`는 영구 고정 구조가 아니다. 규모가 커지면 p95 latency, RAM, QPS, rebuild 시간과 recall@k를 측정해 `IndexHNSWFlat` / `IndexIVFFlat` 등을 benchmark한다.

### D2. Similarity

```text
cosine similarity
= L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product search
```

M8 vector가 이미 normalized라고 가정하지 않는다. FAISS용 복사본만 normalize하고 원본 artifact는 수정하지 않는다.

### D3. Query profile

```text
query_text_profile = raw_query_v1
query_text = query.strip()
model/profile/dimension = M8과 동일
```

### D4. Candidate policy

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

Pilot canonical build order:

```text
embedding_id ascending
```

FAISS position은 stable Knowledge identity가 아니다.

### D6. Artifact

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Manifest는 마지막에 publish해 완료 marker로 사용한다.

### D7. Identity

```text
Retrieval Contract  rc_
FAISS Index Artifact fi_
```

- `rc_`: index type / metric / normalization / query profile / Top-k / model-profile-dimension 등 검색 동작 계약의 ID
- `fi_`: source embedding snapshot + index build profile의 논리 artifact ID
- `faiss_position`: identity material이 아님
- FAISS binary SHA-256: 물리 파일 integrity metadata이며 logical `fi_` 입력은 아님

### D8. Pilot update policy

Pilot에서는 incremental add/delete를 하지 않는다.

```text
새 active embedding snapshot
→ M9 full rebuild
```

이 정책은 **파일럿 검증용 baseline**이다. 정식 서비스 운영 정책은 아래 D10에서 별도로 정의한다.

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

Knowledge statement / Evidence resolve와 MCP는 M10 책임이다.

### M9-01 승인 결과

```text
[x] IndexFlatIP exact baseline
[x] cosine/L2 normalize
[x] raw_query_v1
[x] Top-3 / no threshold / no reranker
[x] embedding_id canonical mapping
[x] index + mapping + manifest
[x] rc_ / fi_ identity
[x] Pilot full rebuild
[x] M10 boundary

M9-01 = DESIGN FROZEN
```

---

## D10 · 정식 서비스 Update Policy — DELTA FIRST

상태: **PRODUCTION DIRECTION APPROVED / IMPLEMENTATION LATER**

정식 서비스에서는 전체 Knowledge를 매번 다시 embedding하거나 FAISS 전체를 매번 rebuild하지 않는다.

### 기본 원칙

```text
변경 없음
→ 아무 작업 없음

새 Knowledge
→ 새 embedding만 생성
→ index add

변경된 Knowledge
→ 필요한 embedding만 생성/재사용
→ old 검색 entry 비활성/제거
→ new entry add

삭제/비활성 Knowledge
→ 검색 entry 비활성/제거
```

### 변경 감지 기준

기존 DB 계약을 그대로 활용한다.

```text
jira_id
→ source_hash / issue_version
→ active knowledge_generation
→ accepted knowledge_attempt
→ knowledge_item
→ embedding_text_hash
```

Issue가 그대로면 재처리하지 않는다. Issue가 바뀌더라도 최종 embedding text가 같다면 vector API를 다시 호출하지 않는 방향을 우선한다.

### Embedding vector 재사용

현재 `emb_` identity에는 `knowledge_item_id`가 포함되므로 새 Attempt/Item identity가 생기면 `emb_`는 새로 생길 수 있다. 하지만 실제 vector 값은 같은 text + 같은 embedding contract라면 재사용할 수 있다.

정식 서비스에서는 다음과 같은 **vector cache key**를 별도 도입하는 것을 권고한다.

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

의미:

```text
새 ki_ / 새 emb_ identity
하지만 embedding_text_hash + ec_ 동일
→ BGE-M3 API 재호출 없이 기존 vector 재사용 가능
```

`vector_cache_key`는 `emb_`를 대체하지 않는다. `emb_`는 Knowledge lineage를 보존하고, cache key는 계산 비용 절감을 위한 실행 최적화다.

### Incremental FAISS의 stable ID

현재 Pilot의 bare `IndexFlatIP`는 sequential position을 사용한다. FAISS 공식 문서상 Flat index에서 remove하면 뒤 순번이 이동할 수 있으므로 정식 서비스의 incremental mutation에는 부적합하다.

운영형 exact baseline 후보:

```text
IndexIDMap2(IndexFlatIP)
+ explicit int64 vector_id
```

권고 mapping:

```text
vector_id(int64)
↔ embedding_id(emb_)
↔ knowledge_item_id(ki_)
```

`emb_` SHA-256을 단순 잘라 int64로 쓰기보다 SQLite에서 collision 없이 관리되는 stable `vector_id`를 부여하는 방식을 우선한다.

FAISS 공식 문서상 `IndexIDMap2`는 explicit ID를 저장하고 `remove_ids`를 지원해 다른 ID를 밀어내지 않는다. `IndexIVF` 계열도 explicit ID 기반 운영이 가능하다. 반면 HNSW는 vector remove를 직접 지원하지 않으므로 HNSW를 선택할 경우 tombstone/filter + 주기적 rebuild 전략이 필요하다.

### Production update flow

```text
Jira delta 수집
→ changed issue/version만 Knowledge pipeline 실행
→ 이전 active snapshot vs 새 active snapshot diff
   ├─ unchanged
   │    → 기존 embedding/index 유지
   ├─ added
   │    → vector cache 확인 → 필요 시 BGE-M3 → index add
   ├─ changed
   │    → old vector_id remove/tombstone
   │    → cache 확인 → new vector add
   └─ removed/inactive
        → old vector_id remove/tombstone
```

### Full rebuild의 역할

정식 서비스에서도 full rebuild를 없애지는 않는다.

```text
평상시       delta update
주기적/필요시 full rebuild
```

Full rebuild 용도:

- tombstone / fragmentation 정리
- mapping/index integrity 재검증
- index type 변경
- embedding contract 변경
- 대규모 backfill
- 장애 복구

즉 **운영 기본 = delta-first, full rebuild = maintenance / recovery / migration** 으로 구분한다.

---

## M9-02 · Index Build / Search Implementation

상태: **IMPLEMENTED / CI PASS**

현재 Pilot 구현:

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

구현/CI 확인:

```text
[x] M8 source integrity re-validation
[x] embedding_id canonical order
[x] L2-normalized IndexFlatIP
[x] deterministic rc_ / fi_
[x] manifest-last publish
[x] index/mapping SHA validation
[x] exact cosine Top-k
[x] same-source rebuild synthetic reproducibility
[x] mapping corruption detection
[x] query model/profile/dimension guard
[x] GitHub Actions pytest PASS
```

정식 서비스 delta update / IDMap2 / vector cache는 현재 Pilot M9-02 범위 밖이며 후속 production-hardening 단계에서 구현한다.

---

## M9-03 · Real Retrieval Gate

상태: **CURRENT / REAL BUILD PASS / REBUILD NEXT**

첫 실제 FAISS Build:

```text
validation: PASS
vector_count: 285
dimension: 1024
retrieval_contract_hash: rc_6b9fc7222abbf08ff5861fbb73ab31cc37a12cd78585313d05e2645e7603dd77
faiss_index_id: fi_b544c57a560cec99069be46b6ee8f2047841b522ddf81681d3cd6027baa65b2d
source_embedding_artifact_sha256: 45c363194defbb0e7095c32ecd462e749c943d4524ec7dd6acda093260abe2f8
mapping_sha256: 9e546845b97307d095dd1ff3ec3ab3e4262dcf9b0a1444cbcd4391e0837e947b
faiss_binary_sha256: b54e172b2a9d302b8ad6003cd3f56680021cc64f6d0e2ea619f537395055cec2
mapping_failure_count: 0
hash_failure_count: 0
normalization_failure_count: 0
```

판정:

```text
M9-03 Real Build = PASS
```

남은 Pilot Gate:

```text
[ ] same source rebuild → same rc_ / fi_ / mapping
[ ] actual BGE-M3 query → Top-3 exact retrieval
[ ] same query ranking reproducibility
[ ] representative semantic sanity
[ ] dense-neighborhood observation
[ ] documentation final sync
```

---

## External verification

FAISS 공식 문서 기준:

- `IndexFlatIP`는 exact inner-product search이며 normalize한 vector에서는 cosine에 사용할 수 있다.
- Flat index는 자체 explicit vector ID를 저장하지 않지만 `IndexIDMap` / `IndexIDMap2`로 explicit ID를 추가할 수 있다.
- sequential Flat에서 remove하면 뒤 번호가 이동한다.
- `IndexIDMap2`와 IVF는 explicit ID를 보존하면서 remove가 가능하다.
- HNSW는 vector remove를 직접 지원하지 않는다.

참고:

- https://github.com/facebookresearch/faiss/wiki/Faiss-indexes
- https://github.com/facebookresearch/faiss/wiki/Special-operations-on-indexes
- https://github.com/facebookresearch/faiss/wiki/Pre--and-post-processing
- https://github.com/facebookresearch/faiss/wiki/The-index-factory

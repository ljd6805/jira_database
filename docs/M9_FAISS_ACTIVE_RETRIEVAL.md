# M9 FAISS + Active Retrieval

기준일: 2026-08-26  
상태: **CURRENT / M9-01 DESIGN FROZEN / M9-02 IMPLEMENTED · CI PASS / M9-03 REAL BUILD PASS**

M9는 M8에서 검증된 BGE-M3 embedding을 검색 가능한 active retrieval index로 만들고, 질문을 같은 vector space에 투영해 Top-k Knowledge 후보를 반환하는 단계다.

M9 책임:

```text
질문
→ 같은 BGE-M3 query embedding
→ FAISS Top-k
→ score + embedding_id + knowledge_item_id
```

M10에서 Knowledge/Evidence resolve와 MCP를 구현한다.

---

## 1. 입력

```text
M7 active accepted Knowledge
→ M8 corpus 285
→ BGE-M3 1024-d embedding 285
→ M8 artifact integrity PASS
→ M9 FAISS
```

M9 build 직전에도 M8 corpus + embedding integrity를 다시 검증한다.

---

## 2. Pilot Retrieval Contract · FROZEN

```text
Index       IndexFlatIP
Metric      cosine
Normalize   DB/query 모두 L2
Query       raw_query_v1 = query.strip()
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Update      full rebuild (Pilot only)
```

Cosine 구현:

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

M8 원본 embedding JSONL은 수정하지 않는다.

---

## 3. Identity / Mapping

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

`rc_`는 검색 규칙의 논리 ID이고, `fi_`는 source embedding snapshot + index build profile의 논리 ID다.

---

## 4. Artifact

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Mapping은 position → emb_ → ki_ lineage를 보존한다.

Manifest는 다음을 보존한다.

```text
rc_ / fi_
source embedding SHA-256
source embedding contract hash
mapping SHA-256
FAISS binary SHA-256
FAISS version
vector_count / dimension
query profile / Top-k policy
```

Publish:

```text
index.tmp + mapping.tmp
→ load/count/dimension/norm validation
→ index + mapping replace
→ manifest LAST publish
```

Manifest/hash가 맞지 않으면 검색기가 artifact를 거부한다.

---

## 5. M9-02 구현 · CI PASS

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
[x] exact cosine Top-k
[x] manifest/hash/mapping validation
[x] same-source synthetic rebuild reproducibility
[x] mapping corruption detection
[x] query model/profile/dimension mismatch guard
[x] GitHub Actions pytest PASS
```

---

## 6. Pilot Full Rebuild의 의미

현재 Pilot에서는 새 active snapshot이 생기면 M9 index 전체를 다시 만든다.

```text
new active snapshot
→ full M8 embedding artifact
→ full M9 rebuild
```

이 방식은 **정식 서비스 운영 정책이 아니다.**

Pilot에서 full rebuild를 쓰는 목적:

- 같은 입력 → 같은 logical result 확인
- stale vector 제거 단순화
- mapping/identity 검증
- exact baseline 확보
- 장애 원인 분리

---

## 7. 정식 서비스 · DELTA-FIRST Update Policy

정식 서비스에서는 신규/변경/비활성분만 처리한다.

```text
변경 없음
→ 아무 작업 없음

새 Knowledge
→ 새 embedding만 생성
→ index add

변경된 Knowledge
→ 필요한 embedding만 생성/재사용
→ old 검색 entry 제거/비활성
→ new entry add

삭제/비활성 Knowledge
→ 검색 entry 제거/비활성
```

### 7.1 변경 감지

기존 identity/version 계약을 활용한다.

```text
jira_id
→ source_hash / issue_version
→ active knowledge_generation
→ accepted knowledge_attempt
→ knowledge_item
→ embedding_text_hash
```

변경되지 않은 Issue/Knowledge는 다시 처리하지 않는다.

### 7.2 Embedding API도 변경 text만

Issue Version이나 Knowledge Item identity가 바뀌었다고 반드시 BGE-M3 API를 다시 호출할 필요는 없다.

같은 text + 같은 embedding contract라면 vector는 재사용 가능하다.

Production optimization 후보:

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

```text
새 ki_ / 새 emb_ lineage
하지만 같은 text hash + 같은 ec_
→ 기존 vector 재사용
→ BGE-M3 API 호출 생략
```

`vector_cache_key`는 `emb_` identity를 대체하지 않는다. lineage identity와 계산 cache를 분리한다.

### 7.3 Incremental FAISS ID

현재 bare `IndexFlatIP`는 순차 position을 사용한다. Flat에서 remove하면 뒤 position이 당겨질 수 있으므로 정식 서비스 incremental update에는 별도 explicit ID가 필요하다.

운영형 exact 후보:

```text
IndexIDMap2(IndexFlatIP)
+ stable int64 vector_id
```

```text
vector_id(int64)
↔ embedding_id(emb_)
↔ knowledge_item_id(ki_)
```

`vector_id`는 SQLite에서 collision 없이 관리하는 stable ID를 우선한다.

향후 `IndexIVFFlat`로 전환해도 explicit ID mapping은 유지할 수 있다.

HNSW는 FAISS에서 vector remove를 직접 지원하지 않으므로 HNSW를 선택할 경우:

```text
tombstone / active filter
+ periodic rebuild
```

전략이 필요하다.

### 7.4 Production delta flow

```text
Jira delta 수집
→ changed issue/version만 Knowledge pipeline
→ old active vs new active diff
   ├─ unchanged → reuse
   ├─ added     → cache check → embed if needed → add
   ├─ changed   → old remove/tombstone → cache/embed → add
   └─ removed   → remove/tombstone
```

### 7.5 Full rebuild는 유지한다

정식 서비스에서도 full rebuild는 없애지 않는다.

```text
평상시        delta update
주기적/필요시 full rebuild
```

Full rebuild 용도:

- tombstone/fragmentation 정리
- index/mapping integrity 재검증
- embedding contract 변경
- index type migration
- 대규모 backfill
- 장애 복구

즉:

```text
운영 기본 = delta-first
full rebuild = maintenance / recovery / migration
```

---

## 8. Scaling / ANN

`IndexFlatIP`는 exact baseline/test oracle이다.

규모가 커져 다음이 문제가 되면 ANN을 검토한다.

```text
p95 search latency > 목표
index RAM > budget
QPS에서 CPU saturation
rebuild/reload 시간 > 목표
Flat search가 end-to-end 병목
```

우선 비교:

```text
IndexHNSWFlat
IndexIVFFlat
```

전환 판단:

```text
Flat Top-k = exact reference
ANN Top-k  = candidate
→ recall@k + latency + memory + throughput
```

Index 구현이 바뀌어도 `emb_ → ki_ → Evidence` 계약은 유지한다.

---

## 9. M9-03 Real Gate

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

## 10. M10 경계

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

## 11. FAISS 관련 운영 근거

FAISS 공식 문서 기준:

- `IndexFlatIP`는 exact inner-product search이며 L2 normalize한 vector에서는 cosine에 사용 가능
- Flat은 자체 explicit ID를 저장하지 않지만 `IndexIDMap` / `IndexIDMap2`로 explicit ID 추가 가능
- sequential Flat의 remove는 뒤 번호를 이동시킬 수 있음
- `IndexIDMap2` / IVF는 explicit ID 기반 remove 가능
- HNSW는 vector remove를 직접 지원하지 않음

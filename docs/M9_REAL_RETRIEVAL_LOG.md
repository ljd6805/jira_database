# M9 Real FAISS Retrieval Validation Log

기준일: 2026-08-26  
상태: **DONE / PASS**

이 문서는 M9-03 실제 Pilot FAISS index 생성, rebuild 재현성, 실제 BGE-M3 query retrieval 검증 결과를 기록한다. 실제 Jira 본문, Issue Key, 사내 endpoint/header 값은 기록하지 않는다.

---

## 1. 입력

M8에서 검증 완료한 active accepted embedding artifact를 사용했다.

```text
corpus_rows      285
embedding_rows   285
dimension        1024
mapping failure  0
identity failure 0
vector integrity PASS
```

---

## 2. 첫 Real FAISS Build · PASS

실제 M8 Pilot embedding 285개를 Windows 로컬 환경에서 `IndexFlatIP`로 build했다.

```text
validation: PASS
vector_count: 285
dimension: 1024
mapping_failure_count: 0
hash_failure_count: 0
normalization_failure_count: 0
```

Artifact:

```text
data/retrieval/runs/20260804T043628Z/
├─ index.faiss
├─ index.mapping.jsonl
└─ index.manifest.json
```

Build 흐름:

```text
M8 validated embeddings
→ embedding_id ascending
→ float32 copy
→ L2 normalize
→ IndexFlatIP
→ mapping + manifest-last publish
```

판정:

```text
M9-03 Real Build = PASS
```

---

## 3. Rebuild Reproducibility · PASS

같은 source, 같은 retrieval contract, 같은 output directory에서 동일한 build 명령을 다시 실행했다.

첫 build와 rebuild 비교:

```text
retrieval_contract_hash             SAME
faiss_index_id                       SAME
source_embedding_artifact_sha256     SAME
mapping_sha256                       SAME
faiss_binary_sha256                  SAME · same environment observation
vector_count / dimension             SAME
validation failures                  0 / 0
```

따라서:

```text
same source + same retrieval contract
→ same logical retrieval contract
→ same logical FAISS artifact identity
→ same canonical position ↔ emb_ ↔ ki_ mapping
```

판정:

```text
M9-03 Rebuild Reproducibility = PASS
```

FAISS binary SHA까지 같은 환경에서 동일했지만, logical identity의 authoritative 기준은 `rc_`, `fi_`, source SHA, canonical mapping SHA다.

---

## 4. 서로 다른 두 Real Query · Semantic Sanity

서로 다른 실제 질문 두 개를 BGE-M3로 query embedding하여 현재 FAISS에서 Top-3를 검색했다. 실제 query text와 Jira-derived Knowledge text는 공개 문서에 기록하지 않는다.

```text
Case 1
rank1  좋음    0.843981
rank2  좋음    0.788863
rank3  어색함  0.601325

Case 2
rank1  좋음    0.708450
rank2  괜찮음  0.699601
rank3  어색함  0.687829
```

관찰:

- 두 질문 모두 Rank 1은 의미상 양호했다.
- Rank 2도 두 질문 모두 유효 후보였다.
- Rank 3에는 두 질문 모두 noise가 있었다.
- Case 2에서는 Rank 2와 Rank 3 score 차이가 작았지만 의미 품질은 달랐다.
- 따라서 global cosine threshold를 지금 임의로 도입하지 않는다.
- `Top-3 / no threshold / no reranker`는 Pilot baseline으로 유지하고, M10에서 Evidence를 붙인 실제 사용 품질과 후속 평가를 보고 조정한다.

판정:

```text
Real Query Path             PASS
Representative Sanity      PASS with Top-3 noise observation
```

---

## 5. Same-query Reproducibility · PASS

수동으로 질문을 두 번 입력하지 않고, 같은 Python 문자열을 한 프로세스 안에서 두 번 BGE-M3에 보내는 진단 도구를 사용했다.

```text
compare=1_vs_2
vector_exact_equal=True
max_abs_diff=0
cosine=1.000000000
ranking_equal=True
scores_exact_equal=True
```

의미:

```text
same exact query text
→ same BGE-M3 vector
→ same L2-normalized query
→ same IndexFlatIP Top-3 identity order
→ same cosine scores
```

판정:

```text
Same-query Vector Reproducibility  = PASS
Same-query Ranking Reproducibility = PASS
```

---

## 6. Pilot과 정식 서비스 Update 정책

이번 Pilot의 full rebuild는 운영 기본 정책이 아니다.

```text
Pilot
→ full rebuild
→ deterministic / integrity / reproducibility 검증

Production
→ delta-first
→ added / changed / removed Knowledge만 embedding/index 반영
→ 필요 시 maintenance full rebuild
```

정식 서비스에서는 같은 text + 같은 embedding contract vector를 재사용할 수 있도록 vector cache를 검토한다.

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)
```

Incremental exact index는 sequential Flat position 이동 문제를 피하기 위해 `IndexIDMap2(IndexFlatIP)` + stable int64 `vector_id`를 우선 후보로 둔다. HNSW/IVF 전환은 실제 latency/RAM/QPS/recall@k 측정 후 결정한다.

---

## 7. M9 최종 Gate

```text
[x] real FAISS build
[x] vector_count = 285
[x] dimension = 1024
[x] mapping/hash/normalization failure = 0
[x] manifest-last artifact publish
[x] same source rebuild → same rc_
[x] same source rebuild → same fi_
[x] same source rebuild → same source SHA
[x] same source rebuild → same mapping SHA
[x] distinct real query Case 1
[x] distinct real query Case 2
[x] representative semantic sanity
[x] Top-3 noise observation
[x] same exact query vector reproducibility
[x] same exact query ranking reproducibility
[x] exact score reproducibility

M9 = DONE / PASS
```

---

## 8. M10 Handoff

M9 output contract:

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M10 responsibility boundary:

```text
ki_ → Knowledge statement
ke_ → Evidence source
→ Evidence package
→ MCP
```

M10은 새 세션에서 **DESIGN부터** 시작한다. 상세 인수인계는 `docs/status/M10_START_HERE.html`을 기준으로 한다.

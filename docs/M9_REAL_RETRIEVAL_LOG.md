# M9 Real FAISS Retrieval Validation Log

기준일: 2026-08-26  
상태: **CURRENT / REAL BUILD PASS / REBUILD REPRODUCIBILITY PASS / REAL QUERY QUALITY PARTIAL PASS / QUERY REPRODUCIBILITY INVESTIGATE**

이 문서는 M9-03 실제 Pilot FAISS index 생성과 retrieval 검증 과정을 기록한다. 실제 Jira 본문, Issue Key, 사내 endpoint/header 값은 기록하지 않는다.

---

## 1. 입력

M8에서 검증 완료한 artifact를 사용한다.

```text
corpus_rows      285
embedding_rows   285
dimension        1024
mapping failure  0
identity failure 0
vector integrity PASS
```

입력 파일의 실제 공개 불가 내용은 문서화하지 않고, artifact SHA-256과 aggregate count만 기록한다.

---

## 2. M9-03 첫 Real Build · PASS

사용자 로컬 Windows 환경에서 M8 embedding 285개를 실제 FAISS `IndexFlatIP`로 build했다.

첫 실행 결과:

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

Artifact 위치는 공개 문서에서는 상대 경로만 기록한다.

```text
data/retrieval/runs/20260804T043628Z/
├─ index.faiss
├─ index.mapping.jsonl
└─ index.manifest.json
```

판정:

```text
M9-03 Real Build = PASS
```

---

## 3. Rebuild Reproducibility · PASS

같은 source, 같은 retrieval contract, 같은 output directory에서 동일한 build 명령을 다시 실행했다.

두 번째 실행도 첫 실행과 동일했다.

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
same source + same contract
→ same logical retrieval contract
→ same logical FAISS artifact identity
→ same canonical position ↔ emb_ ↔ ki_ mapping
```

이 재현성 Gate는 PASS다.

```text
M9-03 Rebuild Reproducibility = PASS
```

`faiss_binary_sha256`까지 동일했지만 이 값은 logical identity의 필수 조건으로 승격하지 않는다. 다른 FAISS/library/platform serialization에서 byte representation 차이가 날 수 있기 때문이다.

---

## 4. Identity / Hash 해석

### retrieval_contract_hash · rc_

검색 동작 계약의 identity다.

현재 baseline 계약:

```text
IndexFlatIP
cosine
L2 normalization
raw_query_v1
Top-3
no threshold
no reranker
BGE-M3 model/profile/dimension
```

같은 검색 계약이면 같은 `rc_`가 나와야 한다.

### faiss_index_id · fi_

source embedding artifact + index build profile의 logical identity다.

같은 M8 source artifact와 같은 index build profile이면 같은 `fi_`가 나와야 한다.

### source_embedding_artifact_sha256

M8 embedding JSONL source file의 fingerprint다. 어떤 embedding snapshot에서 이 index를 만들었는지 추적한다.

### mapping_sha256

`embedding_id ascending` canonical order로 만들어진 `index.mapping.jsonl`의 byte hash다.

Rebuild에서 이 값이 같다는 것은:

```text
faiss_position
↔ embedding_id
↔ knowledge_item_id
```

연결표가 그대로 재현됐다는 뜻이다.

### faiss_binary_sha256

실제 serialized FAISS binary의 SHA-256이다.

같은 로컬 환경에서 두 build가 동일한 값으로 확인됐지만, M9 logical reproducibility의 authoritative identity는 `rc_`, `fi_`, source SHA, canonical mapping SHA다.

---

## 5. Pilot과 정식 서비스의 차이

이번 rebuild test는 정식 서비스에서 매번 full rebuild하겠다는 의미가 아니다.

```text
Pilot
→ full rebuild
→ deterministic / integrity / reproducibility 검증

Production
→ delta-first
→ added / changed / removed Knowledge만 embedding/index 반영
→ 필요 시 maintenance full rebuild
```

정식 서비스 delta-first 계약은 `docs/M9_FAISS_ACTIVE_RETRIEVAL.md`에 별도 기록한다.

---

## 6. Real Query Semantic Sanity · PARTIAL PASS

동일 질문을 두 번 실행해 실제 BGE-M3 query embedding → FAISS Top-3를 확인했다.

실제 query text와 Jira-derived Knowledge text는 공개 문서에 기록하지 않는다.

사용자 의미 판정:

```text
Run 1
rank1  좋음    score 0.843981
rank2  좋음    score 0.788863
rank3  어색함  score 0.601325

Run 2
rank1  좋음    score 0.708450
rank2  괜찮음  score 0.699601
rank3  어색함  score 0.687829
```

관찰:

- 두 실행 모두 Rank 1은 의미상 양호했다.
- Rank 2도 유효 후보였다.
- Rank 3은 두 실행 모두 어색해 Top-3 baseline에 일부 noise가 섞일 수 있음을 확인했다.
- 단일 query 사례만으로 Top-k/threshold/reranker 정책을 변경하지 않는다.
- 점수 자체보다 더 중요한 문제는 동일 질문 실행 간 score/ranking 재현성이다.

판정:

```text
Real Query Semantic Sanity = PARTIAL PASS
Top-1 / Top-2 quality       = acceptable
Top-3 noise observation     = recorded
```

---

## 7. Same-query Reproducibility · INVESTIGATE

동일 질문을 두 번 실행했다는 전제에서 score가 크게 달랐다.

```text
Run 1: 0.843981 / 0.788863 / 0.601325
Run 2: 0.708450 / 0.699601 / 0.687829
```

이 차이는 단순 float rounding 수준이 아니다.

현재 검색 코드의 구조:

```text
query text
→ 매 실행 BGE-M3 API 호출
→ query vector
→ float32
→ L2 normalize
→ deterministic IndexFlatIP.search()
```

`IndexFlatIP.search()` 경로에는 random 요소가 없으므로 우선 다음을 분리 진단한다.

```text
A. 실제 입력 query bytes가 두 실행에서 달랐는가
B. 같은 query bytes에 사내 BGE-M3 API가 서로 다른 vector를 반환했는가
```

이를 위해 `tools/jira_knowledge/diagnose_query_reproducibility.py`를 추가했다.

이 도구는 같은 Python 문자열을 한 프로세스 안에서 연속 호출하여 다음만 출력한다.

```text
query_text_sha256
query vector SHA-256
vector norm
Top-k identity / score
vector exact equality
max absolute diff
vector cosine
ranking equality
```

실제 query text와 Knowledge text는 출력하지 않는다.

판정:

```text
Same-query Ranking Reproducibility = NOT YET PASS
M9 = NOT DONE
```

---

## 8. 현재 M9-03 Gate 상태

```text
[x] real FAISS build success
[x] vector_count = 285
[x] dimension = 1024
[x] mapping/hash/normalization failure = 0
[x] index + mapping + manifest publish
[x] same source rebuild → same rc_
[x] same source rebuild → same fi_
[x] same source rebuild → same source SHA
[x] same source rebuild → same mapping_sha256
[x] same environment → same faiss_binary_sha256 · observation
[x] real BGE-M3 query → Top-3 retrieval 실행
[x] representative semantic sanity · partial pass
[x] Top-3 noise observation
[ ] same query vector reproducibility
[ ] same query ranking reproducibility
[ ] root cause diagnosis
[ ] final documentation sync
```

다음 단계는 query vector reproducibility 진단이다.

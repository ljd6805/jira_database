# M9 Real FAISS Retrieval Validation Log

기준일: 2026-08-26  
상태: **CURRENT / REAL BUILD PASS / REBUILD REPRODUCIBILITY PASS / TWO REAL QUERY CASES OBSERVED / SAME-QUERY REPRODUCIBILITY NEXT**

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

## 6. Real Query Semantic Sanity · TWO DISTINCT CASES

사용자는 **서로 다른 두 질문**으로 실제 BGE-M3 query embedding → FAISS Top-3를 확인했다.

따라서 두 실행의 score 차이는 재현성 문제와 무관하다. 실제 query text와 Jira-derived Knowledge text는 공개 문서에 기록하지 않는다.

사용자 의미 판정:

```text
Case 1 · Query A
rank1  좋음    score 0.843981
rank2  좋음    score 0.788863
rank3  어색함  score 0.601325

Case 2 · Query B
rank1  좋음    score 0.708450
rank2  괜찮음  score 0.699601
rank3  어색함  score 0.687829
```

관찰:

- 서로 다른 두 질문에서 모두 Rank 1은 의미상 양호했다.
- Rank 2도 두 질문 모두 유효 후보였다.
- Rank 3은 두 질문 모두 어색해 Top-3 baseline에 일부 noise가 섞일 수 있음을 확인했다.
- Case 2에서는 Rank 2와 Rank 3의 score 차이가 작음에도 의미 품질 차이가 있었으므로 단순 global cosine threshold만으로 관련/비관련을 나누기 어렵다는 근거가 생겼다.
- 두 사례만으로 Top-k/threshold/reranker 계약을 즉시 변경하지 않는다. M10에서 Evidence와 함께 활용하고, 필요 시 후속 품질 실험에서 reranker/threshold를 비교한다.

판정:

```text
Real Query Execution         = PASS
Top-1 quality                = good in 2/2 cases
Top-2 candidate usefulness   = acceptable in 2/2 cases
Top-3 noise                  = observed in 2/2 cases
Same-query reproducibility   = NOT TESTED YET
```

---

## 7. Same-query Reproducibility · NEXT

현재까지 Case 1과 Case 2는 서로 다른 질문이므로 score/ranking을 서로 비교해 재현성을 판단하면 안 된다.

다음 Gate에서는 **완전히 동일한 한 질문 문자열**을 반복 사용한다.

수동 복사 차이를 없애기 위해 `tools/jira_knowledge/diagnose_query_reproducibility.py`를 사용할 수 있다. 이 도구는 같은 Python 문자열을 한 프로세스 안에서 연속 2회 이상 BGE-M3 API에 전달하고 다음만 비교한다.

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

이 검사는 이상이 이미 발견됐다는 뜻이 아니라, **아직 수행하지 않은 same-query reproducibility Gate를 모호함 없이 검증하기 위한 도구**다.

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
[x] real BGE-M3 query Case 1 실행
[x] real BGE-M3 query Case 2 실행
[x] semantic sanity · Top-1/2 useful, Top-3 noise observed
[ ] same exact query vector reproducibility
[ ] same exact query ranking reproducibility
[ ] final documentation sync
```

다음 단계는 동일한 질문 하나를 반복해 same-query reproducibility를 검증하는 것이다.

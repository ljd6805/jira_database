# M9 Real FAISS Retrieval Validation Log

기준일: 2026-08-26  
상태: **CURRENT / REAL BUILD PASS / REBUILD REPRODUCIBILITY PASS / REAL QUERY NEXT**

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

두 번째 실행도:

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

첫 실행과 두 번째 실행 비교:

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

## 6. 현재 M9-03 Gate 상태

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
[ ] real BGE-M3 query → Top-3 exact retrieval
[ ] same query ranking reproducibility
[ ] representative semantic sanity
[ ] dense-neighborhood observation
[ ] final documentation sync
```

---

## 7. 다음 Gate · Real Query

이제 실제 사용자 질문을 같은 BGE-M3 model/profile/dimension으로 embedding하고, 현재 FAISS index에서 exact cosine Top-3를 검색한다.

검증 대상:

```text
query text
→ BGE-M3 1024-d
→ L2 normalize
→ IndexFlatIP exact search
→ Top-3
→ faiss_position → emb_ → ki_
```

확인할 것:

```text
Top-3가 의미상 타당한가
같은 질문을 다시 실행하면 같은 rank/identity가 나오는가
score가 dense-neighborhood를 보이는 경우에도 후보군이 타당한가
```

실제 Jira-derived Top-k text는 로컬 화면에서만 확인하고 공개 문서에는 복사하지 않는다.

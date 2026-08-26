# M9 Real FAISS Retrieval Validation Log

기준일: 2026-08-26  
상태: **CURRENT / REAL BUILD PASS / REBUILD REPRODUCIBILITY NEXT**

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

실행 결과:

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

### 확인된 사실

```text
M8 validated embeddings 285
→ canonical embedding_id order
→ float32 copy
→ L2 normalization
→ IndexFlatIP
→ vector_count 285
→ dimension 1024
→ mapping/hash/normalization failure 0
```

따라서 첫 실데이터 FAISS build 자체는 PASS다.

```text
M9-03 Real Build = PASS
```

---

## 3. Identity / Hash 해석

### retrieval_contract_hash · rc_

```text
rc_6b9fc7...
```

검색 동작 계약의 identity다.

현재 baseline 계약에는 다음이 포함된다.

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

같은 검색 계약이면 rebuild에서도 같은 `rc_`가 나와야 한다.

### faiss_index_id · fi_

```text
fi_b544c5...
```

source embedding artifact + index build profile의 logical identity다.

같은 M8 source artifact와 같은 index build profile이면 rebuild에서도 같은 `fi_`가 나와야 한다.

### mapping_sha256

`embedding_id ascending` canonical order로 만들어진 mapping sidecar의 byte hash다.

같은 source set이면 rebuild에서도 동일해야 한다.

### faiss_binary_sha256

실제 serialized FAISS binary의 SHA-256이다.

같은 머신/FAISS version/build에서는 동일할 가능성이 높지만, M9 logical reproducibility의 필수 identity material은 아니다. 라이브러리/플랫폼 serialization 차이가 생길 수 있으므로 `rc_`, `fi_`, canonical mapping이 더 중요한 Gate다.

---

## 4. 현재 M9-03 Gate 상태

```text
[x] real FAISS build success
[x] vector_count = 285
[x] dimension = 1024
[x] mapping/hash/normalization failure = 0
[x] index + mapping + manifest publish
[ ] same source rebuild → same rc_
[ ] same source rebuild → same fi_
[ ] same source rebuild → same mapping_sha256
[ ] real BGE-M3 query → Top-3 exact retrieval
[ ] same query ranking reproducibility
[ ] representative semantic sanity
[ ] dense-neighborhood observation
[ ] final documentation sync
```

---

## 5. 다음 Gate · Rebuild Reproducibility

같은 명령을 같은 source/output-dir에 다시 실행한다.

필수 비교값:

```text
retrieval_contract_hash
faiss_index_id
source_embedding_artifact_sha256
mapping_sha256
```

이 네 값은 첫 build와 동일해야 한다.

참고 관찰값:

```text
faiss_binary_sha256
```

같은 로컬 환경에서 동일하면 좋은 신호지만, logical Gate의 절대 조건으로 두지는 않는다.

Rebuild PASS 후 실제 사용자 질문을 같은 BGE-M3로 embedding하여 Top-3 exact cosine retrieval과 ranking 재현성을 검증한다.

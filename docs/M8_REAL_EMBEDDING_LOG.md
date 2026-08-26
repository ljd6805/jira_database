# M8 Real BGE-M3 Validation Log

기준일: 2026-08-26  
상태: **PASS / DONE**

이 문서는 M8-03 실제 사내 BGE-M3 embedding 검증 과정을 기록한다. 실제 endpoint, API key, custom header 이름/값, Jira 식별자/본문은 기록하지 않는다.

상세 Troubleshooting 시각 문서:

```text
docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html
```

---

## 1. 입력 corpus · PASS

M8-01 실데이터 Gate:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

M7 SQLite의 active accepted Knowledge Item 285개와 M8 corpus 285개가 일치한다.

---

## 2. Runtime 설정 Preflight · PASS

사용자 로컬 환경에서 확인한 secret-safe aggregate:

```text
endpoint configured : true
api_key configured  : false
custom_headers      : 6
model               : BAAI/bge-m3
dimension           : 1024
```

확인:

- endpoint load 성공
- 표준 Bearer API key 미사용
- 고정 custom header 6개 정상 파싱/전달
- model = `BAAI/bge-m3`
- dense dimension contract = `1024`

실제 endpoint/header 값은 Git/public 문서에 기록하지 않는다.

---

## 3. 1-row Real API Smoke · PASS

전체 실행 전에 실제 corpus text 1건을 호출했다.

```text
API call: PASS
vectors : 1
dimension: 1024
```

초기 HTTP 404는 endpoint path가 실제 embeddings route와 달랐던 설정 문제였다. endpoint 수정 후 동일 smoke test가 PASS했다.

---

## 4. Full 285 Real Embedding · PASS

사용자 로컬에서 전체 Pilot corpus를 실제 사내 BGE-M3 API로 실행했다.

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

실행 구조:

```text
285 corpus rows
→ 64 + 64 + 64 + 64 + 29
→ 5 batches
→ 285 embedding rows
→ each vector = 1024 dimensions
```

확인:

- corpus 285개 전부 API 처리 성공
- embedding output 285개 생성
- batch max 64 계약 준수
- 총 batch = 5
- output dimension = 1024
- 모든 batch 성공 후 final JSONL을 atomic publish

---

## 5. Artifact Integrity Gate · PASS

최종 embedding artifact와 corpus를 다시 읽어 deterministic 검증을 수행했다.

최종 출력:

```text
validation: PASS
corpus_rows: 285
embedding_rows: 285
unique_knowledge_item_ids: 285
unique_embedding_ids: 285
contract_count: 1
mapping_failure_count: 0
identity_failure_count: 0
dimension_failure_count: 0
non_finite_vector_count: 0
zero_norm_vector_count: 0
temp_artifact_exists: false
```

의미:

```text
Knowledge Item 285
↕ 1:1
Embedding 285

mapping failure        0
identity failure       0
dimension failure      0
non-finite vector      0
zero-norm vector       0
leftover temp artifact false
```

즉 `emb_ ↔ ki_` mapping, deterministic ID 재계산, vector 수치 유효성, atomic publish 상태가 모두 정상이다.

---

## 6. Semantic Quality Sanity Check · PASS

FAISS 없이 Pilot 285개 vector를 brute-force cosine similarity로 비교하고 사용자 검토를 수행했다.

```text
Sample 1  PASS
Sample 2  PASS · 매우 양호
Sample 3  PASS
          top-3 scores = 0.5918 / 0.5908 / 0.5900
```

Sample 3은 Top-1~3 점수 차이가 작았지만 세 후보 모두 의미상 타당하다고 판단했다.

해석:

- embedding 실패가 아니라 유사한 Knowledge가 같은 semantic neighborhood에 촘촘히 존재하는 사례다.
- cosine absolute score 자체만으로 품질을 판정하지 않는다.
- M9에서는 Top-1 하나를 과신하기보다 Top-k 후보군을 유지하고 Evidence와 함께 사용하는 방식을 검토한다.
- 이 관찰은 M9 retrieval 설계 근거이며 M8 Gate 실패 사유가 아니다.

---

## 7. Troubleshooting Summary

이번 실제 연결 과정에서 다음 문제와 해결을 확인했다.

```text
T01  legacy VS Code SQLite extension query 오류
     → DB corruption이 아니라 Viewer 문제로 분리

T02  python-dotenv multi-line parse 오류
     → JSON 전체를 하나의 dotenv value로 구성

T03  BGE_M3_HEADERS_JSON JSONDecodeError
     → str(uuid.uuid4()) 같은 Python 표현식은 JSON literal이 아님

T04  사내 custom header 필요
     → generic BGE_M3_HEADERS_JSON runtime injection 구현

T05  HTTP 404
     → endpoint/path 우선 진단, 실제 embeddings route로 수정 후 PASS

T06  corpus_rows 28 전달 오류
     → 실제 deterministic CLI 결과 285, 프로젝트 결함 아님
```

상세 내용은 `docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html`에 증상 → 원인 → 해결 → 재발 방지 형태로 보존한다.

---

## 8. M8-03 Final Gate

```text
[x] corpus_rows = 285
[x] embedding_rows = 285
[x] batch_count = 5
[x] embedding_dimension = 1024
[x] unique knowledge_item_id = 285
[x] unique embedding_id = 285
[x] embedding contract = 1
[x] mapping failure = 0
[x] deterministic identity failure = 0
[x] dimension failure = 0
[x] non-finite vector = 0
[x] zero-norm vector = 0
[x] leftover temp artifact = false
[x] semantic quality sanity check PASS
[x] troubleshooting 기록 보존

M8-03 = PASS / DONE
M8 = DONE
```

---

## 9. 다음 단계

```text
M8 validated embedding artifact
→ M9 FAISS + Active Retrieval 설계
```

M8에서는 FAISS를 구현하지 않았다. M9는 아직 구현 시작 전이며, 먼저 index/mapping/search/top-k 검증 계약을 문서로 설계한 뒤 구현한다.

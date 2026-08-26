# M8 Real BGE-M3 Validation Log

기준일: 2026-08-26  
상태: **CURRENT / FULL 285 EMBEDDING PASS / ARTIFACT INTEGRITY VALIDATION NEXT**

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

판정:

```text
M8-01 = PASS
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

확인:

- 로컬 PC → 사내 BGE-M3 endpoint 연결 성공
- current custom headers로 실제 request 성공
- OpenAI-compatible request/response baseline 동작
- dense vector 1개 / 1024 dimension

초기 HTTP 404는 endpoint path가 실제 embeddings route와 달랐던 설정 문제였다. endpoint 수정 후 동일 smoke test가 PASS했다.

---

## 4. Full 285 Real Embedding · PASS

사용자 로컬에서 전체 Pilot corpus를 실제 사내 BGE-M3 API로 실행했다.

최종 출력:

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

실행 구조:

```text
285 corpus rows
→ Batch 1 = 64
→ Batch 2 = 64
→ Batch 3 = 64
→ Batch 4 = 64
→ Batch 5 = 29
→ 285 embedding rows
→ each vector = 1024 dimensions
```

확인된 사실:

- corpus 285개 전부 API 처리 성공
- embedding output 285개 생성
- batch max 64 계약 준수
- 총 request batch = 5
- output dimension = 1024
- runner가 모든 batch 성공 후 final JSONL을 publish했으므로 partial result를 완료본으로 오인하지 않음

판정:

```text
M8-03 Full Real Embedding = PASS
```

---

## 5. Troubleshooting Summary

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

## 6. Artifact Integrity Gate · NEXT

API 성공만으로 M8을 닫지 않는다. 생성된 final embedding JSONL과 corpus를 다시 읽어 다음을 deterministic하게 검증한다.

```text
[ ] corpus_rows = 285
[ ] embedding_rows = 285
[ ] unique knowledge_item_id = 285
[ ] unique embedding_id = 285
[ ] embedding contract = 1개
[ ] corpus ↔ embedding lineage mapping failure = 0
[ ] emb_ deterministic ID recomputation failure = 0
[ ] dimension failure = 0
[ ] non-finite vector = 0
[ ] zero-norm vector = 0
[ ] leftover .tmp artifact = false
```

도구:

```text
src/jira_collector/embedding/validation.py
tools/jira_knowledge/validate_m8_embedding_artifact.py
```

실행:

```powershell
python tools/jira_knowledge/validate_m8_embedding_artifact.py --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl --embeddings data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl --expected-count 285 --expected-dimension 1024
```

---

## 7. 현재 M8-03 Gate 상태

```text
[x] M8-01 corpus_rows = 285
[x] embedding runtime settings parse
[x] custom header 6개 runtime load
[x] 1-row real API call success
[x] smoke vector dimension = 1024
[x] corpus 285개 full embedding success
[x] embedding_rows = 285
[x] batch_count = 5
[x] reported output dimension = 1024
[x] final artifact publish 완료
[ ] artifact mapping / deterministic identity validation
[ ] finite / non-zero vector validation
[ ] 작은 semantic quality sanity check
[ ] 문서/HTML 최종 sync
```

M8에서는 FAISS를 구현하지 않는다. 위 M8 Gate를 닫은 뒤 M9에서 FAISS를 시작한다.

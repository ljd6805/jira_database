# M8 Real BGE-M3 Validation Log

기준일: 2026-08-26  
상태: **CURRENT / PREFLIGHT PASS / REAL API CALL NEXT**

이 문서는 M8-03 실제 사내 BGE-M3 embedding 검증 과정을 기록한다. 실제 endpoint, API key, custom header 이름/값은 기록하지 않는다.

---

## 1. 입력 corpus

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

---

## 2. Runtime 설정 Preflight

사용자 로컬 환경에서 embedding 설정 loader를 실행해 다음 aggregate 결과를 확인했다.

```text
endpoint configured : true
api_key configured  : false
custom_headers      : 6
model               : BAAI/bge-m3
dimension           : 1024
```

의미:

- endpoint 값이 로드됐다.
- 표준 Bearer API key는 사용하지 않는다.
- 고정 custom header 6개가 JSON으로 정상 파싱됐다.
- model/dimension contract는 `BAAI/bge-m3` / `1024`다.

초기 `.env`에는 Python 표현식 형태의 동적 UUID header 값이 포함돼 JSON 파싱 오류가 발생했다. 해당 표현식은 JSON 값이 아니므로 `.env`의 static custom header 설정에서 제외했다.

중요:

- 이 시점에는 동적 UUID header가 실제 embedding endpoint에 불필요하다고 확정하지 않는다.
- 실제 API 호출 성공 여부로 필요성을 판단한다.
- header 이름/값은 Git, 로그, embedding artifact에 저장하지 않는다.

판정:

```text
M8-03 runtime configuration preflight = PASS
Real API call = NEXT
```

---

## 3. 다음 검증

실제 BGE-M3 호출에서 다음을 확인한다.

```text
[ ] corpus_rows = 285
[ ] embedding_rows = 285
[ ] batch_count = 5
[ ] embedding_dimension = 1024
[ ] custom header 인증/라우팅 성공
[ ] emb_ ↔ ki_ mapping 무결성
[ ] final artifact atomic publish
```

실패 시 HTTP status / response contract만 기록하고 secret/header 값은 기록하지 않는다.

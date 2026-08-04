# Jira TLS 인증서 검증 설정

사내 Jira가 자체 서명 인증서를 사용하므로 현재 기본 설정은 다음과 같습니다.

```yaml
jira:
  tls:
    verify_ssl: false
```

이 값은 `requests.Session.verify`에 그대로 적용됩니다. 따라서 `jira-collector check-connection`을 실행할 때 Python이 Jira 서버의 인증서 체인을 검증하지 않습니다.

## 적용 대상

- 사내망에서만 접근 가능한 신뢰된 Jira 서버
- 자체 서명 인증서 또는 사내 CA 인증서를 사용하는 현재 파일럿 환경

## 보안 주의

`verify_ssl: false`는 중간자 공격을 탐지하지 못할 수 있습니다. 외부 Jira 또는 신뢰할 수 없는 네트워크에서는 다음과 같이 인증서 검증을 다시 활성화하십시오.

```yaml
jira:
  tls:
    verify_ssl: true
```

장기 운영에서는 검증을 끄는 방식보다 사내 CA 인증서를 Python 또는 운영체제 trust store에 등록하는 방식이 더 안전합니다.

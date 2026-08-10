# GitHub Pages 문서 배포

`docs/` 아래의 HTML 문서를 GitHub Pages로 바로 열기 위한 설정입니다.

## 배포 대상

GitHub Actions workflow:

```text
.github/workflows/pages.yml
```

배포 원본:

```text
[Git 문서 경로]
docs/

용도:
GitHub Pages에 게시되는 정적 HTML/CSS/JavaScript 문서 원본
```

대표 페이지:

```text
https://ljd6805.github.io/jira_database/
https://ljd6805.github.io/jira_database/status/jira_knowledge_db_current_status.html
https://ljd6805.github.io/jira_database/architecture/jira_data_relationship_map.html
```

## 최초 1회 GitHub 설정

Repository에서 다음 설정이 필요합니다.

```text
Settings
→ Pages
→ Build and deployment
→ Source: GitHub Actions
```

이 설정 후 `main`의 `docs/**`가 변경되면 `.github/workflows/pages.yml`이 실행되어 `docs/` 전체를 Pages artifact로 배포합니다.

## 저장소를 Private으로 유지하려는 경우

GitHub Pages는 public repository에서는 GitHub Free에서도 사용할 수 있습니다.

Private repository에서 Pages를 사용하려면 GitHub Pro, Team, Enterprise 계열 플랜이 필요합니다.

개인 계정의 Private repository에서 Pages를 사용하더라도 Pages 사이트 자체는 기본적으로 public일 수 있습니다. Repository 읽기 권한이 있는 사용자에게만 Pages를 공개하는 Private Pages access control은 GitHub Enterprise Cloud 조직 기능입니다.

따라서 이 프로젝트를 개인 계정의 Private repository로 운영할 경우에는 HTML 문서에 외부 공개가 곤란한 실제 Jira 내용, 인증정보, 개인정보를 넣지 않는 현재 원칙을 유지해야 합니다.

## 문서 관리 원칙

- HTML 문서는 `docs/` 아래에서 Git 버전 관리합니다.
- `docs/index.html`을 HTML 문서의 기본 진입점으로 사용합니다.
- 기능/검증 상태가 바뀌면 HTML 현황 문서도 함께 갱신합니다.
- 외부 CDN 또는 웹 폰트 없이 self-contained 문서로 유지합니다.
- `.nojekyll`을 유지하여 정적 파일을 별도 Jekyll 변환 없이 배포합니다.

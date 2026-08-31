(function () {
  "use strict";

  const NAV_CLASS = Object.freeze({
    top: "doc-global-nav--top",
    bottom: "doc-global-nav--bottom",
  });

  const CURRENT_CONTEXT = Object.freeze({
    "architecture/jira_sync_contract.html": [
      "현재 운영 규칙",
      "Sync Contract 개정 3이 현재 기준입니다. 숫자 3은 이 계약 문서 계열의 세 번째 개정이라는 뜻입니다.",
    ],
    "architecture/jira_sync_state_schema_contract.html": [
      "현재 Operational State 설계",
      "State Schema 개정 3이 현재 구현 목표입니다. Knowledge DB의 개정 번호와는 별개입니다.",
    ],
    "architecture/jira_sync_state_schema_decision7_final_ddl.html": [
      "현재 Operational State DDL",
      "State DB 개정 3의 실제 SQLite DDL 기준입니다.",
    ],
    "architecture/jira_operational_two_loop_architecture.html": [
      "현재 운영 아키텍처",
      "2-Loop + Source Ready + Latest-Only를 현재 기준으로 설명합니다.",
    ],
    "architecture/jira_data_relationship_map.html": [
      "두 DB를 함께 보는 문서",
      "Operational State DB 개정 3과 실제 구현된 Knowledge DB 개정 1을 같은 화면에서 비교합니다. 숫자 크기를 서로 비교하면 안 됩니다.",
    ],
    "status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html": [
      "현재 구현 진행",
      "Operational State 설계 개정 3의 Migration/StateStore foundation 구현 결과입니다.",
    ],
    "status/M6_DB_LOGICAL_SCHEMA_COMPLETION.html": [
      "Knowledge DB 설계 단계",
      "여기서의 DB 개정 번호는 Knowledge DB 계열입니다. Operational State Schema 개정 번호와 독립적입니다.",
    ],
    "status/M7_SQLITE_MATERIALIZATION.html": [
      "Knowledge DB 실제 구현",
      "Knowledge DB Schema 개정 1을 실제 SQLite로 구현하고 검증한 문서입니다. State Schema 개정 3보다 숫자가 작다고 과거 설계라는 뜻이 아닙니다.",
    ],
    "VERSION_TERMINOLOGY_GUIDE.html": [
      "버전 표기 공식 가이드",
      "상태 → 대상 → 개정 번호 순서로 읽고, 서로 다른 대상의 숫자를 비교하지 않는 규칙을 설명합니다.",
    ],
    "status/VERSION_LANGUAGE_REALIGNMENT_2026-08-31.html": [
      "문서 정리 기록",
      "전체 문서에서 버전 숫자 혼동을 줄이기 위해 적용한 변경과 회귀 방지를 기록합니다.",
    ],
    "DOCUMENT_FRAMEWORK_STANDARD_2026-08-27.html": [
      "문서 UI 프레임",
      "Document Shell/Hub Frame 개정 1입니다. DB나 Sync Contract의 개정 번호와 아무 관계가 없습니다.",
    ],
    "DOCUMENTATION_POLICY.html": [
      "문서 정책",
      "문서에서 버전 숫자를 단독으로 쓰지 않고 대상과 상태를 함께 설명하는 규칙을 적용합니다.",
    ],
  });

  const EXPLICIT_HISTORICAL_PATHS = new Set([
    "architecture/jira_sync_contract_decision8_run_status.html",
    "architecture/jira_sync_state_project_registry_design_draft.html",
  ]);

  const runtimeScript = document.currentScript;
  if (!runtimeScript || !runtimeScript.src) return;

  const assetsBase = new URL(".", runtimeScript.src);
  const docsBase = new URL("../", assetsBase);
  const hubUrl = new URL("index.html", docsBase).href;

  function currentDocumentPath() {
    const docsPath = decodeURIComponent(docsBase.pathname).replace(/\/$/, "") + "/";
    const currentPath = decodeURIComponent(window.location.pathname);
    if (currentPath.startsWith(docsPath)) {
      return currentPath.slice(docsPath.length).replace(/^\/+/, "");
    }
    const marker = "/docs/";
    const index = currentPath.lastIndexOf(marker);
    if (index >= 0) return currentPath.slice(index + marker.length);
    return currentPath.split("/").pop() || "";
  }

  function documentUrl(path) {
    return new URL(path, docsBase).href;
  }

  function control(role, label, entry) {
    if (!entry) {
      const disabled = document.createElement("span");
      disabled.className = "doc-global-nav__button is-disabled";
      disabled.dataset.navRole = role;
      disabled.setAttribute("aria-disabled", "true");
      disabled.textContent = label;
      return disabled;
    }
    const anchor = document.createElement("a");
    anchor.className = "doc-global-nav__button";
    anchor.dataset.navRole = role;
    anchor.href = role === "hub" ? hubUrl : documentUrl(entry.path);
    anchor.textContent = label;
    if (entry.title) anchor.title = entry.title;
    return anchor;
  }

  function buildNavigation(position, previousEntry, nextEntry) {
    const nav = document.createElement("nav");
    nav.className = `doc-global-nav ${NAV_CLASS[position]}`;
    nav.dataset.docShellNav = position;
    nav.setAttribute("aria-label", position === "top" ? "문서 이동" : "다음 문서 이동");
    nav.append(
      control("previous", "← 이전 문서", previousEntry),
      control("hub", "⌂ 문서 Hub", { path: "index.html", title: "Documentation Hub" }),
      control("next", "다음 문서 →", nextEntry),
    );
    return nav;
  }

  function pageUsesVersionTerms() {
    const text = document.body ? document.body.innerText : "";
    return /\bv\d+(?:\.\d+)?\b/i.test(text)
      || /semantic_v2|schema_version|user_version|revision|개정\s*\d+/i.test(text);
  }

  function historicalContext(path) {
    const bodyText = document.body ? document.body.innerText : "";
    const baseline = /_v[12]_baseline\.html$/i.test(path);
    const explicit = EXPLICIT_HISTORICAL_PATHS.has(path);
    const bodySaysHistorical = /HISTORICAL|과거\s+(?:설계|보관|의사결정)|현재\s+구현\s+기준(?:이|이\s*)?\s*아님/i.test(bodyText);
    if (!baseline && !explicit && !bodySaysHistorical) return null;
    return [
      "과거 설계/의사결정 보관본 · 현재 구현 기준 아님",
      "이 문서는 설계 변화 과정을 보존하기 위한 기록입니다. 현재 기준은 문서 Hub의 '현재 운영 규칙'과 '현재 State 설계'를 따르세요.",
    ];
  }

  function buildStatusHint(path) {
    const historical = historicalContext(path);
    const current = CURRENT_CONTEXT[path];
    const info = historical || current;
    if (!info) return null;
    const box = document.createElement("div");
    box.className = "doc-version-status";
    if (historical) box.classList.add("is-historical");
    else if (current) box.classList.add("is-current");
    const strong = document.createElement("strong");
    strong.textContent = info[0];
    const span = document.createElement("span");
    span.textContent = info[1];
    box.append(strong, span);
    return box;
  }

  function versionItem(title, body) {
    const item = document.createElement("div");
    item.className = "doc-version-help__item";
    const strong = document.createElement("b");
    strong.textContent = title;
    const span = document.createElement("span");
    span.innerHTML = body;
    item.append(strong, span);
    return item;
  }

  function buildVersionHelp() {
    const details = document.createElement("details");
    details.className = "doc-version-help";
    const summary = document.createElement("summary");
    summary.textContent = "버전 숫자 읽는 법 · v1/v2/v3는 서로 다른 종류일 수 있습니다";
    const body = document.createElement("div");
    body.className = "doc-version-help__body";
    const lead = document.createElement("p");
    lead.className = "doc-version-help__lead";
    lead.textContent = "핵심: 숫자가 더 크다고 다른 종류의 문서보다 더 최신이라는 뜻이 아닙니다. 항상 '현재/과거 상태'와 '무엇의 버전인지'를 먼저 보세요.";
    const grid = document.createElement("div");
    grid.className = "doc-version-help__grid";
    grid.append(
      versionItem("현재 운영 Sync Contract · 개정 3", "Jira 동기화/2-Loop/Latest-Only 운영 규칙의 현재 개정입니다."),
      versionItem("현재 Operational State Schema · 개정 3", "<code>collector.db</code> 운영 상태 테이블의 현재 설계 개정입니다."),
      versionItem("Knowledge DB Schema · 개정 1", "M7에서 실제 구현·검증한 지식 DB의 첫 스키마 개정입니다. State Schema 개정 3과 <strong>독립된 번호 체계</strong>입니다."),
      versionItem("Document Shell / Hub Frame · 개정 1", "문서 UI 틀의 개정 번호입니다. DB/Sync 설계와 관계없습니다."),
      versionItem("semantic_v2", "문서 버전이 아니라 <strong>Jira 내용의 의미 변화 여부를 판별하는 Source hash profile 이름</strong>입니다."),
      versionItem("STATE_ID_SCHEMA_VERSION = 2", "Operational State 개정 번호가 아니라 <strong>Work Item ID 생성 알고리즘의 기술 버전</strong>입니다."),
      versionItem("Historical / Baseline", "과거 설계를 보존한 문서입니다. 학습/의사결정 이력용이며 현재 구현 기준으로 사용하지 않습니다."),
    );
    body.append(lead, grid);
    details.append(summary, body);
    return details;
  }

  function buildVersionContext(path) {
    const status = buildStatusHint(path);
    if (!status && !pageUsesVersionTerms()) return null;
    const wrapper = document.createElement("section");
    wrapper.className = "doc-version-context";
    wrapper.setAttribute("aria-label", "문서 버전 표기 안내");
    if (status) wrapper.append(status);
    wrapper.append(buildVersionHelp());
    return wrapper;
  }

  function mount(registry) {
    if (!Array.isArray(registry) || document.querySelector('[data-doc-shell-nav="top"]')) return;
    const current = currentDocumentPath();
    const index = registry.findIndex((entry) => entry.path === current);
    const previousEntry = index > 0 ? registry[index - 1] : null;
    const nextEntry = index >= 0 && index < registry.length - 1 ? registry[index + 1] : null;
    const host = document.querySelector("main") || document.body;
    const topNav = buildNavigation("top", previousEntry, nextEntry);
    host.prepend(topNav);
    const versionContext = buildVersionContext(current);
    if (versionContext) topNav.after(versionContext);
    host.append(buildNavigation("bottom", previousEntry, nextEntry));
    document.documentElement.classList.add("doc-shell-mounted");
  }

  function loadRegistry() {
    if (window.JIRA_DOCUMENT_REGISTRY) {
      mount(window.JIRA_DOCUMENT_REGISTRY);
      return;
    }
    const registryScript = document.createElement("script");
    registryScript.src = new URL("document-registry.js", assetsBase).href;
    registryScript.onload = () => mount(window.JIRA_DOCUMENT_REGISTRY || []);
    registryScript.onerror = () => mount([]);
    document.head.append(registryScript);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadRegistry, { once: true });
  } else {
    loadRegistry();
  }
})();

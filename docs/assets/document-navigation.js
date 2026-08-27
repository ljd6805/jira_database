(function () {
  "use strict";

  const NAV_CLASS = Object.freeze({
    top: "doc-global-nav--top",
    bottom: "doc-global-nav--bottom",
  });
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

  function mount(registry) {
    if (!Array.isArray(registry) || document.querySelector('[data-doc-shell-nav="top"]')) return;
    const current = currentDocumentPath();
    const index = registry.findIndex((entry) => entry.path === current);
    const previousEntry = index > 0 ? registry[index - 1] : null;
    const nextEntry = index >= 0 && index < registry.length - 1 ? registry[index + 1] : null;
    const host = document.querySelector("main") || document.body;
    host.prepend(buildNavigation("top", previousEntry, nextEntry));
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

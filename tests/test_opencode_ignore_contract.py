from pathlib import Path


def test_opencode_ignore_exposes_only_knowledge_paths_for_both_roots() -> None:
    text = Path(".ignore").read_text(encoding="utf-8")

    required = {
        "!data/",
        "data/*",
        "!data/knowledge_input/",
        "!data/knowledge_input/**",
        "!data/knowledge/",
        "!data/knowledge/**",
        "!data_smoke/",
        "data_smoke/*",
        "!data_smoke/knowledge_input/",
        "!data_smoke/knowledge_input/**",
        "!data_smoke/knowledge/",
        "!data_smoke/knowledge/**",
    }

    lines = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert required.issubset(lines)


def test_gitignore_keeps_runtime_roots_out_of_git() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in text.splitlines() if line.strip()}

    assert "data/" in lines
    assert "data_smoke/" in lines

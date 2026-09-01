from pathlib import Path

from jira_collector.publishing import OperationalPublishWorker
from jira_collector.retrieval_head import (
    active_generation_ids,
    active_retrieval_artifact_dir,
    retrieval_artifact_dir_for_generation_set,
)
from test_g4_atomic_publish import _environment, _seed_ready_work


def test_published_bundle_resolves_from_active_generation_set(tmp_path: Path) -> None:
    state, db_path, embedding_root, retrieval_root = _environment(tmp_path)
    _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=1,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="a",
        statement="shared retrieval head resolver",
        vector=[1.0, 0.0, 0.0],
    )
    worker = OperationalPublishWorker(state, db_path, embedding_root, retrieval_root)

    result = worker.run()

    assert result.published_count == 1
    assert result.publish_result is not None
    generations = active_generation_ids(db_path)
    assert generations == frozenset({result.publish_result.knowledge_generation_id})
    assert (
        retrieval_artifact_dir_for_generation_set(retrieval_root, generations)
        == result.publish_result.artifact_dir
    )
    assert (
        active_retrieval_artifact_dir(db_path, retrieval_root)
        == result.publish_result.artifact_dir
    )

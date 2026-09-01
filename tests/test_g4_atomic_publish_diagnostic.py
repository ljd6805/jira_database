from pathlib import Path

from jira_collector.publishing import OperationalPublishWorker
from test_g4_atomic_publish import _environment, _seed_ready_work


def test_expose_g4_publish_failure_boundary(tmp_path: Path) -> None:
    state, db_path, embedding_root, retrieval_root = _environment(tmp_path)
    work = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=1,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="a",
        statement="diagnostic",
        vector=[1.0, 0.0, 0.0],
    )
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work["work_item_id"], processing_run_id)
    worker = OperationalPublishWorker(state, db_path, embedding_root, retrieval_root)
    worker.process_work(work["work_item_id"], processing_run_id)

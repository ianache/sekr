from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_gitlab_pipeline_defines_blocking_knowledge_check_with_report_artifact():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert "stages:" in pipeline
    assert "knowledge-check:" in pipeline
    assert 'if: \'$CI_PIPELINE_SOURCE == "merge_request_event"\'' in pipeline
    assert 'if: \'$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH\'' in pipeline
    assert "image: python:3.12-slim" in pipeline
    assert 'SEKR_KNOWLEDGE_INPUT: "data/coder_activation.json"' in pipeline
    assert 'SEKR_KNOWLEDGE_BASELINE: "data/knowledge-baseline.json"' in pipeline
    assert 'SEKR_KNOWLEDGE_POLICY: ".sekr/knowledge-policy.json"' in pipeline
    assert 'python -m sekr.cli knowledge-check' in pipeline
    assert "--input \"$SEKR_KNOWLEDGE_INPUT\"" in pipeline
    assert "--baseline \"$SEKR_KNOWLEDGE_BASELINE\"" in pipeline
    assert "--policy \"$SEKR_KNOWLEDGE_POLICY\"" in pipeline
    assert "--output .sekr/knowledge-check.json" in pipeline
    assert "when: always" in pipeline
    assert "- .sekr/knowledge-check.json" in pipeline


def test_gitlab_pipeline_defines_manual_baseline_proposal_without_overwriting_approved_file():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert "knowledge-baseline-propose:" in pipeline
    assert "when: manual" in pipeline
    assert "allow_failure: true" in pipeline
    assert "knowledge-snapshot" in pipeline
    assert "--output .sekr/proposed-knowledge-baseline.json" in pipeline
    assert "- .sekr/proposed-knowledge-baseline.json" in pipeline
    assert "data/knowledge-baseline.json" in pipeline


def test_gitlab_pipeline_defines_knowledge_freshness_report_job_without_baseline_write():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    job = pipeline.split("knowledge-freshness:", 1)[1].split("\n\n", 1)[0]

    assert pipeline.index("knowledge-check:") < pipeline.index("knowledge-freshness:")
    assert 'SEKR_KNOWLEDGE_AS_OF: "2026-09-11T00:00:00Z"' in pipeline
    assert "knowledge-freshness:" in pipeline
    assert 'python -m sekr.cli knowledge-freshness --input "$SEKR_KNOWLEDGE_INPUT" --as-of "$SEKR_KNOWLEDGE_AS_OF" --output .sekr/knowledge-freshness.json' in job
    assert "when: always" in job
    assert "expire_in: 1 week" in job
    assert "- .sekr/knowledge-freshness.json" in job
    assert "data/knowledge-baseline.json" not in job


def test_readme_documents_freshness_reporting_and_baseline_approval_separately():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "knowledge-freshness" in readme
    assert "SEKR_KNOWLEDGE_AS_OF" in readme
    assert "freshness report" in readme.lower()
    assert "does not approve" in readme.lower()

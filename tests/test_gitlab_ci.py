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

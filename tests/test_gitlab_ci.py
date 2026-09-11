from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_gitlab_pipeline_defines_blocking_knowledge_check_with_report_artifact():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert "stages:" in pipeline
    assert "knowledge-check:" in pipeline
    assert "image: python:3.12-slim" in pipeline
    assert 'SEKR_KNOWLEDGE_INPUT: "data/coder_activation.json"' in pipeline
    assert 'SEKR_KNOWLEDGE_BASELINE: "data/knowledge-baseline.json"' in pipeline
    assert 'python -m sekr.cli knowledge-check' in pipeline
    assert "--input \"$SEKR_KNOWLEDGE_INPUT\"" in pipeline
    assert "--baseline \"$SEKR_KNOWLEDGE_BASELINE\"" in pipeline
    assert "--output .sekr/knowledge-check.json" in pipeline
    assert "when: always" in pipeline
    assert "- .sekr/knowledge-check.json" in pipeline

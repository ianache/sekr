import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
PACK = ROOT / "experiment-pack" / "v0.1"
DATASET = ROOT / "data" / "coder_activation.json"
ORACLE = ROOT / "data" / "oracle" / "coder_activation.json"


def pack_files():
    return {path.name for path in PACK.iterdir()}


def test_pack_declares_p0_p1_contract():
    assert {"README.md", "ontology.md", "hypotheses.md", "expected-results.json"} <= pack_files()

    expected = json.loads((PACK / "expected-results.json").read_text(encoding="utf-8"))
    assert expected["case"] == "coder-activation"
    assert expected["budget"] == 6
    assert expected["acceptance"]["compilerCriticalRecall"] == 1.0


def test_oracle_ids_exist_in_fixture_and_critical_ids_are_expected():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))

    fixture_ids = {artifact["id"] for artifact in fixture["artifacts"]}
    expected_ids = set(oracle["expected_artifact_ids"])
    critical_ids = set(oracle["critical_artifact_ids"])

    assert expected_ids <= fixture_ids
    assert critical_ids <= expected_ids


def test_ontology_declares_every_fixture_relationship_type():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    ontology = (PACK / "ontology.md").read_text(encoding="utf-8")

    relation_types = {relation["relation_type"].upper() for relation in fixture["relations"]}

    assert all(f"`{relation_type}`" in ontology for relation_type in relation_types)

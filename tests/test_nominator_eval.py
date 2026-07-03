import json

from scripts.eval_nominator import (
    compute_convergence_curve,
    compute_gold_recall,
    compute_honesty_rate,
    evaluate_models,
    extract_gold_edges,
)


def test_compute_honesty_rate_uses_g2_passed_over_total():
    assert compute_honesty_rate(g2_passed=3, total_nominated=4) == 0.75
    assert compute_honesty_rate(g2_passed=0, total_nominated=0) == 0.0


def test_compute_convergence_curve_counts_new_edges_per_round():
    round_edges = [
        [("control_8.13", "control_8.14")],
        [("control_8.14", "control_8.13"), ("control_5.19", "control_5.20")],
        [("control_5.19", "control_5.20"), ("control_5.21", "control_5.22")],
    ]

    assert compute_convergence_curve(round_edges) == [1, 1, 1]


def test_compute_gold_recall_treats_edges_as_undirected():
    survived = [
        {"from": "control_8.14", "to": "control_8.13"},
        {"from": "control_5.19", "to": "control_5.20"},
    ]
    gold = [
        {"from": "control_8.13", "to": "control_8.14"},
        {"from": "control_5.21", "to": "control_5.22"},
    ]

    assert compute_gold_recall(survived, gold) == 0.5


def test_extract_gold_edges_reads_pdca_related_only(tmp_path):
    structure_path = tmp_path / "iso27001_structure.json"
    pdca_path = tmp_path / "pdca_graph.json"
    output_path = tmp_path / "kg_gold_edges.json"
    structure_path.write_text(
        json.dumps(
            [
                {"id": "control_8.13"},
                {"id": "control_8.14"},
                {"id": "control_5.30"},
                {"id": "control_5.24"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pdca_path.write_text(
        json.dumps(
            {
                "control_8.13": {
                    "related": ["control_8.14", "control_5.30", "control_missing"],
                    "next": ["control_5.24"],
                },
                "control_8.14": {"related": ["control_8.13"], "next": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output = extract_gold_edges(
        pdca_path=pdca_path,
        structure_path=structure_path,
        output_path=output_path,
    )

    assert output_path.exists()
    assert output["source"] == str(pdca_path)
    assert output["edges"] == [
        {"from": "control_5.30", "to": "control_8.13", "source": "pdca_graph"},
        {"from": "control_8.13", "to": "control_8.14", "source": "pdca_graph"},
    ]


def test_evaluate_models_uses_pipeline_sample_argument(tmp_path, monkeypatch):
    structure_path = tmp_path / "iso27001_structure.json"
    embeddings_path = tmp_path / "clause_embeddings.json"
    gold_path = tmp_path / "kg_gold_edges.json"
    output_path = tmp_path / "nominator_eval_results.json"
    structure_path.write_text(json.dumps([{"id": "control_8.13"}]), encoding="utf-8")
    embeddings_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    gold_path.write_text(json.dumps({"edges": []}), encoding="utf-8")
    calls = []

    def fake_run_kg_pipeline(**kwargs):
        calls.append(kwargs)
        return {
            "gate_report": {
                "nominated": 0,
                "g1_rejected": 0,
                "g2_rejected": 0,
                "g3_rejected": 0,
                "g4_rejected": 0,
                "survived": 0,
            },
            "format_failures": {"mock-model": 0},
            "edges": [],
        }

    monkeypatch.setattr("scripts.eval_nominator.run_kg_pipeline", fake_run_kg_pipeline)

    evaluate_models(
        ["mock-model"],
        sample=25,
        rounds=2,
        structure_path=structure_path,
        embeddings_path=embeddings_path,
        gold_path=gold_path,
        output_path=output_path,
    )

    assert calls[0]["structure_path"] == structure_path
    assert calls[0]["sample"] == 25

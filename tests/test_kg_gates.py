from iso27001_advisor.core.kg_gates import (
    apply_degree_cap,
    gate_bidirectional,
    gate_evidence,
    gate_similarity,
    gate_structure,
)


def _id_index():
    return {
        "clause_5": {
            "id": "clause_5",
            "title": "領導",
            "content": "父章節內容",
        },
        "clause_5.1": {
            "id": "clause_5.1",
            "title": "領導及承諾",
            "content": "最高管理階層應展現領導及承諾。",
        },
        "control_8.13": {
            "id": "control_8.13",
            "title": "資訊備份",
            "content": "資訊、軟體及系統之備份複本應予維護。",
        },
        "control_8.14": {
            "id": "control_8.14",
            "title": "資訊處理設施之備援",
            "content": "資訊處理設施應以足夠備援實作。",
        },
    }


def test_gate_structure_accepts_valid_non_parent_edges():
    edge = {"from": "control_8.13", "to": "control_8.14"}

    assert gate_structure(edge, _id_index()) is True


def test_gate_structure_rejects_self_loop_and_unknown_id():
    id_index = _id_index()

    assert gate_structure({"from": "control_8.13", "to": "control_8.13"}, id_index) is False
    assert gate_structure({"from": "control_8.13", "to": "control_9.99"}, id_index) is False


def test_gate_structure_rejects_parent_child_sections():
    edge = {"from": "clause_5", "to": "clause_5.1"}

    assert gate_structure(edge, _id_index()) is False


def test_gate_evidence_accepts_title_or_content_substrings():
    edge = {
        "from": "control_8.13",
        "to": "control_8.14",
        "evidence_from": "備份複本應予維護",
        "evidence_to": "資訊處理設施",
    }

    assert gate_evidence(edge, _id_index()) is True


def test_gate_evidence_rejects_fake_or_too_short_quotes():
    id_index = _id_index()

    fake = {
        "from": "control_8.13",
        "to": "control_8.14",
        "evidence_from": "不存在的引句內容",
        "evidence_to": "資訊處理設施",
    }
    too_short = {
        "from": "control_8.13",
        "to": "control_8.14",
        "evidence_from": "備份",
        "evidence_to": "資訊處理設施",
    }

    assert gate_evidence(fake, id_index) is False
    assert gate_evidence(too_short, id_index) is False


def test_gate_similarity_accepts_vectors_above_floor():
    edge = {"from": "control_8.13", "to": "control_8.14"}
    emb_index = {"control_8.13": [1.0, 0.0], "control_8.14": [0.8, 0.2]}

    assert gate_similarity(edge, emb_index, floor=0.5) is True


def test_gate_similarity_rejects_low_similarity_or_missing_vector():
    edge = {"from": "control_8.13", "to": "control_8.14"}
    low = {"control_8.13": [1.0, 0.0], "control_8.14": [0.0, 1.0]}
    missing = {"control_8.13": [1.0, 0.0]}

    assert gate_similarity(edge, low, floor=0.5) is False
    assert gate_similarity(edge, missing, floor=0.5) is False


def test_gate_bidirectional_accepts_mutual_nomination():
    edge = {"from": "control_8.13", "to": "control_8.14"}
    nominations = [
        {"from": "control_8.13", "to": "control_8.14"},
        {"from": "control_8.14", "to": "control_8.13"},
    ]

    assert gate_bidirectional(edge, nominations) is True


def test_gate_bidirectional_rejects_single_direction():
    edge = {"from": "control_8.13", "to": "control_8.14"}
    nominations = [{"from": "control_8.13", "to": "control_8.14"}]

    assert gate_bidirectional(edge, nominations) is False


def test_apply_degree_cap_keeps_highest_similarity_edges():
    edges = [
        {"from": "control_8.13", "to": f"node_{i}", "similarity": float(i)}
        for i in range(8)
    ]

    capped = apply_degree_cap(edges, cap=6)

    kept_neighbors = {edge["to"] for edge in capped}
    assert len(capped) == 6
    assert "node_0" not in kept_neighbors
    assert "node_1" not in kept_neighbors

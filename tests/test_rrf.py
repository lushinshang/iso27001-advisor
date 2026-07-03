import pytest

from iso27001_advisor.core.hybrid_search import rrf_fuse


def test_rrf_fuse_combines_two_rankings_by_rank():
    """同時出現在兩路排名的項目，應累加兩路 RRF 分數。"""
    keyword = [{"id": "control_8.13"}, {"id": "control_8.14"}]
    vector = [{"id": "control_8.14"}, {"id": "control_8.13"}]

    fused = rrf_fuse([keyword, vector], k=60)

    assert [item_id for item_id, _score in fused] == ["control_8.13", "control_8.14"]
    assert fused[0][1] == pytest.approx((1 / 61) + (1 / 62))
    assert fused[1][1] == pytest.approx((1 / 62) + (1 / 61))


def test_rrf_fuse_keeps_single_route_items():
    keyword = [{"id": "control_8.13"}, {"id": "control_8.14"}]
    vector = [{"id": "control_5.23"}]

    fused = dict(rrf_fuse([keyword, vector], k=60))

    assert fused["control_8.13"] == pytest.approx(1 / 61)
    assert fused["control_8.14"] == pytest.approx(1 / 62)
    assert fused["control_5.23"] == pytest.approx(1 / 61)


def test_rrf_fuse_accepts_empty_rankings():
    assert rrf_fuse([], k=60) == []
    assert rrf_fuse([[]], k=60) == []


def test_rrf_fuse_k_parameter_changes_score_gap():
    ranking = [{"id": "first"}, {"id": "second"}]

    small_k = dict(rrf_fuse([ranking], k=1))
    large_k = dict(rrf_fuse([ranking], k=60))

    assert (small_k["first"] - small_k["second"]) > (
        large_k["first"] - large_k["second"]
    )

from __future__ import annotations

from shapely.geometry import LineString

from highway_topo_poc.modules.t04_rc_sw_anchor.drivezone_ops import gap_midpoint_between_pieces, pick_top_two_segment_pieces


def test_pick_top_two_segment_pieces_accepts_3d_linestring() -> None:
    segment = LineString([(0.0, 0.0), (10.0, 0.0)])
    pieces = [
        LineString([(0.5, 0.0, 1.0), (2.0, 0.0, 1.0)]),
        LineString([(3.0, 0.0, 2.0), (5.0, 0.0, 2.0)]),
        LineString([(6.0, 0.0, 3.0), (8.5, 0.0, 3.0)]),
    ]

    picked, has_extra = pick_top_two_segment_pieces(segment=segment, pieces=pieces)
    assert has_extra is True
    assert len(picked) == 2

    mid, gap = gap_midpoint_between_pieces(segment=segment, pieces=picked)
    assert mid is not None
    assert gap is not None
    assert float(gap) >= 0.0

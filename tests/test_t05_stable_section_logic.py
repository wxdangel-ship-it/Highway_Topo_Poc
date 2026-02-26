from __future__ import annotations

import numpy as np

from highway_topo_poc.modules.t05_topology_between_rc.geometry import _select_stable_section_for_end


def _profile(length_m: float = 200.0, step_m: float = 5.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    stations = np.arange(0.0, length_m + 1e-6, step_m, dtype=np.float64)
    widths = np.full((stations.size,), 8.0, dtype=np.float64)
    gore = np.zeros((stations.size,), dtype=np.float64)
    offsets = np.zeros((stations.size,), dtype=np.float64)
    return stations, widths, gore, offsets


def test_stable_section_simple_case() -> None:
    stations, widths, gore, offsets = _profile()
    dec = _select_stable_section_for_end(
        stations=stations,
        widths=widths,
        gore_overlap=gore,
        offsets=offsets,
        length_m=200.0,
        from_src=True,
        d_min=20.0,
        d_max=200.0,
        near_len=20.0,
        base_from=80.0,
        base_to=150.0,
        l_stable=30.0,
        ratio_tol=0.10,
        w_tol=1.5,
        r_gore=0.02,
        stable_fallback_m=50.0,
    )
    assert dec.is_expanded is False
    assert dec.is_gore_tip is False
    assert dec.cut_mode == "simple_near"
    assert dec.stable_s_m is not None
    assert 15.0 <= float(dec.stable_s_m) <= 30.0


def test_stable_section_expanded_case() -> None:
    stations, widths, gore, offsets = _profile()
    widths[stations < 70.0] = 11.0
    dec = _select_stable_section_for_end(
        stations=stations,
        widths=widths,
        gore_overlap=gore,
        offsets=offsets,
        length_m=200.0,
        from_src=True,
        d_min=20.0,
        d_max=200.0,
        near_len=20.0,
        base_from=80.0,
        base_to=150.0,
        l_stable=30.0,
        ratio_tol=0.10,
        w_tol=1.5,
        r_gore=0.02,
        stable_fallback_m=50.0,
    )
    assert dec.is_expanded is True
    assert dec.cut_mode == "stable_section"
    assert dec.stable_s_m is not None
    assert float(dec.stable_s_m) > 50.0


def test_gore_tip_forces_stable_mode() -> None:
    stations, widths, gore, offsets = _profile()
    gore[stations <= 35.0] = 0.3
    dec = _select_stable_section_for_end(
        stations=stations,
        widths=widths,
        gore_overlap=gore,
        offsets=offsets,
        length_m=200.0,
        from_src=True,
        d_min=20.0,
        d_max=200.0,
        near_len=20.0,
        base_from=80.0,
        base_to=150.0,
        l_stable=30.0,
        ratio_tol=0.10,
        w_tol=1.5,
        r_gore=0.02,
        stable_fallback_m=50.0,
    )
    assert dec.is_gore_tip is True
    assert dec.cut_mode in {"stable_section", "fallback_50m"}
    assert dec.cut_mode != "simple_near"

from __future__ import annotations

from highway_topo_poc.protocol.text_lint import lint_text
from highway_topo_poc.protocol.text_qc_bundle import build_demo_bundle, build_text_qc_bundle
from highway_topo_poc.utils.size_guard import MAX_BYTES, MAX_LINES, apply_size_limit, measure_text


def test_qc_bundle_format() -> None:
    payload = {
        "run_id": "t_run",
        "commit": "t_commit",
        "config_digest": "abcd1234ef",
        "patch": "t_patch",
        "provider": "synth",
        "seed": 1,
        "module": "t01",
        "module_version": "t",
        "inputs": {"traj": "ok", "pc": "missing", "vectors": "ok", "ground": "missing"},
        "input_meta": "unit_test; pasteable",
        "params": {"binN": 1000},
        "metrics": [
            {"name": "m1", "p50": 0.1, "p90": 0.2, "p99": 0.3, "threshold": 0.4, "unit": "na"},
        ],
        "binN": 1000,
        "intervals": [
            {
                "type": "demo",
                "count": 1,
                "total_len_pct": "1.00%",
                "top3": [
                    {"b0": 1, "b1": 2, "severity": "low", "len_pct": "0.50%"},
                    {"b0": 3, "b1": 4, "severity": "med", "len_pct": "0.30%"},
                    {"b0": 5, "b1": 6, "severity": "high", "len_pct": "0.20%"},
                ],
            }
        ],
        "breakpoints": ["bp1"],
        "errors": {"E1": 1},
        "notes": ["ok"],
    }

    text = build_text_qc_bundle(payload)

    assert "=== Highway_Topo_Poc TEXT_QC_BUNDLE v1 ===" in text
    assert "Project: Highway_Topo_Poc" in text
    assert "Run:" in text
    assert "Patch:" in text
    assert "Module:" in text
    assert "Inputs:" in text
    assert "Params(TopN<=12):" in text
    assert "Metrics(TopN<=10):" in text
    assert "Intervals(binN=" in text
    assert "Breakpoints:" in text
    assert "Errors:" in text
    assert "Truncated:" in text
    assert "=== END ===" in text


def test_size_limit() -> None:
    text = "\n".join([f"line{i}: " + ("x" * 200) for i in range(200)]) + "\n"
    limited, truncated, reason = apply_size_limit(text)

    assert truncated is True
    assert reason == "size_limit"
    assert len(limited.splitlines()) <= MAX_LINES
    assert len(limited.encode("utf-8")) <= MAX_BYTES
    assert "Truncated: true" in limited


def test_lint_blocks_oversize_lines() -> None:
    text = "\n".join(["x"] * (MAX_LINES + 1)) + "\n"
    ok, violations = lint_text(text)

    assert ok is False
    assert any(v.startswith("SIZE_LINES") for v in violations)


def test_lint_blocks_oversize_bytes() -> None:
    text = ("x" * (MAX_BYTES + 1)) + "\n"
    ok, violations = lint_text(text)

    assert ok is False
    assert any(v.startswith("SIZE_BYTES") for v in violations)


def test_demo_bundle_is_pasteable() -> None:
    demo = build_demo_bundle()

    s = measure_text(demo)
    assert s.lines <= MAX_LINES
    assert s.bytes_utf8 <= MAX_BYTES

    ok, violations = lint_text(demo)
    assert ok is True, violations
    assert not any(v.startswith("SIZE_") for v in violations)

    assert "Truncated: true" in demo

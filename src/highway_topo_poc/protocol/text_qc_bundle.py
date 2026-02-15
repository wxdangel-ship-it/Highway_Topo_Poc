from __future__ import annotations

import hashlib
from dataclasses import dataclass

from highway_topo_poc.protocol.text_lint import lint_text
from highway_topo_poc.utils.size_guard import apply_size_limit, within_limits


_TEMPLATE = """=== Highway_Topo_Poc TEXT_QC_BUNDLE v1 ===
Project: Highway_Topo_Poc
Run: <run_id>  Commit: <short_sha_or_tag>  ConfigDigest: <8-12chars>
Patch: <patch_uid_or_alias>  Provider: <file|synth>  Seed: <int_or_na>
Module: <t01|t02|t03|t04|t05>  ModuleVersion: <semver_or_sha>

Inputs: traj=<ok|missing>  pc=<ok|missing>  vectors=<ok|missing>  ground=<ok|missing>
InputMeta: <type/resolution/field_availability_summary; NO PATH; NO COORD>

Params(TopN<=12): <k1=v1; k2=v2; ...>

Metrics(TopN<=10):
- <metric_name_1>: p50=<num> p90=<num> p99=<num> threshold=<num|na> unit=<...>
- <metric_name_2>: p50=<num> p90=<num> p99=<num> threshold=<num|na> unit=<...>

Intervals(binN=<N>):
- type=<enum>  count=<int>  total_len_pct=<num%>
  top3=(<b0>-<b1>, severity=<low|med|high>, len_pct=<%>); (<b0>-<b1>, ...); (<b0>-<b1>, ...)

Breakpoints: [<enum1>, <enum2>, ...]
Errors: [<reason_enum>:<count>, <reason_enum>:<count>, ...]
Notes: <1-3 lines max>
Truncated: <true|false> (reason=<na|size_limit|...>)
=== END ===
"""


def qc_bundle_template() -> str:
    return _TEMPLATE.rstrip("\n")


def _one_line(v: object) -> str:
    s = "na" if v is None else str(v)
    return " ".join(s.replace("\t", " ").splitlines()).strip() or "na"


def _fmt_pct(v: object) -> str:
    if v is None:
        return "na%"
    s = str(v).strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        f = float(s)
    except Exception:
        return "na%"
    return f"{f:.2f}%"


def _fmt_num(v: object) -> str:
    if v is None:
        return "na"
    try:
        f = float(v)
    except Exception:
        return _one_line(v)
    return f"{f:.6g}"


def _top_dict_items(d: dict[str, object], n: int) -> list[tuple[str, object]]:
    # Stable order: by key.
    items = sorted(d.items(), key=lambda kv: kv[0])
    return items[:n]


def _top_errors(errors: dict[str, int], n: int) -> list[tuple[str, int]]:
    items = sorted(errors.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    return items[:n]


def _parse_pct(p: str) -> float:
    try:
        return float(str(p).rstrip("%").strip())
    except Exception:
        return 0.0


def _render(payload: dict, truncated: bool, reason: str) -> str:
    project = "Highway_Topo_Poc"
    run_id = _one_line(payload.get("run_id", "na"))
    commit = _one_line(payload.get("commit", "na"))
    config_digest = _one_line(payload.get("config_digest", "na"))
    patch = _one_line(payload.get("patch", "na"))
    provider = _one_line(payload.get("provider", "na"))
    seed = _one_line(payload.get("seed", "na"))
    module = _one_line(payload.get("module", "na"))
    module_version = _one_line(payload.get("module_version", "na"))

    inputs = payload.get("inputs", {}) or {}
    traj = _one_line(inputs.get("traj", "missing"))
    pc = _one_line(inputs.get("pc", "missing"))
    vectors = _one_line(inputs.get("vectors", "missing"))
    ground = _one_line(inputs.get("ground", "missing"))

    input_meta = _one_line(payload.get("input_meta", "na"))

    params = payload.get("params", {}) or {}
    params_items = _top_dict_items({str(k): v for k, v in params.items()}, 12)
    params_str = "; ".join([f"{_one_line(k)}={_one_line(v)}" for k, v in params_items]) or "na"

    metrics = payload.get("metrics", []) or []
    metrics = metrics[:10]

    binN = int(payload.get("binN", payload.get("bin_n", payload.get("binN", 1000))) or 1000)

    intervals = payload.get("intervals", []) or []

    breakpoints = payload.get("breakpoints", []) or []
    breakpoints = breakpoints[:20]

    errors = payload.get("errors", {}) or {}
    if isinstance(errors, list):
        # Accept [(reason, count), ...]
        errors = {str(k): int(v) for k, v in errors}
    errors_items = _top_errors({str(k): int(v) for k, v in errors.items()}, 20)
    errors_str = ", ".join([f"{_one_line(k)}:{int(v)}" for k, v in errors_items]) or "na"

    notes = payload.get("notes", "")
    if isinstance(notes, str):
        notes_lines = [notes] if notes.strip() else []
    else:
        notes_lines = [str(x) for x in notes]
    notes_lines = [_one_line(x) for x in notes_lines if str(x).strip()]
    notes_lines = notes_lines[:3] or ["na"]

    out: list[str] = []
    out.append("=== Highway_Topo_Poc TEXT_QC_BUNDLE v1 ===")
    out.append(f"Project: {project}")
    out.append(f"Run: {run_id}  Commit: {commit}  ConfigDigest: {config_digest}")
    out.append(f"Patch: {patch}  Provider: {provider}  Seed: {seed}")
    out.append(f"Module: {module}  ModuleVersion: {module_version}")
    out.append("")

    out.append(f"Inputs: traj={traj}  pc={pc}  vectors={vectors}  ground={ground}")
    out.append(f"InputMeta: {input_meta}")
    out.append("")

    out.append(f"Params(TopN<=12): {params_str}")
    out.append("")

    out.append("Metrics(TopN<=10):")
    if not metrics:
        out.append("- na: p50=na p90=na p99=na threshold=na unit=na")
    else:
        for m in metrics:
            name = _one_line(m.get("name", "na"))
            p50 = _fmt_num(m.get("p50"))
            p90 = _fmt_num(m.get("p90"))
            p99 = _fmt_num(m.get("p99"))
            thr = _fmt_num(m.get("threshold"))
            unit = _one_line(m.get("unit", "na"))
            out.append(f"- {name}: p50={p50} p90={p90} p99={p99} threshold={thr} unit={unit}")
    out.append("")

    out.append(f"Intervals(binN={binN}):")
    if not intervals:
        out.append("- type=na  count=0  total_len_pct=0.00%")
        out.append("  top3=(0-0, severity=low, len_pct=0.00%); (0-0, severity=low, len_pct=0.00%); (0-0, severity=low, len_pct=0.00%)")
    else:
        for g in intervals:
            t = _one_line(g.get("type", "na"))
            count = int(g.get("count", 0) or 0)
            total_len_pct = _fmt_pct(g.get("total_len_pct", 0.0))
            out.append(f"- type={t}  count={count}  total_len_pct={total_len_pct}")

            top3 = g.get("top3", []) or []
            top3 = list(top3)[:3]
            parts = []
            for it in top3:
                b0 = int(it.get("b0", 0) or 0)
                b1 = int(it.get("b1", 0) or 0)
                sev = _one_line(it.get("severity", "low"))
                lp = _fmt_pct(it.get("len_pct", 0.0))
                parts.append(f"({b0}-{b1}, severity={sev}, len_pct={lp})")
            while len(parts) < 3:
                parts.append("(0-0, severity=low, len_pct=0.00%)")
            out.append("  top3=" + "; ".join(parts))
    out.append("")

    bp_str = ", ".join([_one_line(x) for x in breakpoints])
    out.append(f"Breakpoints: [{bp_str}]")
    out.append(f"Errors: [{errors_str}]")

    if len(notes_lines) == 1:
        out.append(f"Notes: {notes_lines[0]}")
    else:
        out.append(f"Notes: {notes_lines[0]}")
        for extra in notes_lines[1:]:
            out.append(f"Notes: {extra}")

    out.append(f"Truncated: {'true' if truncated else 'false'} (reason={reason})")
    out.append("=== END ===")

    return "\n".join(out) + "\n"


def build_text_qc_bundle(payload: dict) -> str:
    """Build a TEXT_QC_BUNDLE v1 text.

    Hard guarantees:
    - Enforces size budget (<=120 lines OR <=8KB) with a clear Truncated marker.
    - Runs a conservative lint check and refuses to output forbidden info.
    """

    full = _render(payload, truncated=False, reason="na")
    if within_limits(full):
        ok, viol = lint_text(full)
        if not ok:
            raise ValueError(f"lint failed: {viol}")
        return full.rstrip("\n")

    # Structured trimming per protocol guidance: keep essentials, drop long tails.
    trimmed = dict(payload)

    # Keep only Top-3 interval groups by total_len_pct.
    intervals = list(payload.get("intervals", []) or [])
    intervals_sorted = sorted(
        intervals,
        key=lambda g: -_parse_pct(str(g.get("total_len_pct", "0%"))),
    )
    trimmed["intervals"] = intervals_sorted[:3]

    # Keep only Top-3 errors by count.
    errors = payload.get("errors", {}) or {}
    if isinstance(errors, list):
        errors = {str(k): int(v) for k, v in errors}
    trimmed_errors = _top_errors({str(k): int(v) for k, v in errors.items()}, 3)
    trimmed["errors"] = {k: v for k, v in trimmed_errors}

    # Keep Notes compact.
    trimmed["notes"] = [
        "Truncated due to size_limit; showing Top metrics/intervals/errors only.",
    ]

    reduced = _render(trimmed, truncated=True, reason="size_limit")
    if not within_limits(reduced):
        reduced, _tr, _reason = apply_size_limit(reduced)

    ok, viol = lint_text(reduced)
    if not ok:
        raise ValueError(f"lint failed: {viol}")

    return reduced.rstrip("\n")


def build_demo_bundle() -> str:
    # Stable demo identifiers; no paths, no coords, no geometry.
    digest = hashlib.sha1(b"demo_config").hexdigest()[:10]

    # Many interval groups -> force size trimming demonstration.
    intervals = []
    for i in range(80):
        intervals.append(
            {
                "type": f"demo_type_{i:02d}",
                "count": 1 + (i % 7),
                "total_len_pct": f"{0.10 + (i % 10) * 0.11:.2f}%",
                "top3": [
                    {"b0": i, "b1": i + 1, "severity": "low", "len_pct": "0.10%"},
                    {"b0": i + 2, "b1": i + 3, "severity": "med", "len_pct": "0.08%"},
                    {"b0": i + 4, "b1": i + 5, "severity": "high", "len_pct": "0.06%"},
                ],
            }
        )

    payload = {
        "run_id": "demo_run_01",
        "commit": "demo",
        "config_digest": digest,
        "patch": "patch_demo_001",
        "provider": "synth",
        "seed": 123,
        "module": "t01",
        "module_version": "demo",
        "inputs": {"traj": "ok", "pc": "ok", "vectors": "ok", "ground": "missing"},
        "input_meta": "demo_input; synthetic; fields=ok; no_coords",
        "params": {
            "binN": 1000,
            "z_diff_threshold": 0.20,
            "interval_min_len_bin": 5,
        },
        "metrics": [
            {"name": "z_diff", "p50": 0.01, "p90": 0.09, "p99": 0.18, "threshold": 0.20, "unit": "m"},
            {"name": "residual", "p50": 0.02, "p90": 0.10, "p99": 0.19, "threshold": 0.25, "unit": "m"},
        ],
        "binN": 1000,
        "intervals": intervals,
        "breakpoints": ["manual_review", "check_thresholds"],
        "errors": {"E_DEMO_WARN": 2, "E_DEMO_FAIL": 1},
        "notes": ["demo bundle; safe; triggers truncation"],
    }

    return build_text_qc_bundle(payload)

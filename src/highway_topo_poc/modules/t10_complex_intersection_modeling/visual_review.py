from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .manual_mode_support import (
    build_approach_catalog,
    build_review_nonstandard_targets,
    build_review_special_profile_gaps,
    build_review_unknown_movements,
)

_STATUS_CLASS = {
    "allowed": "status-allowed",
    "forbidden": "status-forbidden",
    "unknown": "status-unknown",
}

_TURN_SHORT = {
    "left": "L",
    "through": "T",
    "right": "R",
    "uturn": "U",
    "unknown": "?",
}


def build_t10_review_html(result: Any) -> str:
    catalog = build_approach_catalog(result)
    unknown_payload = build_review_unknown_movements(result)
    nonstandard_payload = build_review_nonstandard_targets(result)
    gap_payload = build_review_special_profile_gaps(result)

    approach_lookup = {item["approach_id"]: item for item in catalog["approaches"]}
    arm_labels = {
        arm.arm_id: f"Arm {idx + 1}"
        for idx, arm in enumerate(result.bundle.arms)
    }
    entry_groups = _group_approaches(result, movement_side="entry", arm_labels=arm_labels)
    exit_groups = _group_approaches(result, movement_side="exit", arm_labels=arm_labels)
    movement_lookup = {
        (item["source_approach_id"], item["target_approach_id"]): item
        for item in result.movement_results
    }
    detail_lookup = _build_movement_detail_lookup(
        result=result,
        movement_lookup=movement_lookup,
        approach_lookup=approach_lookup,
        arm_labels=arm_labels,
    )

    total_movements = len(result.movement_results)
    unknown_count = unknown_payload["unknown_movement_count"]
    nonstandard_count = nonstandard_payload["target_count"]
    gap_count = gap_payload["candidate_count"]

    matrix_html = _build_matrix_html(
        entry_groups=entry_groups,
        exit_groups=exit_groups,
        movement_lookup=movement_lookup,
    )
    review_sections_html = _build_review_sections_html(
        unknown_payload=unknown_payload,
        nonstandard_payload=nonstandard_payload,
        gap_payload=gap_payload,
        approach_lookup=approach_lookup,
    )

    embedded_details = json.dumps(detail_lookup, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>T10 Review Bundle - {escape(str(result.bundle.intersection.intersection_id))}</title>
  <style>
    :root {{
      --bg: #f5f3ee;
      --panel: #fffdf8;
      --line: #d7d0c3;
      --text: #2f2a22;
      --muted: #726859;
      --allowed: #d8ead8;
      --forbidden: #f0d2cf;
      --unknown: #f6edbe;
      --empty: #ebe5da;
      --accent: #1d4f91;
      --shadow: 0 10px 28px rgba(47, 42, 34, 0.08);
      --mono: "Cascadia Code", "Consolas", monospace;
      --sans: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(29,79,145,0.08), transparent 28%),
        linear-gradient(180deg, #f7f4ee 0%, #efe8dc 100%);
    }}
    .page {{
      max-width: 1800px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      gap: 18px;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 20px 24px;
    }}
    .hero h1 {{
      margin: 0 0 6px 0;
      font-size: 28px;
      letter-spacing: 0.02em;
    }}
    .hero .meta {{
      color: var(--muted);
      font-size: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 18px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .card {{
      padding: 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #faf8f2;
    }}
    .card .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .card .value {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 700;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      padding: 18px;
    }}
    .panel h2 {{
      margin: 0 0 14px 0;
      font-size: 18px;
    }}
    .review-block + .review-block {{
      margin-top: 16px;
    }}
    .review-block details {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fbf8f1;
    }}
    .review-block summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    .review-items {{
      margin: 10px 0 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
    }}
    .review-items button {{
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      background: white;
      border-radius: 10px;
      padding: 8px 10px;
      color: var(--text);
      cursor: pointer;
      font-family: inherit;
    }}
    .review-items button:hover {{
      border-color: var(--accent);
    }}
    .matrix-shell {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: white;
    }}
    table.matrix {{
      border-collapse: separate;
      border-spacing: 0;
      min-width: 980px;
      width: 100%;
    }}
    .matrix th, .matrix td {{
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 0;
      vertical-align: top;
    }}
    .matrix tr:first-child th {{
      border-top: none;
    }}
    .matrix th:first-child,
    .matrix td:first-child {{
      border-left: none;
    }}
    .sticky-col-1 {{
      position: sticky;
      left: 0;
      z-index: 3;
      background: #fcfaf4;
      min-width: 92px;
      max-width: 92px;
    }}
    .sticky-col-2 {{
      position: sticky;
      left: 92px;
      z-index: 3;
      background: #fcfaf4;
      min-width: 180px;
      max-width: 180px;
    }}
    .matrix thead th {{
      position: sticky;
      top: 0;
      z-index: 4;
      background: #f7f1e6;
    }}
    .matrix thead .sticky-col-1,
    .matrix thead .sticky-col-2 {{
      z-index: 5;
    }}
    .arm-head {{
      text-align: center;
      padding: 10px 8px;
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
      background: #efe4d0;
    }}
    .approach-head {{
      padding: 10px 8px;
      font-size: 12px;
      text-align: center;
      background: #f6efe1;
    }}
    .source-arm {{
      padding: 10px 8px;
      font-weight: 700;
      text-align: center;
      background: #f1e8d8;
    }}
    .source-approach {{
      padding: 10px 10px;
      background: #faf7ef;
    }}
    .source-approach .road,
    .approach-head .road {{
      font-weight: 700;
      display: block;
    }}
    .source-approach .meta,
    .approach-head .meta {{
      color: var(--muted);
      font-size: 11px;
      margin-top: 3px;
    }}
    .matrix-cell {{
      width: 100%;
      min-height: 64px;
      border: none;
      background: var(--empty);
      cursor: pointer;
      padding: 6px;
      font: inherit;
      color: var(--text);
    }}
    .matrix-cell:hover {{
      outline: 2px solid rgba(29,79,145,0.35);
      outline-offset: -2px;
    }}
    .matrix-cell.is-selected {{
      outline: 3px solid var(--accent);
      outline-offset: -3px;
    }}
    .matrix-cell.status-allowed {{ background: var(--allowed); }}
    .matrix-cell.status-forbidden {{ background: var(--forbidden); }}
    .matrix-cell.status-unknown {{ background: var(--unknown); }}
    .cell-main {{
      font-weight: 700;
      font-size: 16px;
      line-height: 1.1;
    }}
    .cell-sub {{
      margin-top: 4px;
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .detail {{
      margin-top: 18px;
      border-top: 1px solid var(--line);
      padding-top: 18px;
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 18px;
    }}
    .detail-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: #fbf8f1;
    }}
    .detail-card h3 {{
      margin: 0 0 10px 0;
      font-size: 15px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 6px 10px;
      font-size: 13px;
    }}
    .kv .key {{
      color: var(--muted);
    }}
    pre.json-view {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.4;
    }}
    .note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
    }}
    @media (max-width: 1200px) {{
      .layout, .detail {{
        grid-template-columns: 1fr;
      }}
      .cards {{
        grid-template-columns: repeat(2, minmax(120px, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>T10 Review Bundle</h1>
      <div class="meta">
        <span>intersection_id = {escape(str(result.bundle.intersection.intersection_id))}</span>
        <span>mainid = {escape(str(result.bundle.intersection.node_group_id))}</span>
        <span>signalized_control_zone_id = {escape(str(result.bundle.intersection.signalized_control_zone_id))}</span>
      </div>
      <div class="cards">
        {_summary_card("Approaches", len(result.bundle.approaches))}
        {_summary_card("Movements", total_movements)}
        {_summary_card("Unknown", unknown_count)}
        {_summary_card("Nonstandard Targets", nonstandard_count)}
        {_summary_card("Profile Gaps", gap_count)}
        {_summary_card("Arms", len(result.bundle.arms))}
      </div>
    </section>

    <div class="layout">
      <aside class="panel">
        <h2>Review Focus</h2>
        {review_sections_html}
      </aside>

      <section class="panel">
        <h2>Source Arm / Approach -> Target Arm / Approach</h2>
        <div class="note">矩阵颜色表示 status；格子主码为 turn_sense，副码为 parallel_cross_count。</div>
        <div class="matrix-shell">
          {matrix_html}
        </div>

        <div class="detail">
          <div class="detail-card">
            <h3>Selected Movement</h3>
            <div id="movement-kv" class="kv">
              <div class="key">状态</div><div>点击矩阵格子查看详情</div>
            </div>
            <div class="note">推荐先从黄色 unknown 或 review 列表中的项开始看。</div>
          </div>
          <div class="detail-card">
            <h3>Selected Payload</h3>
            <pre id="movement-json" class="json-view">{{}}</pre>
          </div>
        </div>
      </section>
    </div>
  </div>
  <script>
    const MOVEMENT_DETAILS = {embedded_details};
    const STATUS_CLASS = {json.dumps(_STATUS_CLASS, ensure_ascii=False)};

    function renderDetail(payload) {{
      const kv = document.getElementById("movement-kv");
      const jsonView = document.getElementById("movement-json");
      if (!payload) {{
        kv.innerHTML = '<div class="key">状态</div><div>点击矩阵格子查看详情</div>';
        jsonView.textContent = '{{}}';
        return;
      }}
      const rows = [
        ['movement_id', payload.movement_id],
        ['source_arm', payload.source_arm_label],
        ['source_approach', payload.source_approach_id],
        ['target_arm', payload.target_arm_label],
        ['target_approach', payload.target_approach_id],
        ['status', payload.status],
        ['confidence', payload.confidence],
        ['turn_sense', payload.turn_sense],
        ['parallel_cross_count', payload.parallel_cross_count],
        ['reason_codes', (payload.reason_codes || []).join(', ') || '(none)'],
        ['breakpoints', (payload.breakpoints || []).join(', ') || '(none)'],
      ];
      kv.innerHTML = rows.map(([k, v]) => '<div class="key">' + escapeHtml(k) + '</div><div>' + escapeHtml(String(v ?? '')) + '</div>').join('');
      jsonView.textContent = JSON.stringify(payload, null, 2);
    }}

    function clearSelected() {{
      document.querySelectorAll('.matrix-cell.is-selected').forEach((el) => el.classList.remove('is-selected'));
    }}

    function selectMovement(movementId) {{
      const payload = MOVEMENT_DETAILS[movementId];
      clearSelected();
      document.querySelectorAll('[data-movement-id="' + cssEscape(movementId) + '"]').forEach((el) => el.classList.add('is-selected'));
      renderDetail(payload);
    }}

    function escapeHtml(text) {{
      return text
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function cssEscape(text) {{
      if (window.CSS && typeof window.CSS.escape === 'function') {{
        return window.CSS.escape(text);
      }}
      return text.replaceAll('"', '\\"');
    }}
  </script>
</body>
</html>
"""


def write_t10_review_html(result: Any, output_dir: str | Path) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    review_path = resolved_dir / "review_bundle.html"
    review_path.write_text(build_t10_review_html(result), encoding="utf-8")
    return {"review_bundle.html": str(review_path)}


def build_t10_run_diff_html(diff_payload: dict[str, Any]) -> str:
    movement_changes = diff_payload.get("movement_status_changes", [])
    reason_changes = diff_payload.get("movement_primary_reason_changes", [])
    review_changes = diff_payload.get("review_changes", {})

    movement_rows = "".join(
        f"<tr><td>{escape(item.get('source_approach_id', ''))}</td>"
        f"<td>{escape(item.get('target_approach_id', ''))}</td>"
        f"<td>{escape(str(item.get('before_status', item.get('before_present'))))}</td>"
        f"<td>{escape(str(item.get('after_status', item.get('after_present'))))}</td>"
        f"<td>{escape(str(item.get('before_primary_reason_code', '')))}</td>"
        f"<td>{escape(str(item.get('after_primary_reason_code', '')))}</td></tr>"
        for item in movement_changes[:200]
    ) or "<tr><td colspan='6'>No movement status changes</td></tr>"

    reason_rows = "".join(
        f"<tr><td>{escape(item.get('source_approach_id', ''))}</td>"
        f"<td>{escape(item.get('target_approach_id', ''))}</td>"
        f"<td>{escape(str(item.get('before_primary_reason_code', '')))}</td>"
        f"<td>{escape(str(item.get('after_primary_reason_code', '')))}</td></tr>"
        for item in reason_changes[:200]
    ) or "<tr><td colspan='4'>No primary reason changes</td></tr>"

    review_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{escape(str(payload.get('before_count')))}</td>"
        f"<td>{escape(str(payload.get('after_count')))}</td><td>{escape(str(payload.get('delta')))}</td></tr>"
        for name, payload in review_changes.items()
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>T10 Run Diff</title>
  <style>
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #f7f4ef 0%, #ede5d8 100%);
      color: #2f2a22;
    }}
    .page {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      gap: 18px;
    }}
    .panel {{
      background: #fffdf8;
      border: 1px solid #d9d0c0;
      border-radius: 18px;
      padding: 18px 20px;
      box-shadow: 0 10px 24px rgba(47, 42, 34, 0.08);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 12px;
    }}
    .card {{
      border: 1px solid #ddd1bf;
      border-radius: 12px;
      padding: 12px;
      background: #faf7f0;
    }}
    .card .label {{ color: #726859; font-size: 12px; text-transform: uppercase; }}
    .card .value {{ margin-top: 6px; font-size: 24px; font-weight: 700; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      background: white;
    }}
    th, td {{
      border: 1px solid #ddd1bf;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      background: #f3ebde;
    }}
    h1, h2 {{
      margin: 0 0 10px 0;
    }}
    .meta {{
      color: #726859;
      font-size: 13px;
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      margin-top: 8px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="panel">
      <h1>T10 Run Diff</h1>
      <div class="meta">
        <span>before_dir = {escape(str(diff_payload.get("before_dir", "")))}</span>
        <span>after_dir = {escape(str(diff_payload.get("after_dir", "")))}</span>
      </div>
      <div class="cards">
        {_summary_card("Status Changes", diff_payload.get("movement_status_change_count", 0))}
        {_summary_card("Reason Changes", diff_payload.get("movement_primary_reason_change_count", 0))}
        {_summary_card("Before Entries", diff_payload.get("matrix_changes", {}).get("before_entry_count", 0))}
        {_summary_card("After Entries", diff_payload.get("matrix_changes", {}).get("after_entry_count", 0))}
        {_summary_card("After Cells", diff_payload.get("matrix_changes", {}).get("after_cell_count", 0))}
      </div>
    </section>

    <section class="panel">
      <h2>Review Count Changes</h2>
      <table>
        <thead>
          <tr><th>Review Bucket</th><th>Before</th><th>After</th><th>Delta</th></tr>
        </thead>
        <tbody>
          {review_rows}
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Movement Status Changes</h2>
      <table>
        <thead>
          <tr>
            <th>Source Approach</th>
            <th>Target Approach</th>
            <th>Before Status</th>
            <th>After Status</th>
            <th>Before Primary Reason</th>
            <th>After Primary Reason</th>
          </tr>
        </thead>
        <tbody>
          {movement_rows}
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Primary Reason Changes</h2>
      <table>
        <thead>
          <tr>
            <th>Source Approach</th>
            <th>Target Approach</th>
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {reason_rows}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def write_t10_run_diff_html(diff_payload: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    diff_html_path = resolved_dir / "run_diff.html"
    diff_html_path.write_text(build_t10_run_diff_html(diff_payload), encoding="utf-8")
    return {"run_diff.html": str(diff_html_path)}


def _group_approaches(result: Any, *, movement_side: str, arm_labels: dict[str, str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    arm_order = {arm.arm_id: idx for idx, arm in enumerate(result.bundle.arms)}
    approaches = [item for item in result.bundle.approaches if item.movement_side == movement_side]
    approaches.sort(
        key=lambda item: (
            arm_order.get(item.arm_id, 999),
            item.lateral_rank is None,
            item.lateral_rank if item.lateral_rank is not None else 999,
            item.road_id,
            item.approach_id,
        )
    )
    grouped: dict[str, list[Any]] = {}
    for approach in approaches:
        grouped.setdefault(approach.arm_id, []).append(approach)
    for arm in result.bundle.arms:
        if arm.arm_id not in grouped:
            continue
        groups.append(
            {
                "arm_id": arm.arm_id,
                "arm_label": arm_labels.get(arm.arm_id, arm.arm_id),
                "approaches": grouped[arm.arm_id],
            }
        )
    return groups


def _build_movement_detail_lookup(
    *,
    result: Any,
    movement_lookup: dict[tuple[str, str], dict[str, Any]],
    approach_lookup: dict[str, dict[str, Any]],
    arm_labels: dict[str, str],
) -> dict[str, dict[str, Any]]:
    detail_lookup: dict[str, dict[str, Any]] = {}
    for movement in result.movement_results:
        source_id = movement["source_approach_id"]
        target_id = movement["target_approach_id"]
        source = approach_lookup.get(source_id, {})
        target = approach_lookup.get(target_id, {})
        detail_lookup[movement["movement_id"]] = {
            **movement,
            "source_arm_id": source.get("arm_id"),
            "source_arm_label": arm_labels.get(source.get("arm_id"), source.get("arm_id")),
            "source_road_id": source.get("road_id"),
            "source_selector_hints": source.get("selector_hints"),
            "target_arm_id": target.get("arm_id"),
            "target_arm_label": arm_labels.get(target.get("arm_id"), target.get("arm_id")),
            "target_road_id": target.get("road_id"),
            "target_selector_hints": target.get("selector_hints"),
        }
    return detail_lookup


def _build_matrix_html(
    *,
    entry_groups: list[dict[str, Any]],
    exit_groups: list[dict[str, Any]],
    movement_lookup: dict[tuple[str, str], dict[str, Any]],
) -> str:
    header_group_row = [
        '<tr>',
        '<th class="sticky-col-1 arm-head" rowspan="2">Source Arm</th>',
        '<th class="sticky-col-2 arm-head" rowspan="2">Source Approach</th>',
    ]
    for group in exit_groups:
        header_group_row.append(
            f'<th class="arm-head" colspan="{len(group["approaches"])}">{escape(group["arm_label"])}</th>'
        )
    header_group_row.append("</tr>")

    header_approach_row = ['<tr>']
    for group in exit_groups:
        for approach in group["approaches"]:
            header_approach_row.append(
                "<th class=\"approach-head\">"
                f"<span class=\"road\">{escape(str(approach.road_id))}</span>"
                f"<span class=\"meta\">{escape(str(approach.approach_id.split('|')[-1]))}</span>"
                "</th>"
            )
    header_approach_row.append("</tr>")

    body_rows: list[str] = []
    for group in entry_groups:
        approaches = group["approaches"]
        for idx, approach in enumerate(approaches):
            row_parts = ["<tr>"]
            if idx == 0:
                row_parts.append(
                    f'<th class="sticky-col-1 source-arm" rowspan="{len(approaches)}">{escape(group["arm_label"])}</th>'
                )
            row_parts.append(
                "<th class=\"sticky-col-2 source-approach\">"
                f"<span class=\"road\">{escape(str(approach.road_id))}</span>"
                f"<span class=\"meta\">{escape(str(approach.approach_id.split('|')[-1]))}</span>"
                "</th>"
            )
            for target_group in exit_groups:
                for target in target_group["approaches"]:
                    movement = movement_lookup.get((approach.approach_id, target.approach_id))
                    row_parts.append(_build_matrix_cell_html(movement))
            row_parts.append("</tr>")
            body_rows.append("".join(row_parts))

    return (
        '<table class="matrix"><thead>'
        + "".join(header_group_row)
        + "".join(header_approach_row)
        + "</thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def _build_matrix_cell_html(movement: dict[str, Any] | None) -> str:
    if movement is None:
        return '<td><div class="matrix-cell">-</div></td>'
    status = str(movement.get("status", "unknown"))
    status_class = _STATUS_CLASS.get(status, "status-unknown")
    turn_short = _TURN_SHORT.get(str(movement.get("turn_sense", "unknown")), "?")
    cross = str(movement.get("parallel_cross_count", "?"))
    movement_id = str(movement.get("movement_id"))
    movement_id_attr = escape(movement_id)
    movement_id_js = json.dumps(movement_id, ensure_ascii=False)
    title = escape(str(movement.get("reason_text", "")))
    return (
        "<td>"
        f"<button type=\"button\" class=\"matrix-cell {status_class}\" title=\"{title}\" "
        f"data-movement-id=\"{movement_id_attr}\" onclick='selectMovement({movement_id_js})'>"
        f"<div class=\"cell-main\">{escape(turn_short)} {escape(cross)}</div>"
        f"<div class=\"cell-sub\">{escape(status)}</div>"
        "</button>"
        "</td>"
    )


def _build_review_sections_html(
    *,
    unknown_payload: dict[str, Any],
    nonstandard_payload: dict[str, Any],
    gap_payload: dict[str, Any],
    approach_lookup: dict[str, dict[str, Any]],
) -> str:
    unknown_items = "".join(
        _review_item_button(
            label=f"{_approach_short(item['source_approach_id'], approach_lookup)} → {_approach_short(item['target_approach_id'], approach_lookup)}",
            subtitle=" / ".join(item.get("reason_codes", [])[:2]) or "unknown",
            movement_id=item["movement_id"],
        )
        for item in unknown_payload.get("items", [])[:80]
    ) or "<li>No unknown movements</li>"

    nonstandard_items = "".join(
        "<li><button type=\"button\" disabled>"
        f"{escape(_approach_short(item['approach_id'], approach_lookup))} | {escape(str(item['exit_leg_role']))}"
        "</button></li>"
        for item in nonstandard_payload.get("items", [])[:80]
    ) or "<li>No nonstandard targets</li>"

    gap_items = "".join(
        "<li><button type=\"button\" disabled>"
        f"{escape(_approach_short(item['approach_id'], approach_lookup))} | {escape(str(item['review_reason']))}"
        "</button></li>"
        for item in gap_payload.get("items", [])[:80]
    ) or "<li>No profile-gap candidates</li>"

    return (
        _review_block_html("Unknown Movements", unknown_payload.get("unknown_movement_count"), unknown_items)
        + _review_block_html("Nonstandard Targets", nonstandard_payload.get("target_count"), nonstandard_items)
        + _review_block_html("Special Profile Gaps", gap_payload.get("candidate_count"), gap_items)
    )


def _review_block_html(title: str, count: Any, items_html: str) -> str:
    return (
        '<div class="review-block"><details open>'
        f"<summary>{escape(title)} ({escape(str(count))})</summary>"
        f'<ul class="review-items">{items_html}</ul>'
        "</details></div>"
    )


def _review_item_button(*, label: str, subtitle: str, movement_id: str) -> str:
    safe_id = json.dumps(movement_id, ensure_ascii=False)
    return (
        "<li><button type=\"button\" "
        f"onclick='selectMovement({safe_id})'>"
        f"{escape(label)}<br><span class=\"note\">{escape(subtitle)}</span>"
        "</button></li>"
    )


def _approach_short(approach_id: str, approach_lookup: dict[str, dict[str, Any]]) -> str:
    payload = approach_lookup.get(approach_id)
    if not payload:
        return approach_id
    return f"{payload['road_id']} ({payload['movement_side']})"


def _summary_card(label: str, value: Any) -> str:
    return (
        '<div class="card">'
        f'<div class="label">{escape(str(label))}</div>'
        f'<div class="value">{escape(str(value))}</div>'
        "</div>"
    )


__all__ = [
    "build_t10_review_html",
    "build_t10_run_diff_html",
    "write_t10_review_html",
    "write_t10_run_diff_html",
]

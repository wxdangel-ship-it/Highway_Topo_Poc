from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .field_norm import get_first_int, normalize_key, normalize_props
from .io_geojson import read_geojson


_DEFAULT_ID_KEYS = ["id", "mainnodeid", "mainid", "nodeid"]
_DEFAULT_KIND_KEYS = ["kind", "Kind", "KIND"]


def _parse_int_auto(raw: str) -> int:
    text = str(raw).strip()
    if not text:
        raise ValueError("empty_int")
    return int(text, 0)


def _dedup_preserve(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = str(item).strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _kind_histogram_topn(kind_counter: Counter[int], *, limit: int = 20) -> list[dict[str, int]]:
    items = sorted(kind_counter.items(), key=lambda kv: (-int(kv[1]), int(kv[0])))
    out: list[dict[str, int]] = []
    for kind, cnt in items[: max(0, int(limit))]:
        out.append({"kind": int(kind), "count": int(cnt)})
    return out


def discover_node_ids_from_rcsdnode(
    rcsdnode_path: Path,
    kind_mask: int,
    id_key_preference: list[str] = _DEFAULT_ID_KEYS,
    kind_key_preference: list[str] = _DEFAULT_KIND_KEYS,
) -> tuple[list[int], dict[str, Any]]:
    payload = read_geojson(Path(rcsdnode_path))
    features = payload.get("features", [])
    if not isinstance(features, list):
        raise ValueError(f"geojson_features_not_list: {rcsdnode_path}")

    mask = int(kind_mask)
    id_keys = _dedup_preserve([normalize_key(k) for k in id_key_preference])
    kind_keys = _dedup_preserve([normalize_key(k) for k in kind_key_preference])
    if not id_keys:
        raise ValueError("id_key_preference_empty")
    if not kind_keys:
        raise ValueError("kind_key_preference_empty")

    selected_raw: list[int] = []
    kind_hist = Counter()
    id_field_hits = {k: 0 for k in id_keys}
    kind_field_hits = {k: 0 for k in kind_keys}
    filtered_reasons = {"no_id": 0, "no_kind": 0, "kind_not_allowed": 0}

    total_features = 0
    total_with_id = 0
    total_with_kind = 0

    for feat in features:
        total_features += 1
        if isinstance(feat, dict):
            props_raw = feat.get("properties")
            props = props_raw if isinstance(props_raw, dict) else {}
        else:
            props = {}
        props_norm = normalize_props(props)

        nodeid_val: int | None = None
        nodeid_field: str | None = None
        for key in id_keys:
            v = get_first_int(props_norm, [key])
            if v is None:
                continue
            nodeid_val = int(v)
            nodeid_field = key
            break
        if nodeid_val is not None:
            total_with_id += 1
            if nodeid_field is not None:
                id_field_hits[nodeid_field] = int(id_field_hits.get(nodeid_field, 0)) + 1

        kind_val: int | None = None
        kind_field: str | None = None
        for key in kind_keys:
            v = get_first_int(props_norm, [key])
            if v is None:
                continue
            kind_val = int(v)
            kind_field = key
            break
        if kind_val is not None:
            total_with_kind += 1
            if kind_field is not None:
                kind_field_hits[kind_field] = int(kind_field_hits.get(kind_field, 0)) + 1
            kind_hist[int(kind_val)] += 1

        if nodeid_val is None:
            filtered_reasons["no_id"] += 1
            continue
        if kind_val is None:
            filtered_reasons["no_kind"] += 1
            continue
        if (int(kind_val) & mask) == 0:
            filtered_reasons["kind_not_allowed"] += 1
            continue
        selected_raw.append(int(nodeid_val))

    unique_sorted = sorted(set(selected_raw))
    duplicate_id_count = int(len(selected_raw) - len(unique_sorted))
    filtered_out_count = int(sum(int(v) for v in filtered_reasons.values()))

    report: dict[str, Any] = {
        "rcsdnode_path": str(rcsdnode_path),
        "kind_mask": int(mask),
        "kind_mask_hex": hex(int(mask)),
        "id_key_preference": list(id_keys),
        "kind_key_preference": list(kind_keys),
        "total_features": int(total_features),
        "total_with_id": int(total_with_id),
        "total_with_kind": int(total_with_kind),
        "selected_count": int(len(unique_sorted)),
        "selected_raw_count": int(len(selected_raw)),
        "duplicate_id_count": int(duplicate_id_count),
        "filtered_out_count": int(filtered_out_count),
        "filtered_out_reasons": {k: int(v) for k, v in filtered_reasons.items()},
        "id_field_hit_stats": {k: int(v) for k, v in id_field_hits.items()},
        "kind_field_hit_stats": {k: int(v) for k, v in kind_field_hits.items()},
        "kind_histogram": {str(int(k)): int(v) for k, v in sorted(kind_hist.items(), key=lambda kv: int(kv[0]))},
        "kind_histogram_topN": _kind_histogram_topn(kind_hist, limit=20),
        "focus_node_ids": [str(x) for x in unique_sorted],
        "focus_node_ids_int": [int(x) for x in unique_sorted],
    }
    return unique_sorted, report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="t04_node_discovery")
    p.add_argument("--rcsdnode_path", required=True)
    p.add_argument("--kind_mask", default="24")
    p.add_argument("--out_txt", required=True)
    p.add_argument("--out_json", required=True)
    p.add_argument("--id_keys", default=",".join(_DEFAULT_ID_KEYS))
    p.add_argument("--kind_keys", default=",".join(_DEFAULT_KIND_KEYS))
    p.add_argument("--kind_hist_topn", default="20")
    return p


def _split_csv_keys(raw: str) -> list[str]:
    parts = [str(x).strip() for x in str(raw).split(",")]
    return [x for x in parts if x]


def _write_txt(path: Path, node_ids: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(int(x)) for x in node_ids]
    text = ("\n".join(lines) + "\n") if lines else ""
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        rcsdnode_path = Path(args.rcsdnode_path)
        node_ids, report = discover_node_ids_from_rcsdnode(
            rcsdnode_path=rcsdnode_path,
            kind_mask=_parse_int_auto(str(args.kind_mask)),
            id_key_preference=_split_csv_keys(str(args.id_keys)),
            kind_key_preference=_split_csv_keys(str(args.kind_keys)),
        )

        kind_hist_topn = max(0, _parse_int_auto(str(args.kind_hist_topn)))
        kind_hist_counter = Counter({int(k): int(v) for k, v in report.get("kind_histogram", {}).items()})
        report["kind_histogram_topN"] = _kind_histogram_topn(kind_hist_counter, limit=kind_hist_topn)

        out_txt = Path(args.out_txt)
        out_json = Path(args.out_json)
        _write_txt(out_txt, node_ids)
        _write_json(out_json, report)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


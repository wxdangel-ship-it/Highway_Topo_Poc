#!/usr/bin/env python3
"""Patch schema v4 migration: rename Node/Road to RCSDNode/RCSDRoad."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

OLD_NODE = "Node.geojson"
NEW_NODE = "RCSDNode.geojson"
OLD_ROAD = "Road.geojson"
NEW_ROAD = "RCSDRoad.geojson"
LANE_BOUNDARY = "LaneBoundary.geojson"
TRAJ_RAW_POSE = "raw_dat_pose.geojson"


@dataclass
class DatasetInfo:
    root: Path
    dataset_dir: Path
    manifests: list[Path] = field(default_factory=list)
    patch_dirs: list[Path] = field(default_factory=list)
    source: str = "manifest"


@dataclass
class MigrationStats:
    dataset_count: int = 0
    patch_count: int = 0
    patches_to_modify: int = 0
    renamed_node: int = 0
    deleted_node_dup: int = 0
    created_rcsdnode: int = 0
    renamed_road: int = 0
    deleted_road_dup: int = 0
    created_rcsdroad: int = 0
    manifest_replaced: int = 0
    manifest_string_replaced: int = 0
    errors: list[str] = field(default_factory=list)
    dataset_dirs: list[str] = field(default_factory=list)
    modified_patch_dirs: list[str] = field(default_factory=list)
    modified_manifest_files: list[str] = field(default_factory=list)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir_default = f"outputs/_work/patch_schema_migration_v4_{ts}"
    parser = argparse.ArgumentParser(description="Migrate patch schema v4 (Node/Road -> RCSDNode/RCSDRoad).")
    parser.add_argument("--roots", nargs="+", default=["data/synth_local", "data/synth"])
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--backup-dir", default=None, help="Backup directory. Default: <report-dir>/backup")
    parser.add_argument("--report-dir", default=report_dir_default, help=f"Report directory. Default: {report_dir_default}")
    return parser.parse_args(argv)


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except Exception:
        return str(path)


def unique_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def load_json(path: Path, errors: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"json_parse_failed: {path}: {exc}")
        return None


def dump_json(path: Path, payload: Any, errors: list[str]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"json_write_failed: {path}: {exc}")
        return False


def backup_file(
    *,
    src: Path,
    backup_dir: Path,
    repo_root: Path,
    apply_mode: bool,
    backed_up: set[str],
    errors: list[str],
) -> None:
    if not apply_mode:
        return
    key = str(src.resolve())
    if key in backed_up:
        return
    try:
        rel = src.resolve().relative_to(repo_root)
    except Exception:
        rel = Path(src.name)
    dst = backup_dir / rel
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        backed_up.add(key)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"backup_failed: {src} -> {dst}: {exc}")


def extract_patch_ids(manifest_obj: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(manifest_obj, dict):
        return out
    patch_ids = manifest_obj.get("patch_ids")
    if isinstance(patch_ids, list):
        for item in patch_ids:
            if item is not None:
                out.append(str(item))
    patches = manifest_obj.get("patches")
    if isinstance(patches, list):
        for item in patches:
            if not isinstance(item, dict):
                continue
            pid = item.get("patch_id")
            if pid is None:
                pid = item.get("id")
            if pid is not None:
                out.append(str(pid))
    return unique_keep_order([x for x in out if x.strip()])


def resolve_patch_dirs_from_ids(dataset_dir: Path, patch_ids: list[str], errors: list[str]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for patch_id in patch_ids:
        candidates = [dataset_dir / patch_id, dataset_dir / "patches" / patch_id]
        chosen: Path | None = None
        for cand in candidates:
            if cand.is_dir():
                chosen = cand
                break
        if chosen is None:
            errors.append(f"patch_dir_missing: dataset={dataset_dir} patch_id={patch_id}")
            continue
        key = str(chosen.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(chosen)
    return sorted(out, key=lambda p: str(p))


def discover_patch_dirs_by_scan(base_dir: Path) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for vector_dir in sorted(base_dir.rglob("Vector")):
        if not vector_dir.is_dir():
            continue
        patch_dir = vector_dir.parent
        if not (patch_dir / "PointCloud").is_dir():
            continue
        if not (patch_dir / "Traj").is_dir():
            continue
        key = str(patch_dir.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(patch_dir)
    return sorted(out, key=lambda p: str(p))


def discover_datasets(roots: list[Path], errors: list[str]) -> list[DatasetInfo]:
    datasets: list[DatasetInfo] = []
    for root in roots:
        if not root.exists():
            errors.append(f"root_not_found: {root}")
            continue
        if not root.is_dir():
            errors.append(f"root_not_dir: {root}")
            continue
        manifests = sorted([p for p in root.rglob("patch_manifest*.json") if p.is_file()])
        if manifests:
            grouped: dict[Path, list[Path]] = {}
            for mf in manifests:
                grouped.setdefault(mf.parent, []).append(mf)
            for dataset_dir, mfs in sorted(grouped.items(), key=lambda kv: str(kv[0])):
                patch_ids: list[str] = []
                for mf in sorted(mfs, key=lambda p: str(p)):
                    obj = load_json(mf, errors)
                    if obj is None:
                        continue
                    patch_ids.extend(extract_patch_ids(obj))
                patch_dirs = resolve_patch_dirs_from_ids(dataset_dir, unique_keep_order(patch_ids), errors)
                if not patch_dirs:
                    patch_dirs = discover_patch_dirs_by_scan(dataset_dir)
                datasets.append(
                    DatasetInfo(
                        root=root,
                        dataset_dir=dataset_dir,
                        manifests=sorted(mfs, key=lambda p: str(p)),
                        patch_dirs=patch_dirs,
                        source="manifest",
                    )
                )
            continue

        patch_dirs = discover_patch_dirs_by_scan(root)
        if not patch_dirs:
            errors.append(f"no_manifest_or_patch_found: {root}")
            continue
        by_parent: dict[Path, list[Path]] = {}
        for patch_dir in patch_dirs:
            by_parent.setdefault(patch_dir.parent, []).append(patch_dir)
        for dataset_dir, dirs in sorted(by_parent.items(), key=lambda kv: str(kv[0])):
            datasets.append(
                DatasetInfo(
                    root=root,
                    dataset_dir=dataset_dir,
                    manifests=[],
                    patch_dirs=sorted(dirs, key=lambda p: str(p)),
                    source="scan",
                )
            )
    datasets.sort(key=lambda d: str(d.dataset_dir))
    return datasets


def detect_crs(patch_dir: Path, errors: list[str]) -> Any | None:
    traj_dir = patch_dir / "Traj"
    candidates: list[Path] = []
    direct_traj = traj_dir / TRAJ_RAW_POSE
    if direct_traj.is_file():
        candidates.append(direct_traj)
    if traj_dir.is_dir():
        candidates.extend(sorted(traj_dir.glob(f"*/{TRAJ_RAW_POSE}")))
    lane = patch_dir / "Vector" / LANE_BOUNDARY
    if lane.is_file():
        candidates.append(lane)

    for cand in candidates:
        obj = load_json(cand, errors)
        if isinstance(obj, dict) and "crs" in obj:
            return obj["crs"]
    return None


def empty_feature_collection(crs: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if crs is not None:
        out["crs"] = crs
    return out


def process_patch(
    *,
    patch_dir: Path,
    apply_mode: bool,
    stats: MigrationStats,
    repo_root: Path,
    backup_dir: Path,
    backed_up: set[str],
) -> None:
    vector_dir = patch_dir / "Vector"
    if not vector_dir.is_dir():
        stats.errors.append(f"vector_dir_missing: {patch_dir}")
        return
    stats.patch_count += 1

    old_node = vector_dir / OLD_NODE
    new_node = vector_dir / NEW_NODE
    old_road = vector_dir / OLD_ROAD
    new_road = vector_dir / NEW_ROAD

    node_rename = old_node.is_file() and (not new_node.is_file())
    node_delete_dup = old_node.is_file() and new_node.is_file()
    node_create = (not old_node.is_file()) and (not new_node.is_file())

    road_rename = old_road.is_file() and (not new_road.is_file())
    road_delete_dup = old_road.is_file() and new_road.is_file()
    road_create = (not old_road.is_file()) and (not new_road.is_file())

    changed = any([node_rename, node_delete_dup, node_create, road_rename, road_delete_dup, road_create])
    if not changed:
        return

    stats.patches_to_modify += 1
    stats.modified_patch_dirs.append(str(patch_dir))

    if node_rename:
        stats.renamed_node += 1
        if apply_mode:
            backup_file(src=old_node, backup_dir=backup_dir, repo_root=repo_root, apply_mode=apply_mode, backed_up=backed_up, errors=stats.errors)
            try:
                os.replace(old_node, new_node)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"node_rename_failed: {old_node} -> {new_node}: {exc}")

    if node_delete_dup:
        stats.deleted_node_dup += 1
        if apply_mode:
            backup_file(src=old_node, backup_dir=backup_dir, repo_root=repo_root, apply_mode=apply_mode, backed_up=backed_up, errors=stats.errors)
            try:
                old_node.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"node_delete_dup_failed: {old_node}: {exc}")

    if road_rename:
        stats.renamed_road += 1
        if apply_mode:
            backup_file(src=old_road, backup_dir=backup_dir, repo_root=repo_root, apply_mode=apply_mode, backed_up=backed_up, errors=stats.errors)
            try:
                os.replace(old_road, new_road)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"road_rename_failed: {old_road} -> {new_road}: {exc}")

    if road_delete_dup:
        stats.deleted_road_dup += 1
        if apply_mode:
            backup_file(src=old_road, backup_dir=backup_dir, repo_root=repo_root, apply_mode=apply_mode, backed_up=backed_up, errors=stats.errors)
            try:
                old_road.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"road_delete_dup_failed: {old_road}: {exc}")

    if node_create or road_create:
        crs = detect_crs(patch_dir, stats.errors)
    else:
        crs = None

    if node_create:
        stats.created_rcsdnode += 1
        if apply_mode:
            payload = empty_feature_collection(crs)
            dump_json(new_node, payload, stats.errors)

    if road_create:
        stats.created_rcsdroad += 1
        if apply_mode:
            payload = empty_feature_collection(crs)
            dump_json(new_road, payload, stats.errors)


def process_manifest(
    *,
    manifest_path: Path,
    apply_mode: bool,
    stats: MigrationStats,
    repo_root: Path,
    backup_dir: Path,
    backed_up: set[str],
) -> None:
    text = None
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(f"manifest_read_failed: {manifest_path}: {exc}")
        return
    old_text = text
    text = text.replace(OLD_NODE, NEW_NODE).replace(OLD_ROAD, NEW_ROAD)
    if text == old_text:
        return
    stats.manifest_replaced += 1
    stats.manifest_string_replaced += int(old_text.count(OLD_NODE) + old_text.count(OLD_ROAD))
    stats.modified_manifest_files.append(str(manifest_path))
    if not apply_mode:
        return
    backup_file(src=manifest_path, backup_dir=backup_dir, repo_root=repo_root, apply_mode=apply_mode, backed_up=backed_up, errors=stats.errors)
    try:
        manifest_path.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(f"manifest_write_failed: {manifest_path}: {exc}")


def write_reports(
    *,
    report_dir: Path,
    backup_dir: Path,
    roots: list[Path],
    repo_root: Path,
    apply_mode: bool,
    stats: MigrationStats,
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / "migration_report.json"
    report_txt = report_dir / "migration_report.txt"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "apply": bool(apply_mode),
        "roots": [repo_rel(r, repo_root) for r in roots],
        "report_dir": repo_rel(report_dir, repo_root),
        "backup_dir": repo_rel(backup_dir, repo_root),
        "dataset_count": stats.dataset_count,
        "patch_count": stats.patch_count,
        "patches_to_modify": stats.patches_to_modify,
        "renamed_node": stats.renamed_node,
        "deleted_node_dup": stats.deleted_node_dup,
        "created_rcsdnode": stats.created_rcsdnode,
        "renamed_road": stats.renamed_road,
        "deleted_road_dup": stats.deleted_road_dup,
        "created_rcsdroad": stats.created_rcsdroad,
        "manifest_replaced": stats.manifest_replaced,
        "manifest_string_replaced": stats.manifest_string_replaced,
        "errors": stats.errors,
        "dataset_dirs": stats.dataset_dirs,
        "modified_patch_dirs": stats.modified_patch_dirs,
        "modified_manifest_files": stats.modified_manifest_files,
    }
    dump_json(report_json, payload, stats.errors)

    lines = [
        "Patch Schema v4 Migration Report",
        f"generated_at: {payload['generated_at']}",
        f"apply: {str(apply_mode).lower()}",
        f"report_dir: {repo_rel(report_dir, repo_root)}",
        f"backup_dir: {repo_rel(backup_dir, repo_root)}",
        f"roots: {', '.join(payload['roots'])}",
        "",
        "Summary:",
        f"  dataset_count: {stats.dataset_count}",
        f"  patch_count: {stats.patch_count}",
        f"  patches_to_modify: {stats.patches_to_modify}",
        f"  renamed_node: {stats.renamed_node}",
        f"  deleted_node_dup: {stats.deleted_node_dup}",
        f"  created_rcsdnode: {stats.created_rcsdnode}",
        f"  renamed_road: {stats.renamed_road}",
        f"  deleted_road_dup: {stats.deleted_road_dup}",
        f"  created_rcsdroad: {stats.created_rcsdroad}",
        f"  manifest_replaced: {stats.manifest_replaced}",
        f"  errors_count: {len(stats.errors)}",
        "",
        "dataset_dirs:",
    ]
    if stats.dataset_dirs:
        lines.extend([f"  {x}" for x in stats.dataset_dirs])
    else:
        lines.append("  (none)")
    lines.extend(["", "errors:"])
    if stats.errors:
        lines.extend([f"  {x}" for x in stats.errors])
    else:
        lines.append("  (none)")
    report_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_json, report_txt


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd().resolve()

    roots: list[Path] = []
    for item in args.roots:
        p = Path(item)
        if not p.is_absolute():
            p = (repo_root / p).resolve()
        roots.append(p)

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = (repo_root / report_dir).resolve()

    backup_dir = Path(args.backup_dir) if args.backup_dir else (report_dir / "backup")
    if not backup_dir.is_absolute():
        backup_dir = (repo_root / backup_dir).resolve()

    stats = MigrationStats()
    datasets = discover_datasets(roots, stats.errors)
    stats.dataset_count = len(datasets)
    stats.dataset_dirs = unique_keep_order([repo_rel(d.dataset_dir, repo_root) for d in datasets])

    backed_up: set[str] = set()
    for ds in datasets:
        for patch_dir in ds.patch_dirs:
            process_patch(
                patch_dir=patch_dir,
                apply_mode=bool(args.apply),
                stats=stats,
                repo_root=repo_root,
                backup_dir=backup_dir,
                backed_up=backed_up,
            )
        for mf in ds.manifests:
            process_manifest(
                manifest_path=mf,
                apply_mode=bool(args.apply),
                stats=stats,
                repo_root=repo_root,
                backup_dir=backup_dir,
                backed_up=backed_up,
            )

    report_json, report_txt = write_reports(
        report_dir=report_dir,
        backup_dir=backup_dir,
        roots=roots,
        repo_root=repo_root,
        apply_mode=bool(args.apply),
        stats=stats,
    )

    print(f"datasets: {stats.dataset_count}")
    print(f"patch_count: {stats.patch_count}")
    print(f"patches_to_modify: {stats.patches_to_modify}")
    print(f"manifest_replaced: {stats.manifest_replaced}")
    print(f"errors: {len(stats.errors)}")
    print(f"report_json: {repo_rel(report_json, repo_root)}")
    print(f"report_txt: {repo_rel(report_txt, repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Migrate patch schema to v3 by adding Vector/RCSDRoad.geojson and Tiles/."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


ROAD_FILENAME = "RCSDRoad.geojson"
LEGACY_ROAD_FILENAME = "Road.geojson"
TILES_DIRNAME = "Tiles"
TRAJ_FILENAME = "raw_dat_pose.geojson"


@dataclass
class PatchRecord:
    root: Path
    dataset_dir: Path
    patch_id: str
    patch_dir: Path
    sibling_candidates: list[Path]
    source: str


@dataclass
class MigrationStats:
    dataset_count: int = 0
    patch_count: int = 0
    patches_to_modify: int = 0
    created_road: int = 0
    renamed_legacy_road: int = 0
    deleted_legacy_road_dup: int = 0
    created_tiles_dir: int = 0
    copied_tiles: int = 0
    copied_tiles_files: int = 0
    errors: list[str] = field(default_factory=list)
    dataset_dirs: list[str] = field(default_factory=list)
    modified_patch_dirs: list[str] = field(default_factory=list)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_report_dir = f"outputs/_work/patch_schema_migration_v3_{ts}"
    default_backup_dir = f"{default_report_dir}/backup"

    parser = argparse.ArgumentParser(description="Migrate patch schema v3 (RCSDRoad.geojson + Tiles/).")
    parser.add_argument("--roots", nargs="+", default=["data/synth_local", "data/synth"])
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--backup-dir", default=default_backup_dir)
    parser.add_argument("--report-dir", default=default_report_dir)
    parser.add_argument(
        "--tiles-mode",
        choices=["mkdir_empty", "copy_if_exists"],
        default="mkdir_empty",
        help="How to create Tiles/: mkdir only, or copy from sibling candidate when available.",
    )
    return parser.parse_args(argv)


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except Exception:
        return str(path)


def unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
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


def extract_patch_ids(manifest_obj: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(manifest_obj, dict):
        return ids

    for key in ["patch_ids", "patch_id_list", "patch_list"]:
        value = manifest_obj.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    pid = item.get("patch_id") or item.get("id") or item.get("name")
                    if pid is not None:
                        ids.append(str(pid))
                elif item is not None:
                    ids.append(str(item))

    patches = manifest_obj.get("patches")
    if isinstance(patches, list):
        for item in patches:
            if not isinstance(item, dict):
                continue
            pid = item.get("patch_id") or item.get("id") or item.get("name")
            if pid is not None:
                ids.append(str(pid))

    return unique_keep_order([x for x in ids if x.strip()])


def discover_patch_dirs_by_scan(base_dir: Path) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for vector_dir in sorted(base_dir.rglob("Vector")):
        if not vector_dir.is_dir():
            continue
        patch_dir = vector_dir.parent
        if not (patch_dir / "PointCloud").is_dir():
            continue
        if not (patch_dir / "Traj").is_dir():
            continue
        resolved = patch_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(patch_dir)
    return out


def normalize_dataset_dir_from_patch(patch_dir: Path) -> Path:
    if patch_dir.parent.name == "patches":
        return patch_dir.parent.parent
    return patch_dir.parent


def build_sibling_candidates(dataset_dir: Path, patch_id: str) -> list[Path]:
    cands = [dataset_dir / patch_id, dataset_dir / "patches" / patch_id]
    out: list[Path] = []
    seen: set[str] = set()
    for cand in cands:
        if not cand.is_dir():
            continue
        key = str(cand.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def discover_records_for_root(root: Path, errors: list[str]) -> list[PatchRecord]:
    records: list[PatchRecord] = []
    manifest_files = sorted([p for p in root.rglob("patch_manifest*.json") if p.is_file()])

    if manifest_files:
        by_dataset: dict[Path, list[Path]] = {}
        for manifest in manifest_files:
            by_dataset.setdefault(manifest.parent, []).append(manifest)

        for dataset_dir, manifests in sorted(by_dataset.items(), key=lambda kv: str(kv[0])):
            patch_ids: list[str] = []
            for manifest in sorted(manifests, key=lambda p: str(p)):
                obj = load_json(manifest, errors)
                if obj is None:
                    continue
                patch_ids.extend(extract_patch_ids(obj))

            patch_ids = unique_keep_order(patch_ids)
            if patch_ids:
                for patch_id in patch_ids:
                    siblings = build_sibling_candidates(dataset_dir, patch_id)
                    if not siblings:
                        errors.append(f"patch_dir_missing: dataset={dataset_dir} patch_id={patch_id}")
                        continue
                    records.append(
                        PatchRecord(
                            root=root,
                            dataset_dir=dataset_dir,
                            patch_id=patch_id,
                            patch_dir=siblings[0],
                            sibling_candidates=siblings,
                            source="manifest",
                        )
                    )
                continue

            scanned = discover_patch_dirs_by_scan(dataset_dir)
            for patch_dir in scanned:
                pid = patch_dir.name
                siblings = build_sibling_candidates(dataset_dir, pid) or [patch_dir]
                records.append(
                    PatchRecord(
                        root=root,
                        dataset_dir=dataset_dir,
                        patch_id=pid,
                        patch_dir=patch_dir,
                        sibling_candidates=siblings,
                        source="scan_fallback",
                    )
                )
        return records

    scanned = discover_patch_dirs_by_scan(root)
    for patch_dir in scanned:
        dataset_dir = normalize_dataset_dir_from_patch(patch_dir)
        patch_id = patch_dir.name
        siblings = build_sibling_candidates(dataset_dir, patch_id) or [patch_dir]
        records.append(
            PatchRecord(
                root=root,
                dataset_dir=dataset_dir,
                patch_id=patch_id,
                patch_dir=patch_dir,
                sibling_candidates=siblings,
                source="scan",
            )
        )
    return records


def discover_patch_records(roots: Sequence[Path], errors: list[str]) -> list[PatchRecord]:
    out: list[PatchRecord] = []
    seen: set[str] = set()

    for root in roots:
        if not root.exists():
            errors.append(f"root_not_found: {root}")
            continue
        if not root.is_dir():
            errors.append(f"root_not_dir: {root}")
            continue

        for rec in discover_records_for_root(root, errors):
            key = str(rec.patch_dir.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)

    out.sort(key=lambda r: str(r.patch_dir))
    return out


def detect_crs_for_road(patch_dir: Path, errors: list[str]) -> Any | None:
    candidates: list[Path] = []

    traj_root = patch_dir / "Traj"
    direct = traj_root / TRAJ_FILENAME
    if direct.is_file():
        candidates.append(direct)
    if traj_root.is_dir():
        candidates.extend(sorted(traj_root.glob(f"*/{TRAJ_FILENAME}")))

    lane_boundary = patch_dir / "Vector" / "LaneBoundary.geojson"
    if lane_boundary.is_file():
        candidates.append(lane_boundary)

    for candidate in candidates:
        obj = load_json(candidate, errors)
        if isinstance(obj, dict) and "crs" in obj:
            return obj["crs"]
    return None


def empty_feature_collection(crs: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if crs is not None:
        out["crs"] = crs
    return out


def copy_tree_contents(src_dir: Path, dst_dir: Path) -> int:
    copied_files = 0
    for item in sorted(src_dir.rglob("*")):
        rel = item.relative_to(src_dir)
        dst = dst_dir / rel
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)
        copied_files += 1
    return copied_files


def find_tiles_source(record: PatchRecord) -> Path | None:
    target_resolved = record.patch_dir.resolve()
    for candidate_patch_dir in record.sibling_candidates:
        try:
            cand_resolved = candidate_patch_dir.resolve()
        except Exception:
            cand_resolved = candidate_patch_dir
        if cand_resolved == target_resolved:
            continue
        tiles_dir = candidate_patch_dir / TILES_DIRNAME
        if tiles_dir.is_dir():
            return tiles_dir
    return None


def process_patch(
    *,
    record: PatchRecord,
    apply_mode: bool,
    tiles_mode: str,
    stats: MigrationStats,
    repo_root: Path,
    rollback_ops: list[dict[str, Any]],
) -> None:
    patch_dir = record.patch_dir
    vector_dir = patch_dir / "Vector"
    if not vector_dir.is_dir():
        stats.errors.append(f"vector_dir_missing: {patch_dir}")
        return

    road_path = vector_dir / ROAD_FILENAME
    legacy_road_path = vector_dir / LEGACY_ROAD_FILENAME
    tiles_dir = patch_dir / TILES_DIRNAME

    needs_rename_legacy_road = legacy_road_path.is_file() and not road_path.is_file()
    needs_delete_legacy_road_dup = legacy_road_path.is_file() and road_path.is_file()
    needs_road = not road_path.is_file() and not needs_rename_legacy_road
    needs_tiles = not tiles_dir.is_dir()
    tiles_source = find_tiles_source(record) if (needs_tiles and tiles_mode == "copy_if_exists") else None
    will_copy_tiles = tiles_source is not None

    if not (needs_rename_legacy_road or needs_delete_legacy_road_dup or needs_road or needs_tiles):
        return

    stats.patches_to_modify += 1
    stats.modified_patch_dirs.append(repo_rel(patch_dir, repo_root))

    if needs_rename_legacy_road:
        stats.renamed_legacy_road += 1
    if needs_delete_legacy_road_dup:
        stats.deleted_legacy_road_dup += 1
    if needs_road:
        stats.created_road += 1
    if needs_tiles:
        stats.created_tiles_dir += 1
        if will_copy_tiles:
            stats.copied_tiles += 1

    if not apply_mode:
        return

    if needs_rename_legacy_road:
        try:
            legacy_road_path.replace(road_path)
            rollback_ops.append(
                {
                    "op": "rename_file",
                    "from": repo_rel(road_path, repo_root),
                    "to": repo_rel(legacy_road_path, repo_root),
                    "reason": "renamed_legacy_road_to_rcsdroad",
                }
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"road_rename_failed: {legacy_road_path} -> {road_path}: {exc}")

    if needs_delete_legacy_road_dup:
        try:
            legacy_road_path.unlink(missing_ok=True)
            rollback_ops.append(
                {
                    "op": "restore_file_from_backup",
                    "path": repo_rel(legacy_road_path, repo_root),
                    "reason": "deleted_duplicate_legacy_road",
                }
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"legacy_road_delete_failed: {legacy_road_path}: {exc}")

    if needs_road:
        crs = detect_crs_for_road(patch_dir, stats.errors)
        payload = empty_feature_collection(crs)
        ok = dump_json(road_path, payload, stats.errors)
        if ok:
            rollback_ops.append(
                {
                    "op": "remove_file",
                    "path": repo_rel(road_path, repo_root),
                    "reason": "created_by_v3_migration",
                }
            )

    if needs_tiles:
        try:
            tiles_dir.mkdir(parents=True, exist_ok=True)
            copied_files = 0
            copied_from = None
            if will_copy_tiles and tiles_source is not None:
                copied_files = copy_tree_contents(tiles_source, tiles_dir)
                copied_from = repo_rel(tiles_source, repo_root)
                stats.copied_tiles_files += int(copied_files)

            rollback_ops.append(
                {
                    "op": "remove_dir",
                    "path": repo_rel(tiles_dir, repo_root),
                    "reason": "created_by_v3_migration",
                    "copied_from": copied_from,
                    "copied_files": int(copied_files),
                }
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"tiles_create_failed: {tiles_dir}: {exc}")


def write_rollback_manifest(
    *,
    backup_dir: Path,
    repo_root: Path,
    apply_mode: bool,
    rollback_ops: list[dict[str, Any]],
    errors: list[str],
) -> Path | None:
    if not apply_mode:
        return None
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / "rollback_manifest.json"
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "repo_root": str(repo_root),
            "operations": rollback_ops,
            "note": "Rollback can remove created RCSDRoad.geojson and Tiles/ entries in reverse order.",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rollback_manifest_write_failed: {backup_dir}: {exc}")
        return None


def write_reports(
    *,
    report_dir: Path,
    backup_dir: Path,
    roots: Sequence[Path],
    repo_root: Path,
    apply_mode: bool,
    tiles_mode: str,
    stats: MigrationStats,
    rollback_manifest: Path | None,
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / "migration_report.json"
    report_txt = report_dir / "migration_report.txt"

    report_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "apply": bool(apply_mode),
        "tiles_mode": str(tiles_mode),
        "roots": [repo_rel(r, repo_root) for r in roots],
        "report_dir": repo_rel(report_dir, repo_root),
        "backup_dir": repo_rel(backup_dir, repo_root),
        "rollback_manifest": repo_rel(rollback_manifest, repo_root) if rollback_manifest is not None else None,
        "dataset_count": stats.dataset_count,
        "patch_count": stats.patch_count,
        "patches_to_modify": stats.patches_to_modify,
        "created_road": stats.created_road,
        "renamed_legacy_road": stats.renamed_legacy_road,
        "deleted_legacy_road_dup": stats.deleted_legacy_road_dup,
        "created_tiles_dir": stats.created_tiles_dir,
        "copied_tiles": stats.copied_tiles,
        "copied_tiles_files": stats.copied_tiles_files,
        "errors": stats.errors,
        "dataset_dirs": stats.dataset_dirs,
        "modified_patch_dirs": stats.modified_patch_dirs,
    }
    dump_json(report_json, report_payload, stats.errors)

    lines: list[str] = [
        "Patch Schema v3 Migration Report",
        f"generated_at: {report_payload['generated_at']}",
        f"apply: {str(apply_mode).lower()}",
        f"tiles_mode: {tiles_mode}",
        f"report_dir: {repo_rel(report_dir, repo_root)}",
        f"backup_dir: {repo_rel(backup_dir, repo_root)}",
        f"rollback_manifest: {repo_rel(rollback_manifest, repo_root) if rollback_manifest else 'none'}",
        f"roots: {', '.join(report_payload['roots'])}",
        "",
        "Summary:",
        f"  dataset_count: {stats.dataset_count}",
        f"  patch_count: {stats.patch_count}",
        f"  patches_to_modify: {stats.patches_to_modify}",
        f"  created_road: {stats.created_road}",
        f"  renamed_legacy_road: {stats.renamed_legacy_road}",
        f"  deleted_legacy_road_dup: {stats.deleted_legacy_road_dup}",
        f"  created_tiles_dir: {stats.created_tiles_dir}",
        f"  copied_tiles: {stats.copied_tiles}",
        f"  copied_tiles_files: {stats.copied_tiles_files}",
        f"  errors_count: {len(stats.errors)}",
        "",
        "dataset_dirs:",
    ]
    if stats.dataset_dirs:
        lines.extend([f"  {item}" for item in stats.dataset_dirs])
    else:
        lines.append("  (none)")

    lines.extend(["", "errors:"])
    if stats.errors:
        lines.extend([f"  {err}" for err in stats.errors])
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

    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_absolute():
        backup_dir = (repo_root / backup_dir).resolve()

    stats = MigrationStats()
    records = discover_patch_records(roots, stats.errors)
    stats.patch_count = len(records)
    stats.dataset_dirs = unique_keep_order([repo_rel(r.dataset_dir, repo_root) for r in records])
    stats.dataset_count = len(stats.dataset_dirs)

    print(f"Discovered datasets: {stats.dataset_count}")
    print(f"Discovered patches: {stats.patch_count}")

    rollback_ops: list[dict[str, Any]] = []
    for rec in records:
        process_patch(
            record=rec,
            apply_mode=bool(args.apply),
            tiles_mode=str(args.tiles_mode),
            stats=stats,
            repo_root=repo_root,
            rollback_ops=rollback_ops,
        )

    rollback_manifest = write_rollback_manifest(
        backup_dir=backup_dir,
        repo_root=repo_root,
        apply_mode=bool(args.apply),
        rollback_ops=rollback_ops,
        errors=stats.errors,
    )

    report_json, report_txt = write_reports(
        report_dir=report_dir,
        backup_dir=backup_dir,
        roots=roots,
        repo_root=repo_root,
        apply_mode=bool(args.apply),
        tiles_mode=str(args.tiles_mode),
        stats=stats,
        rollback_manifest=rollback_manifest,
    )

    print(
        "Summary: "
        f"patches_to_modify={stats.patches_to_modify} "
        f"created_road={stats.created_road} "
        f"created_tiles_dir={stats.created_tiles_dir} "
        f"copied_tiles={stats.copied_tiles} "
        f"errors={len(stats.errors)}"
    )
    print(f"Report JSON: {repo_rel(report_json, repo_root)}")
    print(f"Report TXT : {repo_rel(report_txt, repo_root)}")

    if stats.patch_count == 0:
        return 2
    if stats.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Migrate patch Vector schema to v2.

Changes:
- Remove `gorearea.geojson`.
- Ensure `DivStripZone.geojson`, `Node.geojson`, `intersection_l.geojson` exist.
- Replace JSON string values containing `gorearea.geojson` with `DivStripZone.geojson`
  in `patch_manifest*.json` files.

The script is idempotent: re-running with `--apply` should produce no further data
changes after the first successful migration.

Node standard fields note:
- Kind (int32): bit0 none, bit2 cross, bit3 merge, bit4 diverge
- mainid (int64)
- id (int64)

intersection_l standard fields note:
- nodeid (int64)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

TOKEN_OLD = "gorearea.geojson"
TOKEN_NEW = "DivStripZone.geojson"


@dataclass
class DatasetInfo:
    root: Path
    dataset_dir: Path
    manifests: List[Path] = field(default_factory=list)
    patch_dirs: List[Path] = field(default_factory=list)
    source: str = "manifest"


@dataclass
class MigrationStats:
    datasets_count: int = 0
    patches_count: int = 0
    patches_to_modify: int = 0

    rename_count: int = 0
    create_count: int = 0
    delete_count: int = 0

    created_divstripzone: int = 0
    created_node: int = 0
    created_intersection_l: int = 0

    manifest_replace_count: int = 0
    manifest_string_replace_count: int = 0

    gorearea_seen_count: int = 0

    verify_gorearea_count: int = 0
    verify_missing_divstripzone_count: int = 0
    verify_missing_node_count: int = 0
    verify_missing_intersection_l_count: int = 0

    manifests_scanned_count: int = 0

    errors: List[str] = field(default_factory=list)
    dataset_dirs: List[str] = field(default_factory=list)
    modified_patch_dirs: List[str] = field(default_factory=list)
    modified_manifest_files: List[str] = field(default_factory=list)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_report_dir = f"outputs/_work/patch_schema_migration_v2_{ts}"

    parser = argparse.ArgumentParser(
        description="Migrate patch Vector schema v2 (gorearea -> DivStripZone)."
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["data/synth_local", "data/synth"],
        help="Dataset roots to scan.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Default is dry-run (no data writes).",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Backup directory. Default: <report-dir>/backup",
    )
    parser.add_argument(
        "--report-dir",
        default=default_report_dir,
        help=f"Report directory. Default: {default_report_dir}",
    )
    return parser.parse_args(argv)


def as_repo_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def unique_keep_order(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def load_json(path: Path, errors: List[str]) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to parse JSON: {path}: {exc}")
        return None


def dump_json(path: Path, data: Any, errors: List[str]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to write JSON: {path}: {exc}")
        return False


def extract_patch_ids(manifest_obj: Any) -> List[str]:
    patch_ids: List[str] = []
    if not isinstance(manifest_obj, dict):
        return patch_ids

    direct_ids = manifest_obj.get("patch_ids")
    if isinstance(direct_ids, list):
        for item in direct_ids:
            if item is None:
                continue
            patch_ids.append(str(item))

    patches = manifest_obj.get("patches")
    if isinstance(patches, list):
        for patch_item in patches:
            if not isinstance(patch_item, dict):
                continue
            if "patch_id" in patch_item and patch_item["patch_id"] is not None:
                patch_ids.append(str(patch_item["patch_id"]))
            elif "id" in patch_item and patch_item["id"] is not None:
                patch_ids.append(str(patch_item["id"]))

    return unique_keep_order(patch_ids)


def discover_patch_dirs_by_scan(base_dir: Path) -> List[Path]:
    found: List[Path] = []
    seen: Set[Path] = set()

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
        found.append(patch_dir)

    return found


def resolve_patch_dirs_from_ids(
    dataset_dir: Path,
    patch_ids: Sequence[str],
    errors: List[str],
) -> List[Path]:
    found: List[Path] = []
    seen: Set[Path] = set()

    for patch_id in unique_keep_order(str(x) for x in patch_ids if str(x).strip()):
        candidates = [
            dataset_dir / patch_id,
            dataset_dir / "patches" / patch_id,
        ]

        selected: Optional[Path] = None
        for candidate in candidates:
            if candidate.is_dir():
                selected = candidate
                break

        if selected is None:
            errors.append(
                f"Patch dir not found for patch_id={patch_id} under dataset {dataset_dir}"
            )
            continue

        resolved = selected.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(selected)

    return found


def discover_datasets(roots: Sequence[Path], errors: List[str]) -> List[DatasetInfo]:
    datasets: List[DatasetInfo] = []

    for root in roots:
        if not root.exists():
            errors.append(f"Root does not exist: {root}")
            continue

        manifest_files = sorted(
            p for p in root.rglob("patch_manifest*.json") if p.is_file()
        )

        if manifest_files:
            by_dataset: Dict[Path, List[Path]] = {}
            for manifest in manifest_files:
                by_dataset.setdefault(manifest.parent, []).append(manifest)

            for dataset_dir in sorted(by_dataset.keys()):
                manifests = sorted(by_dataset[dataset_dir])
                patch_ids: List[str] = []
                for manifest in manifests:
                    obj = load_json(manifest, errors)
                    if obj is None:
                        continue
                    patch_ids.extend(extract_patch_ids(obj))

                patch_dirs = resolve_patch_dirs_from_ids(dataset_dir, patch_ids, errors)
                if not patch_dirs:
                    patch_dirs = discover_patch_dirs_by_scan(dataset_dir)

                datasets.append(
                    DatasetInfo(
                        root=root,
                        dataset_dir=dataset_dir,
                        manifests=manifests,
                        patch_dirs=patch_dirs,
                        source="manifest",
                    )
                )
            continue

        fallback_patch_dirs = discover_patch_dirs_by_scan(root)
        if not fallback_patch_dirs:
            errors.append(f"No manifest or patch dirs found under root: {root}")
            continue

        by_parent: Dict[Path, List[Path]] = {}
        for patch_dir in fallback_patch_dirs:
            by_parent.setdefault(patch_dir.parent, []).append(patch_dir)

        for dataset_dir in sorted(by_parent.keys()):
            dirs = sorted(by_parent[dataset_dir], key=lambda p: str(p))
            datasets.append(
                DatasetInfo(
                    root=root,
                    dataset_dir=dataset_dir,
                    manifests=[],
                    patch_dirs=dirs,
                    source="scan",
                )
            )

    datasets.sort(key=lambda d: str(d.dataset_dir))
    return datasets


def backup_file(
    src: Path,
    backup_dir: Path,
    repo_root: Path,
    backed_up: Set[Path],
    apply_mode: bool,
    errors: List[str],
) -> None:
    src_resolved = src.resolve()
    if src_resolved in backed_up:
        return
    if not apply_mode:
        return

    try:
        rel = src.relative_to(repo_root)
    except ValueError:
        rel = Path(src.name)

    dst = backup_dir / rel
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        backed_up.add(src_resolved)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to backup {src} -> {dst}: {exc}")


def detect_crs(patch_dir: Path, errors: List[str]) -> Optional[Any]:
    candidates: List[Path] = []
    lane_boundary = patch_dir / "Vector" / "LaneBoundary.geojson"
    if lane_boundary.is_file():
        candidates.append(lane_boundary)

    traj_dir = patch_dir / "Traj"
    if traj_dir.is_dir():
        candidates.extend(sorted(traj_dir.glob("*/raw_dat_pose.geojson")))
        direct = traj_dir / "raw_dat_pose.geojson"
        if direct.is_file():
            candidates.append(direct)

    for candidate in candidates:
        obj = load_json(candidate, errors)
        if isinstance(obj, dict) and "crs" in obj:
            return obj["crs"]

    return None


def make_empty_feature_collection(crs: Optional[Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [],
    }
    if crs is not None:
        data["crs"] = crs
    return data


def replace_string_values(value: Any) -> Tuple[Any, int]:
    if isinstance(value, str):
        count = value.count(TOKEN_OLD)
        if count == 0:
            return value, 0
        return value.replace(TOKEN_OLD, TOKEN_NEW), count

    if isinstance(value, list):
        out_list: List[Any] = []
        total = 0
        for item in value:
            new_item, c = replace_string_values(item)
            out_list.append(new_item)
            total += c
        return out_list, total

    if isinstance(value, dict):
        out_dict: Dict[str, Any] = {}
        total = 0
        for k, v in value.items():
            new_v, c = replace_string_values(v)
            out_dict[k] = new_v
            total += c
        return out_dict, total

    return value, 0


def process_manifest_file(
    manifest_path: Path,
    stats: MigrationStats,
    repo_root: Path,
    backup_dir: Path,
    backed_up: Set[Path],
    apply_mode: bool,
) -> None:
    obj = load_json(manifest_path, stats.errors)
    if obj is None:
        return

    stats.manifests_scanned_count += 1
    new_obj, replacements = replace_string_values(obj)
    if replacements <= 0:
        return

    stats.manifest_replace_count += 1
    stats.manifest_string_replace_count += replacements
    stats.modified_manifest_files.append(str(manifest_path))

    if not apply_mode:
        return

    backup_file(
        src=manifest_path,
        backup_dir=backup_dir,
        repo_root=repo_root,
        backed_up=backed_up,
        apply_mode=apply_mode,
        errors=stats.errors,
    )
    dump_json(manifest_path, new_obj, stats.errors)


def process_patch_dir(
    patch_dir: Path,
    stats: MigrationStats,
    repo_root: Path,
    backup_dir: Path,
    backed_up: Set[Path],
    apply_mode: bool,
) -> None:
    stats.patches_count += 1

    vector_dir = patch_dir / "Vector"
    if not vector_dir.is_dir():
        stats.errors.append(f"Missing Vector dir: {patch_dir}")
        return

    gore = vector_dir / "gorearea.geojson"
    div = vector_dir / "DivStripZone.geojson"
    node = vector_dir / "Node.geojson"
    inter = vector_dir / "intersection_l.geojson"

    gore_exists = gore.is_file()
    div_exists = div.is_file()
    node_exists = node.is_file()
    inter_exists = inter.is_file()

    needs_rename = gore_exists and not div_exists
    needs_delete = gore_exists and div_exists

    # If rename is planned, DivStripZone will exist afterwards.
    needs_create_div = (not div_exists) and (not needs_rename)
    needs_create_node = not node_exists
    needs_create_inter = not inter_exists

    changed = any(
        [
            needs_rename,
            needs_delete,
            needs_create_div,
            needs_create_node,
            needs_create_inter,
        ]
    )

    if not changed:
        return

    stats.patches_to_modify += 1
    stats.modified_patch_dirs.append(str(patch_dir))

    if gore_exists:
        stats.gorearea_seen_count += 1

    if needs_rename:
        stats.rename_count += 1
        if apply_mode:
            backup_file(
                src=gore,
                backup_dir=backup_dir,
                repo_root=repo_root,
                backed_up=backed_up,
                apply_mode=apply_mode,
                errors=stats.errors,
            )
            try:
                os.replace(gore, div)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"Failed to rename {gore} -> {div}: {exc}")

    if needs_delete:
        stats.delete_count += 1
        if apply_mode:
            backup_file(
                src=gore,
                backup_dir=backup_dir,
                repo_root=repo_root,
                backed_up=backed_up,
                apply_mode=apply_mode,
                errors=stats.errors,
            )
            try:
                gore.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"Failed to delete {gore}: {exc}")

    crs: Optional[Any] = None
    if needs_create_div or needs_create_node or needs_create_inter:
        crs = detect_crs(patch_dir, stats.errors)

    if needs_create_div:
        stats.create_count += 1
        stats.created_divstripzone += 1
        if apply_mode:
            payload = make_empty_feature_collection(crs)
            dump_json(div, payload, stats.errors)

    if needs_create_node:
        stats.create_count += 1
        stats.created_node += 1
        if apply_mode:
            payload = make_empty_feature_collection(crs)
            dump_json(node, payload, stats.errors)

    if needs_create_inter:
        stats.create_count += 1
        stats.created_intersection_l += 1
        if apply_mode:
            payload = make_empty_feature_collection(crs)
            dump_json(inter, payload, stats.errors)

    # Step 5: final guarantee (best effort): gorearea should not exist after apply.
    if apply_mode and gore.is_file():
        try:
            gore.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"Failed to remove leftover {gore}: {exc}")


def collect_integrity_counts(patch_dirs: Sequence[Path], stats: MigrationStats) -> None:
    gore_count = 0
    miss_div = 0
    miss_node = 0
    miss_inter = 0

    for patch_dir in patch_dirs:
        vector_dir = patch_dir / "Vector"
        if not vector_dir.is_dir():
            continue

        if (vector_dir / "gorearea.geojson").is_file():
            gore_count += 1
        if not (vector_dir / "DivStripZone.geojson").is_file():
            miss_div += 1
        if not (vector_dir / "Node.geojson").is_file():
            miss_node += 1
        if not (vector_dir / "intersection_l.geojson").is_file():
            miss_inter += 1

    stats.verify_gorearea_count = gore_count
    stats.verify_missing_divstripzone_count = miss_div
    stats.verify_missing_node_count = miss_node
    stats.verify_missing_intersection_l_count = miss_inter


def write_reports(
    report_dir: Path,
    backup_dir: Path,
    repo_root: Path,
    roots: Sequence[Path],
    apply_mode: bool,
    stats: MigrationStats,
) -> Tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)

    report_json_path = report_dir / "migration_report.json"
    report_txt_path = report_dir / "migration_report.txt"

    report_obj = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "apply": apply_mode,
        "roots": [as_repo_path(r, repo_root) for r in roots],
        "report_dir": as_repo_path(report_dir, repo_root),
        "backup_dir": as_repo_path(backup_dir, repo_root),
        "datasets_count": stats.datasets_count,
        "patches_count": stats.patches_count,
        "patches_to_modify": stats.patches_to_modify,
        "rename_count": stats.rename_count,
        "create_count": stats.create_count,
        "delete_count": stats.delete_count,
        "manifest_replace_count": stats.manifest_replace_count,
        "manifest_string_replace_count": stats.manifest_string_replace_count,
        "renamed_gore_to_div": stats.rename_count,
        "created_divstripzone": stats.created_divstripzone,
        "created_node": stats.created_node,
        "created_intersection_l": stats.created_intersection_l,
        "manifest_replaced": stats.manifest_replace_count,
        "verify_gorearea_count": stats.verify_gorearea_count,
        "verify_missing_divstripzone_count": stats.verify_missing_divstripzone_count,
        "verify_missing_node_count": stats.verify_missing_node_count,
        "verify_missing_intersection_l_count": stats.verify_missing_intersection_l_count,
        "manifests_scanned_count": stats.manifests_scanned_count,
        "dataset_dirs": stats.dataset_dirs,
        "modified_patch_dirs": stats.modified_patch_dirs,
        "modified_manifest_files": stats.modified_manifest_files,
        "errors": stats.errors,
    }

    dump_json(report_json_path, report_obj, stats.errors)

    lines: List[str] = [
        "Patch Vector Schema v2 Migration Report",
        f"generated_at: {report_obj['generated_at']}",
        f"apply: {apply_mode}",
        f"report_dir: {as_repo_path(report_dir, repo_root)}",
        f"backup_dir: {as_repo_path(backup_dir, repo_root)}",
        f"roots: {', '.join(report_obj['roots'])}",
        "",
        "Summary:",
        f"  datasets_count: {stats.datasets_count}",
        f"  patches_count: {stats.patches_count}",
        f"  patches_to_modify: {stats.patches_to_modify}",
        f"  rename_count: {stats.rename_count}",
        f"  create_count: {stats.create_count}",
        f"  delete_count: {stats.delete_count}",
        f"  manifest_replace_count: {stats.manifest_replace_count}",
        f"  manifest_string_replace_count: {stats.manifest_string_replace_count}",
        "",
        "Detailed create counts:",
        f"  created_divstripzone: {stats.created_divstripzone}",
        f"  created_node: {stats.created_node}",
        f"  created_intersection_l: {stats.created_intersection_l}",
        "",
        "Verify counts (current filesystem state):",
        f"  gorearea_remaining: {stats.verify_gorearea_count}",
        f"  missing_divstripzone: {stats.verify_missing_divstripzone_count}",
        f"  missing_node: {stats.verify_missing_node_count}",
        f"  missing_intersection_l: {stats.verify_missing_intersection_l_count}",
        "",
        f"manifests_scanned_count: {stats.manifests_scanned_count}",
        f"errors_count: {len(stats.errors)}",
        "",
        "dataset_dirs:",
    ]

    if stats.dataset_dirs:
        lines.extend(f"  {item}" for item in stats.dataset_dirs)
    else:
        lines.append("  (none)")

    lines.extend(["", "errors:"])
    if stats.errors:
        lines.extend(f"  {err}" for err in stats.errors)
    else:
        lines.append("  (none)")

    report_txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return report_json_path, report_txt_path


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    repo_root = Path.cwd().resolve()
    roots: List[Path] = []
    for root_arg in args.roots:
        root_path = Path(root_arg)
        if not root_path.is_absolute():
            root_path = repo_root / root_path
        roots.append(root_path.resolve())

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = (repo_root / report_dir).resolve()

    backup_dir = Path(args.backup_dir) if args.backup_dir else (report_dir / "backup")
    if not backup_dir.is_absolute():
        backup_dir = (repo_root / backup_dir).resolve()

    stats = MigrationStats()
    datasets = discover_datasets(roots, stats.errors)
    stats.datasets_count = len(datasets)
    stats.dataset_dirs = [as_repo_path(d.dataset_dir, repo_root) for d in datasets]

    print(f"Discovered dataset_dir count: {stats.datasets_count}")
    max_show = 20
    for dataset_dir in stats.dataset_dirs[:max_show]:
        print(f"  - {dataset_dir}")
    if len(stats.dataset_dirs) > max_show:
        print(f"  - ... ({len(stats.dataset_dirs) - max_show} more)")

    all_patch_dirs: List[Path] = []
    seen_patch_dirs: Set[Path] = set()
    for dataset in datasets:
        for patch_dir in dataset.patch_dirs:
            resolved = patch_dir.resolve()
            if resolved in seen_patch_dirs:
                continue
            seen_patch_dirs.add(resolved)
            all_patch_dirs.append(patch_dir)

    if not all_patch_dirs:
        stats.errors.append("No patch directories discovered.")

    backed_up: Set[Path] = set()

    for patch_dir in sorted(all_patch_dirs, key=lambda p: str(p)):
        process_patch_dir(
            patch_dir=patch_dir,
            stats=stats,
            repo_root=repo_root,
            backup_dir=backup_dir,
            backed_up=backed_up,
            apply_mode=args.apply,
        )

    for dataset in datasets:
        for manifest_path in sorted(dataset.manifests, key=lambda p: str(p)):
            process_manifest_file(
                manifest_path=manifest_path,
                stats=stats,
                repo_root=repo_root,
                backup_dir=backup_dir,
                backed_up=backed_up,
                apply_mode=args.apply,
            )

    collect_integrity_counts(all_patch_dirs, stats)

    report_json_path, report_txt_path = write_reports(
        report_dir=report_dir,
        backup_dir=backup_dir,
        repo_root=repo_root,
        roots=roots,
        apply_mode=args.apply,
        stats=stats,
    )

    print(
        "Planned changes: "
        f"patches_to_modify={stats.patches_to_modify}, "
        f"files_to_create={stats.create_count}, "
        f"manifests_to_replace={stats.manifest_replace_count}"
    )
    print(
        "Integrity check: "
        f"gorearea_remaining={stats.verify_gorearea_count}, "
        f"missing_divstripzone={stats.verify_missing_divstripzone_count}, "
        f"missing_node={stats.verify_missing_node_count}, "
        f"missing_intersection_l={stats.verify_missing_intersection_l_count}"
    )
    print(f"Report JSON: {as_repo_path(report_json_path, repo_root)}")
    print(f"Report TXT : {as_repo_path(report_txt_path, repo_root)}")

    if not all_patch_dirs:
        return 2
    if stats.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

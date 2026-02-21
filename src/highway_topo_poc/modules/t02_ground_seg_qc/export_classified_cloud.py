from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ManifestItem:
    patch_key: str
    points_path: Path
    label_path: Path
    n_points: int | None
    n_ground: int | None


def run_export(
    *,
    in_manifest: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    ground_class: int = 2,
    non_ground_class: int = 1,
    out_format: str = "laz",
    verify: bool = True,
) -> dict[str, object]:
    if chunk_points < 1:
        raise ValueError("chunk_points must be >= 1")
    if not (0 <= ground_class <= 255):
        raise ValueError("ground_class must be within [0,255]")
    if not (0 <= non_ground_class <= 255):
        raise ValueError("non_ground_class must be within [0,255]")

    fmt = str(out_format).strip().lower()
    if fmt not in {"laz", "las"}:
        raise ValueError("out_format must be one of: laz, las")

    items = _load_manifest(Path(in_manifest))
    if not items:
        raise ValueError(f"manifest_empty: {in_manifest}")

    if workers != 1:
        print(f"WARN: workers={workers} is currently executed sequentially (workers=1).", file=sys.stderr)

    run_id_val = _gen_run_id() if run_id == "auto" else str(run_id)
    run_root = Path(out_root) / run_id_val
    cloud_root = run_root / "classified_cloud"
    cloud_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    failed_rows: list[dict[str, object]] = []
    laz_fallback_count = 0

    for item in items:
        row = _process_item(
            item=item,
            cloud_root=cloud_root,
            preferred_format=fmt,
            resume=bool(resume),
            chunk_points=int(chunk_points),
            ground_class=int(ground_class),
            non_ground_class=int(non_ground_class),
            verify=bool(verify),
        )
        rows.append(row)
        if str(row.get("out_format")) == "las" and str(row.get("reason", "")).startswith("fallback_laz_to_las"):
            laz_fallback_count += 1
        if not bool(row.get("overall_pass", False)):
            failed_rows.append(row)

    manifest_path = run_root / "classified_manifest.jsonl"
    _write_jsonl(manifest_path, rows)

    failed_path = run_root / "failed_patches.txt"
    if failed_rows:
        with failed_path.open("w", encoding="utf-8") as f:
            for row in failed_rows:
                f.write(f"{row['patch_key']}\t{row.get('reason', 'unknown')}\n")

    summary = {
        "run_id": run_id_val,
        "input_manifest": str(in_manifest),
        "cloud_root": str(cloud_root),
        "classified_manifest_path": str(manifest_path),
        "total_patches": int(len(rows)),
        "pass_patches": int(len(rows) - len(failed_rows)),
        "fail_patches": int(len(failed_rows)),
        "failed_list_path": str(failed_path) if failed_rows else None,
        "laz_fallback_count": int(laz_fallback_count),
    }
    _write_json(run_root / "classified_summary.json", summary)
    return summary


def _process_item(
    *,
    item: ManifestItem,
    cloud_root: Path,
    preferred_format: str,
    resume: bool,
    chunk_points: int,
    ground_class: int,
    non_ground_class: int,
    verify: bool,
) -> dict[str, object]:
    out_dir = cloud_root / item.patch_key
    out_dir.mkdir(parents=True, exist_ok=True)

    preferred_out = out_dir / f"merged_classified.{preferred_format}"
    fallback_out = out_dir / "merged_classified.las"

    existing = _resolve_existing_output(preferred_out=preferred_out, fallback_out=fallback_out, preferred_format=preferred_format)
    if resume and existing is not None and existing.is_file():
        return _verify_existing_export(
            item=item,
            out_path=existing,
            chunk_points=chunk_points,
            ground_class=ground_class,
            verify=verify,
            reason="resume_skip",
        )

    if not item.points_path.is_file():
        return _fail_row(item=item, out_dir=out_dir, reason=f"points_not_found:{item.points_path}")
    if not item.label_path.is_file():
        return _fail_row(item=item, out_dir=out_dir, reason=f"label_not_found:{item.label_path}")

    suffix = item.points_path.suffix.lower()
    if suffix not in {".las", ".laz"}:
        return _fail_row(item=item, out_dir=out_dir, reason=f"unsupported_points_format:{suffix}")

    labels = np.load(item.label_path, mmap_mode="r")
    if labels.ndim != 1:
        return _fail_row(item=item, out_dir=out_dir, reason=f"label_shape_invalid:{labels.shape}")
    n_labels = int(labels.shape[0])
    if item.n_points is not None and int(item.n_points) != n_labels:
        return _fail_row(
            item=item,
            out_dir=out_dir,
            reason=f"n_points_mismatch_manifest_label:manifest={item.n_points},label={n_labels}",
        )

    try:
        input_count = _read_point_count(item.points_path)
    except Exception as exc:
        return _fail_row(item=item, out_dir=out_dir, reason=f"input_read_error:{type(exc).__name__}:{exc}")

    if input_count != n_labels:
        return _fail_row(
            item=item,
            out_dir=out_dir,
            reason=f"n_points_mismatch_input_label:input={input_count},label={n_labels}",
        )

    write_reason = "ok"
    out_path = preferred_out
    actual_format = preferred_format
    try:
        write_info = _write_classified_stream(
            in_path=item.points_path,
            out_path=out_path,
            labels=labels,
            chunk_points=chunk_points,
            ground_class=ground_class,
            non_ground_class=non_ground_class,
        )
    except Exception as exc:
        if preferred_format == "laz" and _is_laz_backend_error(exc):
            write_reason = f"fallback_laz_to_las:{type(exc).__name__}"
            out_path = fallback_out
            actual_format = "las"
            _safe_unlink(preferred_out)
            try:
                write_info = _write_classified_stream(
                    in_path=item.points_path,
                    out_path=out_path,
                    labels=labels,
                    chunk_points=chunk_points,
                    ground_class=ground_class,
                    non_ground_class=non_ground_class,
                )
            except Exception as exc2:
                return _fail_row(item=item, out_dir=out_dir, reason=f"fallback_write_error:{type(exc2).__name__}:{exc2}")
        else:
            return _fail_row(item=item, out_dir=out_dir, reason=f"write_error:{type(exc).__name__}:{exc}")

    expected_ground = int(item.n_ground) if item.n_ground is not None else int(write_info["ground_count"])
    verify_row = _verify_written_export(
        item=item,
        out_path=out_path,
        out_format=actual_format,
        write_info=write_info,
        expected_points=n_labels,
        expected_ground=expected_ground,
        ground_class=ground_class,
        verify=verify,
        reason=write_reason,
    )
    return verify_row


def _write_classified_stream(
    *,
    in_path: Path,
    out_path: Path,
    labels: np.ndarray,
    chunk_points: int,
    ground_class: int,
    non_ground_class: int,
) -> dict[str, int]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required") from exc

    with laspy.open(str(in_path)) as reader:
        n_points = int(reader.header.point_count)
        dim_names = set(reader.header.point_format.dimension_names)
        if "classification" not in dim_names:
            raise ValueError("classification_dimension_missing")
        if labels.shape[0] != n_points:
            raise ValueError(f"label_length_mismatch: labels={labels.shape[0]} points={n_points}")

        with laspy.open(str(out_path), mode="w", header=reader.header) as writer:
            offset = 0
            ground_count = 0
            for pts in reader.chunk_iterator(chunk_points):
                n = int(len(pts.x))
                if n <= 0:
                    continue

                i0 = offset
                i1 = offset + n
                lab = np.asarray(labels[i0:i1], dtype=np.uint8)
                if lab.shape[0] != n:
                    raise ValueError(f"label_chunk_mismatch: expected={n} got={lab.shape[0]}")
                lab_bool = lab.astype(bool)

                cls = np.full((n,), non_ground_class, dtype=np.uint8)
                cls[lab_bool] = ground_class
                pts.classification = cls
                writer.write_points(pts)

                ground_count += int(np.count_nonzero(lab_bool))
                offset = i1

        if offset != n_points:
            raise ValueError(f"point_count_mismatch_after_write: expected={n_points} got={offset}")

    return {"point_count": n_points, "ground_count": int(ground_count)}


def _verify_written_export(
    *,
    item: ManifestItem,
    out_path: Path,
    out_format: str,
    write_info: dict[str, int],
    expected_points: int,
    expected_ground: int,
    ground_class: int,
    verify: bool,
    reason: str,
) -> dict[str, object]:
    out_count = int(write_info.get("point_count", -1))
    out_ground = int(write_info.get("ground_count", -1))

    ok_points = bool(out_count == expected_points)
    ok_ground = bool(out_ground == expected_ground)

    verify_out_points = out_count
    if verify:
        try:
            verify_out_points = _read_point_count(out_path)
            ok_points = bool(ok_points and verify_out_points == expected_points)
        except Exception as exc:
            return _fail_row(
                item=item,
                out_dir=out_path.parent,
                out_path=out_path,
                out_format=out_format,
                n_points=expected_points,
                n_ground=expected_ground,
                output_n_points=out_count,
                output_n_ground=out_ground,
                reason=f"verify_read_error:{type(exc).__name__}:{exc}",
            )

    if not ok_points:
        return _fail_row(
            item=item,
            out_dir=out_path.parent,
            out_path=out_path,
            out_format=out_format,
            n_points=expected_points,
            n_ground=expected_ground,
            output_n_points=verify_out_points,
            output_n_ground=out_ground,
            reason=f"verify_point_count_mismatch:expected={expected_points},actual={verify_out_points}",
        )

    if not ok_ground:
        return _fail_row(
            item=item,
            out_dir=out_path.parent,
            out_path=out_path,
            out_format=out_format,
            n_points=expected_points,
            n_ground=expected_ground,
            output_n_points=verify_out_points,
            output_n_ground=out_ground,
            reason=f"verify_ground_count_mismatch:expected={expected_ground},actual={out_ground}",
        )

    return {
        "patch_key": item.patch_key,
        "points_path": str(item.points_path),
        "label_path": str(item.label_path),
        "out_path": str(out_path),
        "out_format": out_format,
        "n_points": int(expected_points),
        "n_ground": int(expected_ground),
        "output_n_points": int(verify_out_points),
        "output_n_ground": int(out_ground),
        "ground_class": int(ground_class),
        "pass_fail": "pass",
        "overall_pass": True,
        "reason": reason,
        "output_dir": str(out_path.parent),
    }


def _verify_existing_export(
    *,
    item: ManifestItem,
    out_path: Path,
    chunk_points: int,
    ground_class: int,
    verify: bool,
    reason: str,
) -> dict[str, object]:
    out_format = out_path.suffix.lower().lstrip(".")

    if not verify:
        n_points = int(item.n_points) if item.n_points is not None else -1
        n_ground = int(item.n_ground) if item.n_ground is not None else -1
        return {
            "patch_key": item.patch_key,
            "points_path": str(item.points_path),
            "label_path": str(item.label_path),
            "out_path": str(out_path),
            "out_format": out_format,
            "n_points": n_points,
            "n_ground": n_ground,
            "output_n_points": n_points,
            "output_n_ground": n_ground,
            "ground_class": int(ground_class),
            "pass_fail": "pass",
            "overall_pass": True,
            "reason": reason,
            "output_dir": str(out_path.parent),
        }

    try:
        out_n_points, out_n_ground = _count_points_and_ground_class(
            out_path=out_path,
            chunk_points=chunk_points,
            ground_class=ground_class,
        )
    except Exception as exc:
        return _fail_row(
            item=item,
            out_dir=out_path.parent,
            out_path=out_path,
            out_format=out_format,
            reason=f"resume_verify_error:{type(exc).__name__}:{exc}",
        )

    expected_points = int(item.n_points) if item.n_points is not None else out_n_points
    expected_ground = int(item.n_ground) if item.n_ground is not None else out_n_ground

    if out_n_points != expected_points:
        return _fail_row(
            item=item,
            out_dir=out_path.parent,
            out_path=out_path,
            out_format=out_format,
            n_points=expected_points,
            n_ground=expected_ground,
            output_n_points=out_n_points,
            output_n_ground=out_n_ground,
            reason=f"resume_verify_point_count_mismatch:expected={expected_points},actual={out_n_points}",
        )
    if out_n_ground != expected_ground:
        return _fail_row(
            item=item,
            out_dir=out_path.parent,
            out_path=out_path,
            out_format=out_format,
            n_points=expected_points,
            n_ground=expected_ground,
            output_n_points=out_n_points,
            output_n_ground=out_n_ground,
            reason=f"resume_verify_ground_count_mismatch:expected={expected_ground},actual={out_n_ground}",
        )

    return {
        "patch_key": item.patch_key,
        "points_path": str(item.points_path),
        "label_path": str(item.label_path),
        "out_path": str(out_path),
        "out_format": out_format,
        "n_points": int(expected_points),
        "n_ground": int(expected_ground),
        "output_n_points": int(out_n_points),
        "output_n_ground": int(out_n_ground),
        "ground_class": int(ground_class),
        "pass_fail": "pass",
        "overall_pass": True,
        "reason": reason,
        "output_dir": str(out_path.parent),
    }


def _count_points_and_ground_class(*, out_path: Path, chunk_points: int, ground_class: int) -> tuple[int, int]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required") from exc

    with laspy.open(str(out_path)) as reader:
        total = int(reader.header.point_count)
        dim_names = set(reader.header.point_format.dimension_names)
        if "classification" not in dim_names:
            raise ValueError("classification_dimension_missing")

        out_ground = 0
        seen = 0
        for pts in reader.chunk_iterator(chunk_points):
            n = int(len(pts.x))
            if n <= 0:
                continue
            cls = np.asarray(pts.classification, dtype=np.uint8)
            out_ground += int(np.count_nonzero(cls == ground_class))
            seen += n
        if seen != total:
            raise ValueError(f"point_count_mismatch_when_counting: expected={total} got={seen}")
        return total, out_ground


def _read_point_count(path: Path) -> int:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required") from exc

    with laspy.open(str(path)) as reader:
        return int(reader.header.point_count)


def _load_manifest(path: Path) -> list[ManifestItem]:
    if not path.is_file():
        raise ValueError(f"manifest_not_found: {path}")

    items: list[ManifestItem] = []
    used: set[str] = set()

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ValueError(f"manifest_json_parse_error:{path}:{lineno}:{exc}") from exc

        if not isinstance(row, dict):
            raise ValueError(f"manifest_row_not_object:{path}:{lineno}")

        points_path = Path(str(row.get("points_path", "")))
        label_path = Path(str(row.get("label_path", "")))
        if not str(points_path):
            raise ValueError(f"manifest_points_path_missing:{path}:{lineno}")
        if not str(label_path):
            raise ValueError(f"manifest_label_path_missing:{path}:{lineno}")

        n_points = _opt_int(row.get("n_points"))
        n_ground = _opt_int(row.get("n_ground"))
        patch_key = _normalize_patch_key(str(row.get("patch_key", "")).strip(), points_path=points_path, used=used)

        items.append(
            ManifestItem(
                patch_key=patch_key,
                points_path=points_path,
                label_path=label_path,
                n_points=n_points,
                n_ground=n_ground,
            )
        )

    return items


def _normalize_patch_key(raw: str, *, points_path: Path, used: set[str]) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    if not key:
        key = re.sub(r"[^A-Za-z0-9._-]+", "_", points_path.parent.name).strip("_") or "patch"
    if key in used:
        base = key
        idx = 2
        while f"{base}_{idx}" in used:
            idx += 1
        key = f"{base}_{idx}"
    used.add(key)
    return key


def _resolve_existing_output(*, preferred_out: Path, fallback_out: Path, preferred_format: str) -> Path | None:
    if preferred_out.is_file():
        return preferred_out
    if preferred_format == "laz" and fallback_out.is_file():
        return fallback_out
    return None


def _is_laz_backend_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    keys = ["lazrs", "laszip", "backend", "compress", "decompress", "laz"]
    return any(k in msg for k in keys)


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return


def _fail_row(
    *,
    item: ManifestItem,
    out_dir: Path,
    reason: str,
    out_path: Path | None = None,
    out_format: str | None = None,
    n_points: int | None = None,
    n_ground: int | None = None,
    output_n_points: int | None = None,
    output_n_ground: int | None = None,
) -> dict[str, object]:
    return {
        "patch_key": item.patch_key,
        "points_path": str(item.points_path),
        "label_path": str(item.label_path),
        "out_path": str(out_path) if out_path is not None else None,
        "out_format": out_format,
        "n_points": int(n_points if n_points is not None else (item.n_points if item.n_points is not None else 0)),
        "n_ground": int(n_ground if n_ground is not None else (item.n_ground if item.n_ground is not None else 0)),
        "output_n_points": int(output_n_points) if output_n_points is not None else None,
        "output_n_ground": int(output_n_ground) if output_n_ground is not None else None,
        "ground_class": None,
        "pass_fail": "fail",
        "overall_pass": False,
        "reason": reason,
        "output_dir": str(out_dir),
    }


def _opt_int(v: object) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _gen_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(_to_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_to_json_safe(row), ensure_ascii=False, sort_keys=True) + "\n")


def _to_json_safe(v: object) -> object:
    if isinstance(v, dict):
        return {str(k): _to_json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_json_safe(x) for x in v]
    if isinstance(v, tuple):
        return [_to_json_safe(x) for x in v]
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.floating, float)):
        val = float(v)
        return val if math.isfinite(val) else None
    return v


def _parse_bool(s: str) -> bool:
    t = str(s).strip().lower()
    if t in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if t in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid_bool: {s}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="t02_ground_seg_qc.export_classified_cloud")
    parser.add_argument("--in_manifest", required=True)
    parser.add_argument("--out_root", default="outputs/_work/t02_ground_seg_qc")
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--resume", type=_parse_bool, default=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--chunk_points", type=int, default=2_000_000)
    parser.add_argument("--ground_class", type=int, default=2)
    parser.add_argument("--non_ground_class", type=int, default=1)
    parser.add_argument("--out_format", default="laz")
    parser.add_argument("--verify", type=_parse_bool, default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = run_export(
            in_manifest=args.in_manifest,
            out_root=args.out_root,
            run_id=args.run_id,
            resume=bool(args.resume),
            workers=int(args.workers),
            chunk_points=int(args.chunk_points),
            ground_class=int(args.ground_class),
            non_ground_class=int(args.non_ground_class),
            out_format=str(args.out_format),
            verify=bool(args.verify),
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"RunID: {summary['run_id']}")
    print(f"CloudRoot: {summary['cloud_root']}")
    print(f"ClassifiedManifest: {summary['classified_manifest_path']}")
    print(f"TotalPatches: {summary['total_patches']}")
    print(f"PassPatches: {summary['pass_patches']}")
    print(f"FailPatches: {summary['fail_patches']}")
    print(f"LAZFallbackCount: {summary['laz_fallback_count']}")
    if summary.get("failed_list_path"):
        print(f"FailedList: {summary['failed_list_path']}")

    return 2 if int(summary.get("fail_patches", 0)) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

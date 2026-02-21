from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .types import PatchCandidate


_CLOUD_NAMES = {"merged.laz", "merged.las"}
_TRAJ_NAME = "raw_dat_pose.geojson"


def _prefer_cloud(a: Path, b: Path) -> bool:
    a_name = a.name.lower()
    b_name = b.name.lower()
    if a_name == b_name:
        return a.as_posix() < b.as_posix()
    if a_name.endswith(".laz") and b_name.endswith(".las"):
        return True
    if a_name.endswith(".las") and b_name.endswith(".laz"):
        return False
    return a.as_posix() < b.as_posix()


def _choose_traj_for_cloud(cloud_path: Path, traj_candidates: list[Path], data_root: Path) -> Path:
    cloud_parent = cloud_path.parent

    def _sort_key(traj: Path) -> tuple[int, int, str]:
        rel = traj.relative_to(data_root).as_posix().lower()
        prefer_traj_dir = 0 if "/traj/" in f"/{rel}" else 1
        rel_parts = len(Path(os.path.relpath(traj, cloud_parent)).parts)
        return (prefer_traj_dir, rel_parts, rel)

    return sorted(traj_candidates, key=_sort_key)[0]


def discover_patch_candidates(data_root: Path) -> list[PatchCandidate]:
    data_root = data_root.resolve()
    if not data_root.exists():
        return []

    cloud_by_parent: dict[Path, Path] = {}
    traj_paths: list[Path] = []

    for p in sorted(data_root.rglob("*")):
        if not p.is_file():
            continue
        lname = p.name.lower()
        if lname in _CLOUD_NAMES:
            prev = cloud_by_parent.get(p.parent)
            if prev is None or _prefer_cloud(p, prev):
                cloud_by_parent[p.parent] = p
        elif lname == _TRAJ_NAME:
            traj_paths.append(p)

    @lru_cache(maxsize=None)
    def _trajs_under(parent: str) -> tuple[Path, ...]:
        p = Path(parent)
        return tuple(t for t in traj_paths if p in t.parents)

    pairs: list[PatchCandidate] = []
    for cloud_path in sorted(cloud_by_parent.values(), key=lambda x: x.as_posix()):
        chosen: Path | None = None

        ancestors = [cloud_path.parent, *cloud_path.parent.parents]
        for anc in ancestors:
            if anc == data_root.parent:
                break
            if anc != data_root and data_root not in anc.parents:
                continue
            cands = list(_trajs_under(str(anc)))
            if cands:
                chosen = _choose_traj_for_cloud(cloud_path, cands, data_root)
                break

        if chosen is None:
            continue

        patch_key = cloud_path.parent.relative_to(data_root).as_posix()
        pairs.append(
            PatchCandidate(
                cloud_path=cloud_path,
                traj_path=chosen,
                patch_key=patch_key,
            )
        )

    return pairs

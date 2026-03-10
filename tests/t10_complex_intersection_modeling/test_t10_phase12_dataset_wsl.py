from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    discover_geojson_dataset_inputs,
    parse_mainid_values,
    run_t10_mainnodeids_from_geojson_dataset,
)


def _node(node_id: int, x: float, y: float, *, mainid: int, kind: int = 4) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
        "properties": {"id": int(node_id), "mainid": int(mainid), "Kind": int(kind)},
    }


def _road(
    road_id: str,
    coords: list[tuple[float, ...]],
    *,
    snodeid: int,
    enodeid: int,
    direction: int = 1,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "properties": {
            "road_id": road_id,
            "snodeid": int(snodeid),
            "enodeid": int(enodeid),
            "direction": int(direction),
        },
    }


def _feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(json.dumps(_feature_collection(features), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_dataset_dir(path: Path, *, node_features: list[dict], road_features: list[dict], vector_layout: bool = True) -> Path:
    root = path / "Vector" if vector_layout else path
    root.mkdir(parents=True, exist_ok=True)
    _write_geojson(root / "RCSDNode.geojson", node_features)
    _write_geojson(root / "RCSDRoad.geojson", road_features)
    return path


def _service_intersection(mainid: int, *, node_offset: int, x_offset: float) -> tuple[list[dict], list[dict]]:
    nodes = [
        _node(node_offset + 1, x_offset + 0.0, -1.0, mainid=mainid),
        _node(node_offset + 2, x_offset + 2.0, -1.0, mainid=mainid),
        _node(node_offset + 3, x_offset + 0.0, 1.0, mainid=mainid),
        _node(node_offset + 4, x_offset + 2.0, 1.0, mainid=mainid),
        _node(node_offset + 5, x_offset - 1.0, 0.0, mainid=mainid),
        _node(node_offset + 6, x_offset + 3.0, 0.0, mainid=mainid),
    ]
    roads = [
        _road(f"south_service_{mainid}", [(x_offset + 0.0, -1.0), (x_offset + 0.0, -10.0)], snodeid=node_offset + 1, enodeid=node_offset + 101),
        _road(f"south_main_{mainid}", [(x_offset + 2.0, -1.0), (x_offset + 2.0, -10.0)], snodeid=node_offset + 2, enodeid=node_offset + 102),
        _road(f"north_service_{mainid}", [(x_offset + 0.0, 1.0), (x_offset + 0.0, 10.0)], snodeid=node_offset + 3, enodeid=node_offset + 103),
        _road(f"north_main_{mainid}", [(x_offset + 2.0, 1.0), (x_offset + 2.0, 10.0)], snodeid=node_offset + 4, enodeid=node_offset + 104),
        _road(f"west_{mainid}", [(x_offset - 1.0, 0.0), (x_offset - 10.0, 0.0)], snodeid=node_offset + 5, enodeid=node_offset + 105),
        _road(f"east_{mainid}", [(x_offset + 3.0, 0.0), (x_offset + 10.0, 0.0)], snodeid=node_offset + 6, enodeid=node_offset + 106),
    ]
    return nodes, roads


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_dir = _repo_root() / "src"
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_dir) if not existing else str(src_dir) + os.pathsep + existing
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "highway_topo_poc.modules.t10_complex_intersection_modeling.cli",
            *args,
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _to_wsl_path(path: Path) -> str:
    text = str(path)
    if ":" in text[:3]:
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return text.replace("\\", "/")


def test_phase12_parse_mainnodeids_and_discover_dataset_inputs(tmp_path: Path) -> None:
    dataset_dir = _write_dataset_dir(
        tmp_path / "SH",
        node_features=[_node(1, 0.0, -1.0, mainid=12113465), _node(2, 0.0, 1.0, mainid=12113465)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )

    assert parse_mainid_values(["12113465", "12113466,12113467"]) == (12113465, 12113466, 12113467)
    node_path, road_path = discover_geojson_dataset_inputs(dataset_dir)
    assert node_path.name == "RCSDNode.geojson"
    assert road_path.name == "RCSDRoad.geojson"
    assert node_path.parent.name == "Vector"


def test_phase12_dataset_runner_supports_multiple_mainnodeids_and_keeps_failures_visible(tmp_path: Path) -> None:
    mainid_a = 12113465
    mainid_b = 12113466
    nodes_a, roads_a = _service_intersection(mainid_a, node_offset=0, x_offset=0.0)
    nodes_b, roads_b = _service_intersection(mainid_b, node_offset=1000, x_offset=100.0)
    dataset_dir = _write_dataset_dir(
        tmp_path / "SH",
        node_features=[*nodes_a, *nodes_b],
        road_features=[*roads_a, *roads_b],
    )
    override_dir = tmp_path / "overrides"
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / f"{mainid_a}.json").write_text(
        json.dumps(
            {
                "service_profile_map": {f"south_service_{mainid_a}": "left_uturn_service"},
                "paired_mainline_map": {f"south_service_{mainid_a}": f"south_main_{mainid_a}"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "dataset_out"
    result = run_t10_mainnodeids_from_geojson_dataset(
        dataset_dir=dataset_dir,
        mainnodeids=[mainid_a, mainid_b, 99999999],
        manual_override_source=override_dir,
        output_root=output_root,
        validate_override=True,
        compute_buffer_m=320.0,
    )

    status_map = {item.mainnodeid: item for item in result.items}
    assert status_map[mainid_a].status == "success"
    assert status_map[mainid_b].status == "success"
    assert status_map[99999999].status == "error"
    assert (output_root / f"mainnodeid_{mainid_a}" / "base" / "approach_catalog.json").exists()
    assert (output_root / f"mainnodeid_{mainid_a}" / "rerun" / "override_roundtrip.json").exists()
    assert (output_root / f"mainnodeid_{mainid_a}" / "diff" / "run_diff.json").exists()
    assert (output_root / f"mainnodeid_{mainid_b}" / "base" / "review_summary.txt").exists()
    assert not (output_root / f"mainnodeid_{mainid_b}" / "rerun").exists()
    assert (output_root / f"mainnodeid_{99999999}" / "error.txt").exists()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["compute_buffer_m"] == 320.0


def test_phase12_cli_dataset_dir_mode_accepts_multiple_mainnodeids_and_compute_buffer(tmp_path: Path) -> None:
    mainid_a = 12113465
    mainid_b = 12113466
    nodes_a, roads_a = _service_intersection(mainid_a, node_offset=0, x_offset=0.0)
    nodes_b, roads_b = _service_intersection(mainid_b, node_offset=1000, x_offset=100.0)
    dataset_dir = _write_dataset_dir(
        tmp_path / "SH",
        node_features=[*nodes_a, *nodes_b],
        road_features=[*roads_a, *roads_b],
    )
    output_root = tmp_path / "cli_dataset_out"

    proc = _run_cli(
        "--dataset-dir",
        str(dataset_dir),
        "--mainnodeid",
        str(mainid_a),
        str(mainid_b),
        "--output-dir",
        str(output_root),
        "--compute-buffer-m",
        "250",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "dataset_mainnodeid_review_cycle"
    assert payload["compute_buffer_m"] == 250.0
    assert payload["mainnodeids"] == [mainid_a, mainid_b]
    assert (output_root / "manifest.json").exists()


def test_phase12_wsl_script_smoke_runs_against_temp_dataset(tmp_path: Path) -> None:
    mainid = 12113465
    nodes, roads = _service_intersection(mainid, node_offset=0, x_offset=0.0)
    dataset_dir = _write_dataset_dir(
        tmp_path / "SH",
        node_features=nodes,
        road_features=roads,
    )
    output_root = tmp_path / "wsl_script_out"
    repo_root = _repo_root()
    repo_root_wsl = _to_wsl_path(repo_root)
    dataset_dir_wsl = _to_wsl_path(dataset_dir)
    output_root_wsl = _to_wsl_path(output_root)
    script_path_wsl = _to_wsl_path(repo_root / "scripts" / "run_t10_sh_manual_mode.sh")

    syntax_proc = subprocess.run(
        ["bash", "-n", str(repo_root / "scripts" / "run_t10_sh_manual_mode.sh")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax_proc.returncode == 0, syntax_proc.stderr

    run_proc = subprocess.run(
        [
            "bash",
            "-lc",
            "cd "
            + shlex.quote(repo_root_wsl)
            + " && bash "
            + shlex.quote(script_path_wsl)
            + " --dataset-dir "
            + shlex.quote(dataset_dir_wsl)
            + " --mainnodeid "
            + shlex.quote(str(mainid))
            + " --output-root "
            + shlex.quote(output_root_wsl),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_proc.returncode == 0, run_proc.stderr
    assert (output_root / f"mainnodeid_{mainid}" / "base" / "serialized_bundle.json").exists()
    assert (output_root / "manifest.json").exists()


def test_phase12_dataset_runner_accepts_3d_linestring_coordinates(tmp_path: Path) -> None:
    mainid = 12113465
    node_features = [
        _node(1, 0.0, -1.0, mainid=mainid),
        _node(2, 0.0, 1.0, mainid=mainid),
    ]
    road_features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.0, -1.0, 5.0], [0.0, -10.0, 5.0]]},
            "properties": {"road_id": "south", "snodeid": 1, "enodeid": 101, "direction": 1},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0.0, 1.0, 5.0], [0.0, 10.0, 5.0]]},
            "properties": {"road_id": "north", "snodeid": 2, "enodeid": 102, "direction": 1},
        },
    ]
    dataset_dir = _write_dataset_dir(tmp_path / "SH_3D", node_features=node_features, road_features=road_features)
    output_root = tmp_path / "dataset_out_3d"

    result = run_t10_mainnodeids_from_geojson_dataset(
        dataset_dir=dataset_dir,
        mainnodeids=[mainid],
        output_root=output_root,
    )

    assert result.items[0].status == "success"
    serialized_bundle = json.loads((output_root / f"mainnodeid_{mainid}" / "base" / "serialized_bundle.json").read_text(encoding="utf-8"))
    first_line = serialized_bundle["approaches"][0]["geometry_ref"]["line"]
    assert isinstance(first_line, list)
    assert len(first_line[0]) == 2

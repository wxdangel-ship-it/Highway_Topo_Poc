from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""

    def __str__(self) -> str:
        return self.code if not self.detail else f"{self.code}:{self.detail}"


# Conservative patterns: prefer false positives over false negatives.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Common coordinate / CRS keywords.
    ("coord_keyword", re.compile(r"(?i)\b(lat|lon|latitude|longitude|epsg|utm|wgs84|srid|crs|easting|northing)\b")),
    # Suspicious axis assignments (even without numbers).
    ("coord_axis_assign", re.compile(r"(?i)\b(x|y|z)\s*[:=]")),
    # Lat/lon pair (comma-separated decimals).
    ("latlon_pair", re.compile(r"\b-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+\b")),
    # GeoJSON/WKT geometry signatures.
    ("geojson_coordinates", re.compile(r"(?i)\"coordinates\"\s*:\s*\[")),
    ("geojson_geometry", re.compile(r"(?i)\"geometry\"\s*:\s*\{")),
    ("wkt_geometry", re.compile(r"(?i)\b(POINT|LINESTRING|POLYGON|MULTI(?:POINT|LINESTRING|POLYGON)|GEOMETRYCOLLECTION)\s*\(")),
    # Bracketed numeric pairs often indicate vertices.
    ("bracketed_numeric_pair", re.compile(r"\[\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\]")),
    # Paths (Windows / WSL / Unix absolute).
    ("windows_path", re.compile(r"(?i)\b[a-z]:\\\\")),
    ("windows_path_slash", re.compile(r"(?i)\b[a-z]:/")),
    ("unc_path", re.compile(r"\\\\\\\\[A-Za-z0-9_.-]+\\")),
    ("wsl_mount_path", re.compile(r"(?i)/mnt/[a-z]/")),
    ("unix_abs_path", re.compile(r"(?i)\b/(home|data|var|etc|usr|opt|srv|root|tmp)/")),
    # IP address.
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def lint_text(text: str) -> tuple[bool, list[str]]:
    violations: list[Violation] = []

    for code, pat in _PATTERNS:
        if pat.search(text):
            violations.append(Violation(code))

    # Heuristics for raw dumps / arrays.
    for idx, line in enumerate(text.splitlines(), start=1):
        if len(line) > 500:
            violations.append(Violation("line_too_long", str(idx)))

        # Many comma-separated numeric tokens on one line is suspicious.
        if line.count(",") >= 30 and re.search(r"\d", line):
            violations.append(Violation("suspicious_numeric_list", str(idx)))

        # Dense JSON-like arrays.
        if line.count("[") >= 3 and re.search(r"\d", line):
            violations.append(Violation("suspicious_brackets", str(idx)))

    ok = len(violations) == 0
    return ok, [str(v) for v in violations]

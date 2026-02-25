from __future__ import annotations

import logging
import re
from typing import Any


logger = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(key: str) -> str:
    return _NON_ALNUM.sub("", str(key).strip().lower())


def normalize_props(props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, value in props.items():
        nk = normalize_key(str(raw_key))
        if not nk:
            continue
        if nk in out and out[nk] != value and out[nk] is not None and value is not None:
            logger.warning("field_norm_key_conflict: key=%s old=%r new=%r", nk, out[nk], value)
            continue
        if nk not in out:
            out[nk] = value
    return out


def get_first_raw(props_norm: dict[str, Any], keys_norm: list[str]) -> Any | None:
    for key in keys_norm:
        nk = normalize_key(key)
        if nk in props_norm and props_norm[nk] is not None:
            return props_norm[nk]
    return None


def get_first_int(props_norm: dict[str, Any], keys_norm: list[str]) -> int | None:
    raw = get_first_raw(props_norm, keys_norm)
    if raw is None:
        return None
    try:
        if isinstance(raw, bool):
            return int(raw)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float):
            return int(raw)
        return int(str(raw).strip())
    except Exception:
        return None


__all__ = [
    "get_first_int",
    "get_first_raw",
    "normalize_key",
    "normalize_props",
]

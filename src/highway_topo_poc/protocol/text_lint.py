from __future__ import annotations

from dataclasses import dataclass

from highway_topo_poc.utils.size_guard import MAX_BYTES, MAX_LINES, measure_text


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""

    def __str__(self) -> str:
        return self.code if not self.detail else f"{self.code}:{self.detail}"


def lint_text(text: str) -> tuple[bool, list[str]]:
    """Check whether text is pasteable.

    This is a *pasteability* guard (size/shape), not a sensitive-content filter.

    Rules:
    - Lines must be <= MAX_LINES (default 120)
    - UTF-8 bytes must be <= MAX_BYTES (default 8192)
    - Warn on very long single lines (may be hard to paste/read)

    Returns:
      (ok, violations)

    ok is False only when hard limits are exceeded.
    """

    v: list[Violation] = []

    s = measure_text(text)
    if s.lines > MAX_LINES:
        v.append(Violation("SIZE_LINES", f"lines={s.lines} max={MAX_LINES}"))
    if s.bytes_utf8 > MAX_BYTES:
        v.append(Violation("SIZE_BYTES", f"bytes={s.bytes_utf8} max={MAX_BYTES}"))

    # Optional: warnings that do not block ok.
    for idx, line in enumerate(text.splitlines(), start=1):
        if len(line) > 2000:
            v.append(Violation("LONG_LINE", f"line={idx} len={len(line)}"))

    hard = [x for x in v if x.code.startswith("SIZE_")]
    ok = len(hard) == 0

    return ok, [str(x) for x in v]

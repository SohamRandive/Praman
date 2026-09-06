"""Extract the architecture diagram from the README so the two cannot drift.

The README's mermaid block is the source of truth - it is what a reader on
GitHub actually sees. The exported PNG exists for slides and video, where
mermaid does not render, and it is derived rather than drawn so that editing
one and forgetting the other is not possible.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```mermaid\n(.*?)```", readme, re.S)
    if match is None:
        print("no mermaid block in README.md")
        return 1
    out = ROOT / "docs" / "figures" / "architecture.mmd"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(match.group(1), encoding="utf-8")
    print(f"extracted {len(match.group(1).splitlines())} lines to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

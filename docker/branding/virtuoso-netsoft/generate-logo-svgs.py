#!/usr/bin/env python3
"""Embed virtuoso-logo.png as base64 inside logo SVG wrappers (required for <img src> usage)."""
import base64
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPT_DIR / "assets"
PNG = ASSETS / "virtuoso-logo.png"
VIEWBOX_W, VIEWBOX_H = 1024, 378
LABEL = "Virtuoso NetSoft"


def main() -> None:
    if not PNG.is_file():
        raise SystemExit(f"Missing logo PNG: {PNG}")
    b64 = base64.b64encode(PNG.read_bytes()).decode("ascii")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEWBOX_W} {VIEWBOX_H}" '
        f'role="img" aria-label="{LABEL}">\n'
        f'  <image width="{VIEWBOX_W}" height="{VIEWBOX_H}" preserveAspectRatio="xMidYMid meet"\n'
        f'    href="data:image/png;base64,{b64}"/>\n'
        f"</svg>\n"
    )
    for name in ("logo_title_white.svg", "logo_white.svg"):
        out = ASSETS / name
        out.write_text(svg)
        print(f"Generated {out}")


if __name__ == "__main__":
    main()

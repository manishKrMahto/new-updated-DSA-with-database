#!/usr/bin/env python
"""
Draw the PBM agent's LangGraph compiled graph and save it as a PNG image.

Run from project root:
    python scripts/draw_langgraph.py

Output: pbm_agent_graph.png (in project root by default).
Use --output to save elsewhere.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on path when run as script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Save LangGraph compiled graph as PNG")
    default_out = Path(__file__).resolve().parent.parent / "pbm_agent_graph.png"
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_out,
        help=f"Output PNG path (default: {default_out})",
    )
    args = parser.parse_args()
    out_path = args.output.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from pbm_agent import graph

    drawable = graph.get_graph()
    png_bytes = drawable.draw_mermaid_png(output_file_path=str(out_path))
    size = len(png_bytes) if png_bytes else 0
    print(f"Graph image saved: {out_path}" + (f" ({size} bytes)" if size else ""))


if __name__ == "__main__":
    main()

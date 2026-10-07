"""Regenerate the terminal screenshots in docs/images from the demo project.

Run from the repository root: python scripts/screenshots.py
"""

from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI

from breakscope.contracts import load_contract
from breakscope.impact import analyze
from breakscope.reports.impact import render_terminal

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "demo"
OUT = ROOT / "docs" / "images"


def analyze_svg() -> None:
    old = "examples/demo/api/openapi-v1.yaml"
    new = "examples/demo/api/openapi-v2.yaml"
    report = analyze(load_contract(ROOT / old), load_contract(ROOT / new), DEMO)
    shown = [i for i in report.impacts if i.confidence.rank <= 1]

    console = Console(record=True, width=78, force_terminal=True, color_system="truecolor")
    console.print(f"[bold green]$[/] breakscope analyze {old} \\\n    {new} examples/demo\n")
    render_terminal(report, shown, console)

    OUT.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(OUT / "analyze.svg"), title="breakscope analyze", theme=MONOKAI)
    print(f"wrote {OUT / 'analyze.svg'}")


if __name__ == "__main__":
    analyze_svg()

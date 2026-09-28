"""Generate docs/assets/banner.svg (README cover).

Run: uv run python scripts/gen_banner.py
"""

import math
import random
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "assets" / "banner.svg"

W, H = 1280, 400
KNOT = (230, 205)
LANES_Y = [214, 238, 262, 286, 310]
LANE_START_X = 520
LANE_END = [1196, 1148, 1210, 1120, 1172]
SEED = 7

Point = tuple[float, float]

STYLE = """\
:root { --bg:#F2F4F8; --ink:#1A2340; --muted:#56607A; --grid:#DCE1EC;
  --t1:#3444A8; --t2:#D69A1C; --t3:#18877A; --t4:#C2416F; --t5:#6A3F99; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151B30; --ink:#EEF1F8; --muted:#A3ACC4; --grid:#232B45;
    --t1:#7F8FF0; --t2:#F2BC4B; --t3:#3FC2AE; --t4:#EE7AA3; --t5:#B08BE6; }
}
.bg { fill:var(--bg); }
.rule { stroke:var(--grid); stroke-width:1; }
.thread { fill:none; stroke-width:3.2; stroke-linecap:round; stroke-linejoin:round; }
.node { fill:var(--bg); stroke-width:3.2; }
.t1 { stroke:var(--t1); } .t2 { stroke:var(--t2); } .t3 { stroke:var(--t3); }
.t4 { stroke:var(--t4); } .t5 { stroke:var(--t5); }
.word { fill:var(--ink);
  font-family:'Avenir Next','Segoe UI Variable Display','Segoe UI',
    'Helvetica Neue',Arial,sans-serif;
  font-weight:800; font-size:112px; letter-spacing:-4px; }
.tag { fill:var(--muted);
  font-family:'Avenir Next','Segoe UI','Helvetica Neue',Arial,sans-serif;
  font-weight:500; font-size:24px; letter-spacing:-0.2px; }
"""

DESC = (
    "A tangled skein of threads on the left straightens into five ordered lanes "
    "ending in module nodes, beside the unskein wordmark."
)


def catmull_rom(points: list[Point]) -> str:
    """Convert points into a smooth SVG path through all of them.

    Args:
        points: Points the curve must pass through, in order.

    Returns:
        SVG path data made of cubic Bézier segments (Catmull-Rom spline).
    """
    d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def thread_path(rng: random.Random, lane_y: int, end_x: int) -> str:
    """Build one thread: random loops around the knot, then a straight lane.

    Args:
        rng: Seeded random generator, so the banner is reproducible.
        lane_y: Vertical position of the thread's straight lane.
        end_x: Horizontal position where the lane ends in a module node.

    Returns:
        SVG path data for the thread.
    """
    cx, cy = KNOT
    angle = rng.uniform(0, 2 * math.pi)
    pts: list[Point] = []
    for _ in range(14):
        r = rng.uniform(34, 140)
        pts.append((cx + r * math.cos(angle) * 1.15, cy + r * math.sin(angle)))
        angle += rng.uniform(1.6, 2.6)
    pts += [(405, cy + (lane_y - cy) * 0.4), (462, lane_y), (LANE_START_X, lane_y)]
    return catmull_rom(pts) + f" L{end_x},{lane_y}"


def build_svg() -> str:
    """Build the banner SVG with light and dark palettes.

    Returns:
        The complete SVG document.
    """
    rng = random.Random(SEED)
    rules, threads, nodes = [], [], []
    for i, (y, end_x) in enumerate(zip(LANES_Y, LANE_END, strict=True), start=1):
        rules.append(f'<line class="rule" x1="{LANE_START_X}" y1="{y}" x2="1240" y2="{y}"/>')
        threads.append(f'<path class="thread t{i}" d="{thread_path(rng, y, end_x)}"/>')
        nodes.append(f'<circle class="node t{i}" cx="{end_x}" cy="{y}" r="6.5"/>')

    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" \
role="img" aria-labelledby="title desc">
<title id="title">unskein</title>
<desc id="desc">{DESC}</desc>
<style>
{STYLE}</style>
<rect class="bg" width="{W}" height="{H}"/>
{"".join(rules)}
<g>{"".join(threads)}</g>
<g>{"".join(nodes)}</g>
<text class="word" x="510" y="166">unskein</text>
<text class="tag" x="520" y="360">Untangle the dependencies of your Python project.</text>
</svg>
"""


if __name__ == "__main__":
    OUTPUT.write_text(build_svg(), encoding="utf-8")
    print(f"wrote {OUTPUT}")

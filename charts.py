"""Pure-SVG chart rendering — no JS, no image library dependency.

Every function here returns markup meant to be embedded with Jinja's `| safe`
filter. To stay XSS-safe, that markup must only ever contain *numbers*
(coordinates, dash offsets, percentages) or text that is never user input —
category names, which are, must be rendered separately as normal
auto-escaped Jinja text (see the `legend` return value of `donut_chart`).
"""

import math

CHART_COLORS = [
    "var(--chart-1)",
    "var(--chart-2)",
    "var(--chart-3)",
    "var(--chart-4)",
    "var(--chart-5)",
]
OTHER_COLOR = "var(--chart-6)"

MAX_DONUT_SEGMENTS = 5  # beyond this, the tail is grouped into "Other"


def bar_chart(monthly_data, width=320, height=180):
    """Grouped monthly cash-in/cash-out bars.

    monthly_data: list of {'month': 'YYYY-MM', 'in_cents': int, 'out_cents': int}
    (as returned by db.monthly_totals — server-generated, never user input).
    Returns an SVG string, or None if there is no data to chart.
    """
    if not monthly_data:
        return None

    label_h = 22
    chart_h = height - label_h
    max_val = max((max(e["in_cents"], e["out_cents"]) for e in monthly_data), default=0) or 1

    n = len(monthly_data)
    group_w = width / n
    bar_w = group_w * 0.32

    parts = [f'<svg class="bar-chart" viewBox="0 0 {width} {height}" role="img">']
    for i, entry in enumerate(monthly_data):
        group_x = i * group_w
        in_h = (entry["in_cents"] / max_val) * chart_h
        out_h = (entry["out_cents"] / max_val) * chart_h
        in_x = group_x + group_w * 0.16
        out_x = in_x + bar_w + 3

        parts.append(
            f'<rect x="{in_x:.1f}" y="{chart_h - in_h:.1f}" width="{bar_w:.1f}" '
            f'height="{in_h:.1f}" fill="var(--green)" rx="2"></rect>'
        )
        parts.append(
            f'<rect x="{out_x:.1f}" y="{chart_h - out_h:.1f}" width="{bar_w:.1f}" '
            f'height="{out_h:.1f}" fill="var(--red)" rx="2"></rect>'
        )

        label = _month_label(entry["month"])
        parts.append(
            f'<text x="{group_x + group_w / 2:.1f}" y="{height - 6}" '
            f'text-anchor="middle">{label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _month_label(yyyy_mm):
    import datetime

    try:
        return datetime.datetime.strptime(yyyy_mm + "-01", "%Y-%m-%d").strftime("%b")
    except ValueError:
        return yyyy_mm


def donut_chart(rows, size=180, stroke_width=28):
    """Category breakdown donut.

    rows: sqlite3.Row list with category_name/total_cents, sorted descending
    (as returned by db.category_breakdown). Returns (svg, legend, total_cents):
      - svg: numeric-only SVG markup, safe to render with `| safe`.
      - legend: list of {'name', 'amount_cents', 'pct', 'color'} for the
        caller to render as normal auto-escaped template text.
      - total_cents: sum across all rows (0 if rows is empty).
    """
    total = sum(r["total_cents"] for r in rows)
    if not rows or total == 0:
        return None, [], 0

    segments = [
        {"name": r["category_name"], "amount_cents": r["total_cents"]} for r in rows
    ]
    if len(segments) > MAX_DONUT_SEGMENTS:
        head = segments[:MAX_DONUT_SEGMENTS]
        other_total = sum(s["amount_cents"] for s in segments[MAX_DONUT_SEGMENTS:])
        segments = head + [{"name": "Other", "amount_cents": other_total}]

    legend = []
    for i, seg in enumerate(segments):
        color = CHART_COLORS[i] if i < len(CHART_COLORS) else OTHER_COLOR
        legend.append(
            {
                "name": seg["name"],
                "amount_cents": seg["amount_cents"],
                "pct": seg["amount_cents"] / total * 100,
                "color": color,
            }
        )

    cx = cy = size / 2
    r = size / 2 - stroke_width / 2
    circumference = 2 * math.pi * r

    parts = [f'<svg class="donut-chart" viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img">']
    cumulative = 0.0
    for entry in legend:
        dash = entry["pct"] / 100 * circumference
        offset = -cumulative
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" '
            f'stroke="{entry["color"]}" stroke-width="{stroke_width}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{offset:.2f}" '
            f'transform="rotate(-90 {cx:.1f} {cy:.1f})"></circle>'
        )
        cumulative += dash
    parts.append("</svg>")

    return "".join(parts), legend, total

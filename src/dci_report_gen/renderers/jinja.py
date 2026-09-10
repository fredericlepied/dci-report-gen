from __future__ import annotations

import re
from pathlib import Path

import markdown as md
import yaml
from jinja2 import Environment, FileSystemLoader

from dci_report_gen.renderers.formatters import _format_date, _format_duration

DEFAULT_CSS = Path(__file__).parent / "default.css"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _build_env(search_paths: list[str | Path]) -> Environment:
    env = Environment(
        loader=FileSystemLoader([str(p) for p in search_paths]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["duration"] = _filter_duration
    env.filters["date"] = _filter_date
    env.filters["jira_link"] = _filter_jira_link
    env.filters["github_link"] = _filter_github_link
    env.filters["status_emoji"] = _filter_status_emoji
    env.filters["dci_link"] = _filter_dci_link
    env.filters["short_id"] = _filter_short_id
    env.filters["human_duration"] = _filter_human_duration
    env.filters["compact_duration"] = _filter_compact_duration
    env.filters["find_testcase"] = _filter_find_testcase
    env.filters["github_run_link"] = _filter_github_run_link
    env.filters["find_file"] = _filter_find_file
    env.filters["regex_extract"] = _filter_regex_extract
    env.filters["yaml_path"] = _filter_yaml_path
    env.filters["line_chart_svg"] = _filter_line_chart_svg
    return env


def _filter_duration(value):
    if value is None:
        return ""
    return _format_duration(value)


def _filter_date(value):
    if value is None:
        return ""
    return _format_date(value)


def _filter_jira_link(key, base_url="https://redhat.atlassian.net"):
    if not key:
        return ""
    return f"[{key}]({base_url}/browse/{key})"


def _filter_github_link(number, repo=""):
    if not number:
        return ""
    if repo:
        return f"[#{number}](https://github.com/{repo}/pull/{number})"
    return f"#{number}"


_STATUS_EMOJI = {
    "success": "✅",
    "failure": "❌",
    "error": "❌",
    "killed": "❌",
    "running": "\U0001f504",
    "new": "\U0001f504",
    "pre-run": "\U0001f504",
    "post-run": "\U0001f504",
}


def _filter_status_emoji(value):
    return _STATUS_EMOJI.get(str(value), str(value))


def _filter_dci_link(job_id, tab="tests"):
    if not job_id:
        return ""
    short = str(job_id)[:8]
    return f"[{short}](https://www.distributed-ci.io/jobs/{job_id}/{tab})"


def _filter_short_id(value, length=8):
    if not value:
        return ""
    return str(value)[:length]


def _filter_compact_duration(seconds):
    try:
        s = int(float(seconds))
    except (ValueError, TypeError):
        return str(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"


def _filter_human_duration(seconds, style="short"):
    try:
        s = int(float(seconds))
    except (ValueError, TypeError):
        return str(seconds)
    m, sec = divmod(s, 60)
    if style == "long":
        return f"{m} minutes and {sec} seconds"
    return f"{m}m {sec:02d}s"


def _filter_find_testcase(tests, name):
    if not tests:
        return None
    for test in tests:
        for suite in test.get("testsuites", []):
            for tc in suite.get("testcases", []):
                if name in tc.get("name", ""):
                    return tc
    return None


def _filter_github_run_link(tags, repo):
    if not tags or not repo:
        return ""
    for tag in tags:
        tag_str = str(tag)
        if tag_str.startswith("github-"):
            run_id = tag_str[len("github-"):]
            return f"[{tag_str}](https://github.com/{repo}/actions/runs/{run_id})"
    return ""


def _filter_find_file(files, pattern):
    if not files:
        return None
    for f in files:
        if re.search(pattern, f.get("name", "")):
            return f.get("content")
    return None


def _filter_regex_extract(text, pattern):
    if not text:
        return None
    m = re.search(pattern, str(text))
    if m:
        g = m.group(1)
        return g.strip() if g is not None else None
    return None


def _filter_yaml_path(text, dotted_path):
    if not text:
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    for key in dotted_path.split("."):
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def _filter_line_chart_svg(
    buckets: list[dict],
    title: str = "Jobs with *console.log (%)",
) -> str:
    """Generate a responsive inline SVG multi-line chart from ES bucket data.

    Uses viewBox + width="100%" so the chart scales to fit any container.
    Legend is rendered below the plot area to avoid horizontal overflow.

    Each bucket must have:
      - bucket.rc_name.hits.hits[0]._source.remoteci.name: display name
      - bucket.by_week.buckets[]: {key_as_string, doc_count, with_console_log.doc_count}
    """
    import html as _html
    import math

    if not buckets:
        return ""

    # --- unique weeks, sorted ascending ---
    weeks_set: set[str] = set()
    for b in buckets:
        for w in b.get("by_week", {}).get("buckets", []):
            weeks_set.add(w["key_as_string"][:10])
    weeks = sorted(weeks_set)
    if not weeks:
        return ""

    # --- 22 distinguishable colours + 3 dash patterns as CVD secondary encoding ---
    _BASE_COLORS = [
        "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
        "#e87ba4", "#008300", "#4a3aa7", "#e34948",
    ]
    _EXTRA_COLORS = [
        "hsl(195,65%,35%)", "hsl(30,70%,38%)", "hsl(155,60%,32%)", "hsl(55,75%,35%)",
        "hsl(320,60%,42%)", "hsl(100,55%,32%)", "hsl(265,55%,48%)", "hsl(10,65%,42%)",
        "hsl(230,50%,50%)", "hsl(75,60%,35%)", "hsl(180,65%,30%)", "hsl(15,65%,45%)",
        "hsl(280,50%,40%)", "hsl(45,70%,38%)",
    ]
    _ALL_COLORS = _BASE_COLORS + _EXTRA_COLORS
    _DASHES = ["none", "6,3", "4,2,1,2"]

    series = []
    for i, b in enumerate(buckets):
        hits = (b.get("rc_name", {}).get("hits", {}).get("hits", []) or [{}])
        name = (
            (hits[0] if hits else {})
            .get("_source", {})
            .get("remoteci", {})
            .get("name", b.get("key", f"rc-{i}"))
        )
        week_pct: dict[str, float] = {}
        for w in b.get("by_week", {}).get("buckets", []):
            week = w["key_as_string"][:10]
            total = w.get("doc_count", 0)
            with_log = w.get("with_console_log", {}).get("doc_count", 0)
            week_pct[week] = round(with_log / total * 100, 1) if total > 0 else 0.0
        series.append({
            "name": name,
            "data": week_pct,
            "color": _ALL_COLORS[i % len(_ALL_COLORS)],
            "dash": _DASHES[(i // len(_ALL_COLORS)) % len(_DASHES)],
        })

    # --- layout (internal viewBox coordinates) ---
    VW = 680          # viewBox width — scales to container via width="100%"
    L, T, B = 52, 36, 268        # plot left edge, top, bottom
    R = VW - 12                  # plot right edge
    pw, ph = R - L, B - T

    # Legend below the plot: 2 columns
    per_col = math.ceil(len(series) / 2)
    leg_row_h = 18
    leg_top = B + 52             # below x-axis labels (allow ~50px for rotated labels)
    col0_x, col1_x = L, L + (VW - L) // 2
    VH = leg_top + per_col * leg_row_h + 12

    SURFACE = "#fcfcfb"
    GRID = "#e1e0d9"
    AXIS_CLR = "#c3c2b7"
    MUTED = "#898781"
    TEXT = "#52514e"

    def xp(i: int) -> int:
        return L + round(i * pw / max(len(weeks) - 1, 1))

    def yp(pct: float) -> int:
        return B - round(pct / 100 * ph)

    out: list[str] = []
    # Responsive SVG: scales to container width, preserves aspect ratio
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {VW} {VH}" width="100%" '
        f'style="display:block;font-family:system-ui,sans-serif;'
        f'font-size:10px;background:{SURFACE}">'
    )

    # title
    out.append(
        f'<text x="{(L + R) // 2}" y="22" text-anchor="middle" '
        f'font-size="12" font-weight="600" fill="{TEXT}">'
        f'{_html.escape(title)}</text>'
    )

    # Y-axis grid + labels
    for pct in (0, 25, 50, 75, 100):
        y = yp(pct)
        out.append(f'<line x1="{L}" y1="{y}" x2="{R}" y2="{y}" stroke="{GRID}" stroke-width="1"/>')
        out.append(
            f'<text x="{L - 5}" y="{y + 4}" text-anchor="end" '
            f'fill="{MUTED}" font-variant-numeric="tabular-nums">{pct}%</text>'
        )

    # X-axis: vertical grid + rotated labels
    for i, week in enumerate(weeks):
        x = xp(i)
        out.append(f'<line x1="{x}" y1="{T}" x2="{x}" y2="{B}" stroke="{GRID}" stroke-width="1"/>')
        out.append(
            f'<text x="{x}" y="{B + 14}" text-anchor="end" fill="{MUTED}" '
            f'transform="rotate(-35,{x},{B + 14})">{week}</text>'
        )

    # plot border
    out.append(f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="none" stroke="{AXIS_CLR}" stroke-width="1"/>')

    # data lines (back-to-front: first series on top)
    for s in reversed(series):
        pts = [(xp(i), yp(s["data"][w])) for i, w in enumerate(weeks) if w in s["data"]]
        if len(pts) >= 2:
            pts_str = " ".join(f"{x},{y}" for x, y in pts)
            da = f'stroke-dasharray="{s["dash"]}"' if s["dash"] != "none" else ""
            out.append(
                f'<polyline points="{pts_str}" fill="none" stroke="{s["color"]}" '
                f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" {da}/>'
            )
        for x, y in pts:
            # 2px surface ring then filled marker
            out.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{SURFACE}" stroke="{SURFACE}" stroke-width="2"/>')
            out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{s["color"]}"/>')

    # legend — 2 columns below the plot
    for i, s in enumerate(series):
        col = i // per_col
        row = i % per_col
        lx = col0_x if col == 0 else col1_x
        ly = leg_top + row * leg_row_h
        da = f'stroke-dasharray="{s["dash"]}"' if s["dash"] != "none" else ""
        out.append(
            f'<line x1="{lx}" y1="{ly + 6}" x2="{lx + 18}" y2="{ly + 6}" '
            f'stroke="{s["color"]}" stroke-width="2" {da}/>'
        )
        out.append(f'<circle cx="{lx + 9}" cy="{ly + 6}" r="3" fill="{s["color"]}"/>')
        out.append(
            f'<text x="{lx + 22}" y="{ly + 10}" fill="{TEXT}" font-size="9.5">'
            f'{_html.escape(s["name"])}</text>'
        )

    out.append("</svg>")
    return "\n".join(out)


def render_markdown(
    template_name: str,
    search_paths: list[str | Path],
    context: dict,
) -> str:
    env = _build_env(search_paths)
    template = env.get_template(template_name)
    return template.render(**context)


def markdown_to_pdf(
    md_text: str,
    output_path: str,
    css_path: str | Path | None = None,
) -> None:
    html_body = md.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
    )
    css_file = Path(css_path) if css_path else DEFAULT_CSS
    css_content = css_file.read_text() if css_file.exists() else ""

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{css_content}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    from weasyprint import HTML

    HTML(string=html_doc).write_pdf(output_path)

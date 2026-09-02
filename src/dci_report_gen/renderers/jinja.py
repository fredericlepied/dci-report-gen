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

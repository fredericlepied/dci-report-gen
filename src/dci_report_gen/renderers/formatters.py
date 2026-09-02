from __future__ import annotations

from datetime import datetime


def format_value(value, fmt: str | None = None):
    if value is None:
        return ""
    if fmt == "date":
        return _format_date(value)
    if fmt == "duration":
        return _format_duration(value)
    return str(value)


def format_value_md(value, fmt: str | None = None):
    if value is None:
        return ""

    if fmt == "jira_link":
        key = str(value)
        return f"[{key}](https://redhat.atlassian.net/browse/{key})"
    if fmt == "github_pr_link":
        return str(value)

    return format_value(value, fmt)


def _format_date(value) -> str:
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value
    return str(value)


def _format_duration(value) -> str:
    try:
        seconds = int(float(value))
    except (ValueError, TypeError):
        return str(value)

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

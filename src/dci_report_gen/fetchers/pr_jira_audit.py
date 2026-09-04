"""Composite fetcher: cross-references GitHub PRs with Jira tickets.

For each open PR found via the GitHub search query, checks whether any
Jira ticket in the configured projects references the PR URL (in summary,
description, or comments).  Returns a flat list of enriched PR rows with
a ``linked`` flag and the matched Jira keys.

Strategy: run one ``text ~ "<full-url>"`` JQL query per PR, then verify
client-side that the PR URL actually appears in a candidate's summary,
description, or comments.  Jira Cloud dropped exact-phrase matching for
the ``~`` operator, so the JQL is only a coarse pre-filter (it matches on
tokenised words such as the repo name); the client-side check is what
makes a match correct.
"""

from __future__ import annotations

import itertools
import os
import sys
import time

from github import Github
from jira import JIRA
from jira.exceptions import JIRAError

from dci_report_gen.config import SourceConfig


def _github_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is required")
    return Github(token)


def _jira_client():
    url = os.environ.get("JIRA_URL", "https://redhat.atlassian.net")
    token = os.environ.get("JIRA_TOKEN") or os.environ.get("JIRA_API_TOKEN")
    email = os.environ.get("JIRA_EMAIL")
    if not token:
        raise RuntimeError(
            "JIRA_TOKEN or JIRA_API_TOKEN environment variable is required"
        )
    if email:
        return JIRA(server=url, basic_auth=(email, token))
    return JIRA(server=url, token_auth=token)


def _extract_pr(issue) -> dict:
    repo_name = issue.repository.full_name if issue.repository else ""
    return {
        "number": issue.number,
        "title": issue.title.replace("|", "–"),
        "state": issue.state,
        "author": issue.user.login if issue.user else "",
        "url": issue.html_url,
        "created_at": issue.created_at.isoformat() if issue.created_at else "",
        "repo": repo_name,
    }


def _references(issue, pr_url: str) -> bool:
    """True if ``pr_url`` literally appears in the issue's text fields."""
    fields = issue.fields
    parts = [fields.summary or "", fields.description or ""]
    comment = getattr(fields, "comment", None)
    if comment is not None:
        parts.extend(c.body or "" for c in comment.comments)
    return any(pr_url in text for text in parts)


class PrJiraAuditFetcher:
    """Fetch open PRs and check for Jira traceability."""

    def fetch(self, source: SourceConfig) -> list[dict]:
        if not source.query:
            return []

        params = source.params or {}
        jira_projects = params.get("jira_projects", "CILAB,CNF")

        # --- Step 1: fetch PRs from GitHub ---
        gh = _github_client()
        results = gh.search_issues(source.query)
        prs = [
            _extract_pr(issue)
            for issue in itertools.islice(results, source.max_results)
        ]
        print(f"  GitHub: found {len(prs)} PRs", file=sys.stderr)

        # --- Step 2: for each PR, JQL pre-filter + client-side verify ---
        jira = _jira_client()
        projects_clause = ", ".join(jira_projects.split(","))
        total = len(prs)

        for idx, pr in enumerate(prs, 1):
            pr_url = pr["url"]
            # Coarse pre-filter; the plain URL (no escaped quotes) keeps
            # Jira's word tokenisation narrow enough to include the real
            # match, then _references() verifies it below.
            jql = (
                f'project in ({projects_clause}) '
                f'AND text ~ "{pr_url}"'
            )
            if idx % 10 == 1 or idx == total:
                print(
                    f"  Jira: checking PR {idx}/{total}: {pr_url}",
                    file=sys.stderr,
                )
            try:
                issues = jira.search_issues(
                    jql, maxResults=50,
                    fields="key,summary,description,comment",
                )
                matched = [t.key for t in issues if _references(t, pr_url)]
                pr["jira_keys"] = matched
                pr["linked"] = len(matched) > 0
            except (ValueError, RuntimeError, OSError, JIRAError) as exc:
                print(
                    f"  Jira lookup failed for {pr_url}: {exc}",
                    file=sys.stderr,
                )
                pr["jira_keys"] = []
                pr["linked"] = False

            # Rate-limit: ~3 req/s
            time.sleep(0.3)

        linked = sum(1 for p in prs if p["linked"])
        print(
            f"  Audit complete: {linked}/{len(prs)} PRs linked to Jira",
            file=sys.stderr,
        )
        return prs

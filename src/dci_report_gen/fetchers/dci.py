from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from dciclient.v1.api import context as dci_context
from dciclient.v1.api import file as dci_file
from dciclient.v1.api import job as dci_job

from dci_report_gen.config import SourceConfig


def _get_context():
    return dci_context.build_signature_context()


def _extract_field(obj: dict, dotted_key: str):
    parts = dotted_key.split(".")
    current = obj
    for i, part in enumerate(parts):
        if current is None:
            return None
        if isinstance(current, list):
            return ", ".join(
                str(_extract_field(item, ".".join(parts[i:])))
                for item in current
                if item is not None
            )
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _flatten_row(hit: dict, fields: list[str] | None) -> dict:
    if fields:
        return {f: _extract_field(hit, f) for f in fields}
    return hit


class DCIFetcher:
    def fetch(self, source: SourceConfig) -> list[dict]:
        ctx = _get_context()

        if source.transform == "weekly_file_coverage":
            return self._transform_weekly_file_coverage(ctx, source)
        if source.query:
            return self._search_jobs(ctx, source)
        return []

    def _search_jobs(self, ctx, source: SourceConfig) -> list[dict]:
        fields = list(source.fields) if source.fields else None
        if source.include_results:
            if fields is None:
                fields = []
            for f in ("tests", "results", "id"):
                if f not in fields:
                    fields.append(f)
        if source.include_files:
            if fields is None:
                fields = []
            for f in ("files.id", "files.name", "id"):
                if f not in fields:
                    fields.append(f)

        import json as _json

        params = {"query": source.query, "limit": source.limit, "sort": source.sort}
        if fields:
            params["fields"] = ",".join(fields)
        if source.aggs:
            # DCI server requires the aggregation wrapped under {"aggs": ...}
            # and sent as the "json-aggs" parameter (not "aggs").
            params["json-aggs"] = _json.dumps({"aggs": source.aggs})

        resp = dci_job.search(ctx, **params)
        if resp.status_code != 200:
            raise RuntimeError(f"DCI search failed ({resp.status_code}): {resp.text}")

        data = resp.json()

        if source.aggs and "aggregations" in data:
            if source.aggs_raw:
                return [data["aggregations"]]
            return self._flatten_aggs(data["aggregations"])

        hits_obj = data.get("hits", {})
        hits = hits_obj.get("hits", []) if isinstance(hits_obj, dict) else hits_obj
        sources = [hit.get("_source", hit) for hit in hits]

        if source.include_results or source.include_files:
            if source.include_files:
                self._download_files(ctx, sources, source.file_patterns)
            return sources

        return [_flatten_row(src, source.fields) for src in sources]

    def _download_files(self, ctx, jobs: list[dict], patterns: list[str] | None) -> None:
        for job in jobs:
            raw_files = job.get("files", [])
            enriched = []
            for f in raw_files:
                file_id = f.get("id")
                file_name = f.get("name", "")
                if not file_id:
                    continue
                if patterns and not any(re.search(p, file_name) for p in patterns):
                    continue
                print(f"    Downloading {file_name}...", file=sys.stderr)
                resp = dci_file.content(ctx, id=file_id)
                if resp.status_code == 200:
                    try:
                        content = resp.content.decode("utf-8")
                    except UnicodeDecodeError:
                        content = ""
                else:
                    print(
                        f"    Warning: failed to download {file_name} ({resp.status_code})",
                        file=sys.stderr,
                    )
                    content = ""
                enriched.append({"name": file_name, "id": file_id, "content": content})
            job["files"] = enriched

    def _transform_weekly_file_coverage(self, ctx, source: SourceConfig) -> list[dict]:
        """Paginated fetch of all jobs matching source.query, then aggregate:
        per remoteci, per ISO week → total jobs vs. jobs missing a file whose
        name matches any pattern in source.file_patterns (default: console.log)."""
        patterns = source.file_patterns or ["console\\.log$"]

        def _has_match(job: dict) -> bool:
            files = job.get("files") or []
            return any(
                re.search(p, f.get("name", ""), re.IGNORECASE)
                for f in files
                for p in patterns
            )

        def _week_start(date_str: str) -> str:
            dt = datetime.fromisoformat(date_str[:19])
            return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")

        # Paginate through all matching jobs (page_size fixed at 200)
        page_size = 200
        offset = 0
        all_jobs: list[dict] = []
        while True:
            params = {
                "query": source.query,
                "limit": page_size,
                "offset": offset,
                "sort": source.sort,
                "fields": "id,remoteci.name,created_at,files.name",
            }
            resp = dci_job.search(ctx, **params)
            if resp.status_code != 200:
                raise RuntimeError(f"DCI search failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            hits_obj = data.get("hits", {})
            hits = hits_obj.get("hits", []) if isinstance(hits_obj, dict) else hits_obj
            page = [h.get("_source", h) for h in hits]
            all_jobs.extend(page)

            total_obj = hits_obj.get("total", 0) if isinstance(hits_obj, dict) else 0
            total_val = total_obj.get("value", 0) if isinstance(total_obj, dict) else int(total_obj)

            print(
                f"    … fetched {len(all_jobs)}/{total_val} jobs (offset={offset})",
                file=sys.stderr,
            )
            if len(page) < page_size or offset + page_size >= total_val:
                break
            offset += page_size

        # Aggregate: remoteci → week → {total, with_log}
        rc_weeks: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"total": 0, "with_log": 0}))
        for job in all_jobs:
            rc = job.get("remoteci") or {}
            rc_name = rc.get("name", "unknown") if isinstance(rc, dict) else str(rc)
            date_str = job.get("created_at", "")
            if not date_str:
                continue
            week = _week_start(date_str)
            rc_weeks[rc_name][week]["total"] += 1
            if _has_match(job):
                rc_weeks[rc_name][week]["with_log"] += 1

        result = []
        for rc_name in sorted(rc_weeks):
            week_data = rc_weeks[rc_name]
            rc_total = sum(w["total"] for w in week_data.values())
            rc_with = sum(w["with_log"] for w in week_data.values())
            result.append({
                "remoteci": rc_name,
                "total": rc_total,
                "with_log": rc_with,
                "missing": rc_total - rc_with,
                "weeks": [
                    {
                        "week": week,
                        "total": wd["total"],
                        "with_log": wd["with_log"],
                        "missing": wd["total"] - wd["with_log"],
                    }
                    for week, wd in sorted(week_data.items())
                ],
            })
        return result

    def _flatten_aggs(self, aggs: dict) -> list[dict]:
        rows = []
        for agg_name, agg_data in aggs.items():
            if "buckets" in agg_data:
                for bucket in agg_data["buckets"]:
                    rows.append({"key": bucket.get("key"), "count": bucket.get("doc_count")})
            elif "value" in agg_data:
                rows.append({"key": agg_name, "value": agg_data["value"]})
        return rows

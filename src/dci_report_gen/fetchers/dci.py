from __future__ import annotations

import re
import sys

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

        params = {"query": source.query, "limit": source.limit, "sort": source.sort}
        if fields:
            params["fields"] = ",".join(fields)
        if source.aggs:
            import json

            params["aggs"] = json.dumps(source.aggs)

        resp = dci_job.search(ctx, **params)
        if resp.status_code != 200:
            raise RuntimeError(f"DCI search failed ({resp.status_code}): {resp.text}")

        data = resp.json()

        if source.aggs and "aggregations" in data:
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

    def _flatten_aggs(self, aggs: dict) -> list[dict]:
        rows = []
        for agg_name, agg_data in aggs.items():
            if "buckets" in agg_data:
                for bucket in agg_data["buckets"]:
                    rows.append({"key": bucket.get("key"), "count": bucket.get("doc_count")})
            elif "value" in agg_data:
                rows.append({"key": agg_name, "value": agg_data["value"]})
        return rows

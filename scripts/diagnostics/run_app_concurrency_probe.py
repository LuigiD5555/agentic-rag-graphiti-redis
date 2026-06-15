#!/usr/bin/env python3
"""Run app-level concurrency probe: ingestion + staggered queries."""

import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AppRecord:
    timestamp_iso: str
    request_id: str
    operation: str
    endpoint: str
    start_ts: float
    end_ts: float
    duration_ms: float
    status_code: int | None
    ok: bool
    error: str | None
    response_excerpt: dict[str, Any]


def post_json(session: requests.Session, endpoint: str, payload: dict[str, Any], request_id: str, timeout: int) -> AppRecord:
    headers = {"X-Request-ID": request_id}
    start_ts = time.perf_counter()
    status = None
    ok = False
    err = None
    excerpt: dict[str, Any] = {}
    try:
        resp = session.post(endpoint, json=payload, headers=headers, timeout=timeout)
        status = resp.status_code
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        excerpt = {
            "status": data.get("status"),
            "run_id": data.get("run_id"),
            "metadata": data.get("metadata"),
        }
        resp.raise_for_status()
        ok = True
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
    end_ts = time.perf_counter()
    return AppRecord(
        timestamp_iso=now_iso(),
        request_id=request_id,
        operation=payload.get("_operation", "unknown"),
        endpoint=endpoint,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_ms=(end_ts - start_ts) * 1000.0,
        status_code=status,
        ok=ok,
        error=err,
        response_excerpt=excerpt,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ingest-path", required=True)
    parser.add_argument("--query", default="Resume el objetivo del proyecto.")
    parser.add_argument("--query-count", type=int, default=5)
    parser.add_argument("--query-delay", type=float, default=1.5)
    parser.add_argument("--timeout-ingest", type=int, default=1800)
    parser.add_argument("--timeout-query", type=int, default=300)
    parser.add_argument("--output-dir", default="docs/investigations/lmstudio-concurrency/raw-results")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ingest_payload = {
        "paths": [args.ingest_path],
        "dry_run": False,
        "streaming": True,
        "_operation": "ingest",
    }

    query_payload = {
        "query": args.query,
        "top_k": 8,
        "include_sources": True,
        "_operation": "query",
    }

    records: list[AppRecord] = []
    session = requests.Session()

    ingest_endpoint = f"{args.base_url.rstrip('/')}/rag/ingest"
    query_endpoint = f"{args.base_url.rstrip('/')}/rag/query"

    with ThreadPoolExecutor(max_workers=max(2, args.query_count + 1)) as ex:
        ingest_request_id = f"probe-ingest-{uuid.uuid4().hex[:10]}"
        ingest_future = ex.submit(
            post_json,
            session,
            ingest_endpoint,
            ingest_payload,
            ingest_request_id,
            args.timeout_ingest,
        )

        time.sleep(args.query_delay)

        query_futures = []
        for i in range(args.query_count):
            qid = f"probe-query-{i + 1}-{uuid.uuid4().hex[:8]}"
            query_futures.append(
                ex.submit(
                    post_json,
                    session,
                    query_endpoint,
                    query_payload,
                    qid,
                    args.timeout_query,
                )
            )
            time.sleep(args.query_delay)

        for fut in query_futures:
            records.append(fut.result())
        records.append(ingest_future.result())

    ingest_records = [record for record in records if record.operation == "ingest"]
    query_records = [record for record in records if record.operation == "query"]
    overlap_count = 0
    for ingest_record in ingest_records:
        for query_record in query_records:
            if max(ingest_record.start_ts, query_record.start_ts) < min(ingest_record.end_ts, query_record.end_ts):
                overlap_count += 1

    summary = {
        "timestamp_iso": now_iso(),
        "ingest_records": len(ingest_records),
        "query_records": len(query_records),
        "query_ok": sum(1 for record in query_records if record.ok),
        "ingest_ok": sum(1 for record in ingest_records if record.ok),
        "overlap_pairs": overlap_count,
        "query_durations_ms": [round(record.duration_ms, 3) for record in query_records],
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rec_path = output_dir / f"app_probe_{stamp}.jsonl"
    sum_path = output_dir / f"app_probe_summary_{stamp}.json"
    with rec_path.open("w", encoding="utf-8") as records_file:
        for rec in records:
            records_file.write(json.dumps(asdict(rec), ensure_ascii=True) + "\n")
    sum_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Wrote records: {rec_path}")
    print(f"Wrote summary: {sum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

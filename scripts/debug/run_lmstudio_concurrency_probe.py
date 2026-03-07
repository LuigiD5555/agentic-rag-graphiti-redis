#!/usr/bin/env python3
"""Run direct LM Studio concurrency probes (embed/chat + ttl scenarios)."""

import argparse
import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProbeRecord:
    timestamp_iso: str
    scenario: str
    request_id: str
    operation: str
    model_name: str
    endpoint: str
    start_ts: float
    end_ts: float
    duration_ms: float
    status_code: int | None
    ok: bool
    error: str | None
    extra: dict[str, Any]


class LMStudioProbe:
    def __init__(self, base_url: str, chat_model: str, embed_model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.timeout = timeout
        self.session = requests.Session()

    def _post(self, endpoint: str, payload: dict[str, Any], scenario: str, operation: str, model: str) -> ProbeRecord:
        request_id = f"probe-{uuid.uuid4().hex[:12]}"
        start_ts = time.perf_counter()
        status = None
        err = None
        ok = False
        try:
            resp = self.session.post(endpoint, json=payload, timeout=self.timeout)
            status = resp.status_code
            resp.raise_for_status()
            ok = True
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        end_ts = time.perf_counter()
        return ProbeRecord(
            timestamp_iso=now_iso(),
            scenario=scenario,
            request_id=request_id,
            operation=operation,
            model_name=model,
            endpoint=endpoint,
            start_ts=start_ts,
            end_ts=end_ts,
            duration_ms=(end_ts - start_ts) * 1000.0,
            status_code=status,
            ok=ok,
            error=err,
            extra={"payload_keys": sorted(payload.keys())},
        )

    def embed_once(self, text: str, scenario: str, ttl: int | None = None) -> ProbeRecord:
        payload: dict[str, Any] = {"model": self.embed_model, "input": text}
        if ttl is not None:
            payload["ttl"] = ttl
        return self._post(
            endpoint=f"{self.base_url}/embeddings",
            payload=payload,
            scenario=scenario,
            operation="embedding",
            model=self.embed_model,
        )

    def chat_once(self, prompt: str, scenario: str, ttl: int | None = None) -> ProbeRecord:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 128,
            "temperature": 0.0,
        }
        if ttl is not None:
            payload["ttl"] = ttl
        return self._post(
            endpoint=f"{self.base_url}/chat/completions",
            payload=payload,
            scenario=scenario,
            operation="chat",
            model=self.chat_model,
        )


def run_lms_cmd(args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "lms command not found"
    out = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, out.strip()


def run_batch(tasks: list[tuple[str, Any]]) -> list[ProbeRecord]:
    results: list[ProbeRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as ex:
        futures = [ex.submit(fn, *args) for fn, fn_args in tasks for args in [fn_args]]
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


def overlap_summary(records: list[ProbeRecord]) -> dict[str, Any]:
    embeds = [r for r in records if r.operation == "embedding"]
    chats = [r for r in records if r.operation == "chat"]
    overlap_pairs = 0
    for e in embeds:
        for c in chats:
            if max(e.start_ts, c.start_ts) < min(e.end_ts, c.end_ts):
                overlap_pairs += 1
    return {
        "embedding_count": len(embeds),
        "chat_count": len(chats),
        "overlap_pairs": overlap_pairs,
        "embedding_ok": sum(1 for r in embeds if r.ok),
        "chat_ok": sum(1 for r in chats if r.ok),
    }


def write_records(path: Path, records: list[ProbeRecord]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(asdict(rec), ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
    parser.add_argument("--chat-model", required=True)
    parser.add_argument("--embed-model", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output-dir", default="docs/investigations/lmstudio-concurrency/raw-results")
    parser.add_argument("--prompt", default="Explain concurrency in one sentence.")
    parser.add_argument("--text", default="Concurrency probe text for embeddings.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probe = LMStudioProbe(args.base_url, args.chat_model, args.embed_model)
    all_records: list[ProbeRecord] = []
    summary: dict[str, Any] = {"timestamp_iso": now_iso(), "base_url": args.base_url}

    ok_ps, ps_before = run_lms_cmd(["lms", "ps"])
    summary["lms_ps_before"] = {"ok": ok_ps, "output": ps_before}

    # Scenario 1: embeddings only
    scenario = "scenario_1_embeddings_only"
    tasks = [(probe.embed_once, (f"{args.text} #{i}", scenario, None)) for i in range(args.concurrency)]
    recs = run_batch(tasks)
    all_records.extend(recs)
    summary[scenario] = overlap_summary(recs)

    # Scenario 2: chat only
    scenario = "scenario_2_chat_only"
    tasks = [(probe.chat_once, (f"{args.prompt} #{i}", scenario, None)) for i in range(args.concurrency)]
    recs = run_batch(tasks)
    all_records.extend(recs)
    summary[scenario] = overlap_summary(recs)

    # Scenario 3: preload models + mixed
    scenario = "scenario_3_preloaded_mixed"
    ok_load_embed, load_embed_out = run_lms_cmd(["lms", "load", args.embed_model])
    ok_load_chat, load_chat_out = run_lms_cmd(["lms", "load", args.chat_model])
    summary["preload"] = {
        "embed_ok": ok_load_embed,
        "embed_output": load_embed_out,
        "chat_ok": ok_load_chat,
        "chat_output": load_chat_out,
    }
    tasks = []
    for i in range(args.concurrency):
        tasks.append((probe.embed_once, (f"{args.text} preloaded #{i}", scenario, None)))
        tasks.append((probe.chat_once, (f"{args.prompt} preloaded #{i}", scenario, None)))
    recs = run_batch(tasks)
    all_records.extend(recs)
    summary[scenario] = overlap_summary(recs)

    # Scenario 4: JIT mixed (include ttl none)
    scenario = "scenario_4_jit_mixed"
    tasks = []
    for i in range(args.concurrency):
        tasks.append((probe.embed_once, (f"{args.text} jit #{i}", scenario, None)))
        tasks.append((probe.chat_once, (f"{args.prompt} jit #{i}", scenario, None)))
    recs = run_batch(tasks)
    all_records.extend(recs)
    summary[scenario] = overlap_summary(recs)

    # TTL sweep
    ttl_results: list[dict[str, Any]] = []
    for ttl in [None, 300, 3600]:
        scenario = f"ttl_{ttl if ttl is not None else 'none'}"
        e = probe.embed_once(f"{args.text} ttl={ttl}", scenario, ttl=ttl)
        c = probe.chat_once(f"{args.prompt} ttl={ttl}", scenario, ttl=ttl)
        all_records.extend([e, c])
        ok_ps, ps_out = run_lms_cmd(["lms", "ps"])
        ttl_results.append({
            "ttl": ttl,
            "embed_ok": e.ok,
            "chat_ok": c.ok,
            "lms_ps_ok": ok_ps,
            "lms_ps": ps_out,
        })
    summary["ttl_sweep"] = ttl_results

    ok_ps, ps_after = run_lms_cmd(["lms", "ps"])
    summary["lms_ps_after"] = {"ok": ok_ps, "output": ps_after}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    records_path = output_dir / f"lmstudio_probe_{stamp}.jsonl"
    summary_path = output_dir / f"lmstudio_probe_summary_{stamp}.json"
    write_records(records_path, all_records)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Wrote records: {records_path}")
    print(f"Wrote summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

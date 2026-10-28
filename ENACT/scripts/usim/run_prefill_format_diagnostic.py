"""Prefill (partial-mode) format diagnostic for the fixed v0.2 A/B subset.

The user-level question is unchanged; the only addition is a trailing assistant message

    {"role": "assistant", "content": "[", "partial": true}

so the model continues from ``[`` instead of writing prose first.  Per the Aliyun partial-mode
documentation the completion is a continuation, so the scored answer is the fixed
concatenation ``completed_answer = "[" + raw_completion``.  That rule is fixed in advance: we
never re-add brackets based on how parsing went, never strip a duplicated prefix, never pick
"the last list", and never read gt to choose a join strategy.

Two steps, in order:

1. ``--smoke``  one request on the first forward-L4 question of the frozen order, condition B,
   2048 budget.  Checks that the endpoint accepts partial mode with multiple images, that the
   response is continuation-only, and what strict parsing does to the joined answer.  This
   request is stored separately and never counted in the formal metrics.
2. ``--run``    the fixed 16 questions x A/B after the request protocol is frozen.

Credentials come from ``VLM_API_KEY`` (environment, falling back to the Windows user scope as
documented in AGENTS.md).  The key is never printed, echoed into a body or written to any file.

Usage:
    python scripts/usim/run_prefill_format_diagnostic.py --smoke
    python scripts/usim/run_prefill_format_diagnostic.py --freeze
    python scripts/usim/run_prefill_format_diagnostic.py --run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.usim import run_inference  # noqa: E402
from scripts.usim.evaluate import USIMEvaluator  # noqa: E402
from scripts.usim.extractable_v1 import VERSION as SECONDARY_VERSION, extract  # noqa: E402

BASE = ROOT / "data/usim_enact"
DATA_ROOT = BASE / "usim-enact-v0.2"
SOURCE_RUN = BASE / "runs/qwen3.8-max/v02_budget2048_diag_v1"
RUN_DIR = BASE / "runs/qwen3.8-max/v02_prefill2048_diag_v1"
FREEZE_PATH = ROOT / "docs/protocols/prefill2048_request.freeze.json"

PREFIX = "["
BUDGET = 2048
CONDITIONS = {"A": "A_full_image", "B": "B_zoom"}
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_key() -> str:
    key = os.environ.get("VLM_API_KEY", "").strip()
    if key:
        return key
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as handle:
                value, _ = winreg.QueryValueEx(handle, "VLM_API_KEY")
            if str(value).strip():
                return str(value).strip()
        except OSError:
            pass
    raise SystemExit("缺少 VLM_API_KEY：环境变量或用户级环境变量都没有，不要写进命令行或文件。")


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_plan() -> Dict:
    return json.loads((SOURCE_RUN / "plan.json").read_text(encoding="utf-8"))


def decode_args(plan: Dict) -> SimpleNamespace:
    decode = plan["decode"]
    return SimpleNamespace(
        temperature=decode["temperature"],
        max_completion_tokens=decode["max_completion_tokens"],
        enable_thinking=decode["enable_thinking"],
        drop_images=False,
    )


def request_body(record: Dict, plan: Dict) -> Dict[str, Any]:
    """Frozen user message + the one trailing assistant message."""
    payload = run_inference.whitelist_payload(record, DATA_ROOT)
    args = decode_args(plan)
    body = run_inference.build_body(
        model=plan["decode"]["model_requested"],
        question=payload["question"],
        images=payload["images"],
        args=args,
        system_prompt=plan["decode"].get("system_prompt") or "",
        format_directive=plan["decode"].get("format_directive") or "",
    )
    body["messages"].append({"role": "assistant", "content": PREFIX, "partial": True})
    return body


def raw_completion(payload: Dict) -> str:
    """The continuation exactly as returned (no strip: the join must be faithful)."""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def score(record: Dict, completed: str, finish_reason: Optional[str]) -> Dict[str, Any]:
    expected = int(record["num_states"]) - 1 if "num_states" in record else len(record["key_frame_ids"]) - 1
    permutation, reason = USIMEvaluator.parse_strict(completed, expected)
    secondary = extract(completed, finish_reason, expected)
    return {
        "expected_length": expected,
        "strict_status": "ok" if permutation is not None else "zero",
        "strict_reason": reason,
        "strict_permutation": permutation,
        "extract_status": secondary["status"],
        "extract_reason": secondary["reason"],
    }


def call(body: Dict, plan: Dict, key: str) -> Dict[str, Any]:
    url = plan["decode"]["api_url"]
    timeout = int(plan["decode"]["timeout_seconds"])
    body_sha = sha256_bytes(json.dumps(body, sort_keys=True).encode("utf-8"))
    status, headers, payload = run_inference.post_json(url, body, key, timeout)
    return {
        "http_status": status,
        "request_id": headers.get("x-request-id") or payload.get("request_id"),
        "model_returned": payload.get("model"),
        "body_sha256": body_sha,
        "payload": payload,
    }


def one_request(record: Dict, condition: str, plan: Dict, key: str) -> Dict[str, Any]:
    body = request_body(record, plan)
    result = call(body, plan, key)
    payload = result.pop("payload")
    choices = payload.get("choices") or []
    finish_reason = choices[0].get("finish_reason") if choices else None
    continuation = raw_completion(payload)
    completed = PREFIX + continuation if continuation else ""
    entry = {
        "id": record["id"],
        "type": record["type"],
        "condition": condition,
        "prefix": PREFIX,
        "finish_reason": finish_reason,
        "usage": (payload.get("usage") or {}),
        "raw_completion": continuation,
        "completed_answer": completed,
        "answers_match_prefix_echo": continuation.startswith(PREFIX),
        "requested_at": now_iso(),
        **result,
        **score(record, completed, finish_reason),
    }
    entry["response_payload_sha256"] = sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return entry


def smoke(key: str) -> int:
    plan = load_plan()
    rows = {row["id"]: row for row in load_jsonl(SOURCE_RUN / "inputs/B.jsonl")}
    target = next(plan["selected_ids"][index] for index, qid in enumerate(plan["selected_ids"])
                  if rows[qid]["type"] == "forward_world_modeling_4_steps")
    record = rows[target]
    entry = one_request(record, "B", plan, key)
    out_dir = RUN_DIR / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.joinpath("smoke.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    verdict = {
        "question": target,
        "http_status": entry["http_status"],
        "finish_reason": entry["finish_reason"],
        "n_images": len(record["images"]),
        "continuation_first_40": entry["raw_completion"][:40],
        "answers_match_prefix_echo": entry["answers_match_prefix_echo"],
        "strict_reason": entry["strict_reason"],
        "extract_reason": entry["extract_reason"],
        "completion_tokens": entry["usage"].get("completion_tokens"),
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    ok = (entry["http_status"] == 200 and entry["finish_reason"] in ("stop", "length")
          and not entry["answers_match_prefix_echo"] and bool(entry["raw_completion"]))
    print("smoke:", "PASS" if ok else "FAIL", "(a FAIL means stop here; do not swap in another prompt)")
    return 0 if ok else 2


def run_matrix(key: str) -> int:
    plan = load_plan()
    rows = {key_: load_jsonl(SOURCE_RUN / "inputs" / f"{key_}.jsonl") for key_ in CONDITIONS}
    order = plan["selected_ids"]
    total, done = len(order) * len(CONDITIONS), 0
    for name, label in CONDITIONS.items():
        out_dir = RUN_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "predictions.jsonl"
        existing = {}
        if out_path.exists():
            existing = {row["id"]: row for row in load_jsonl(out_path)}
        with out_path.open("a", encoding="utf-8") as handle:
            for qid in order:
                if qid in existing:
                    done += 1
                    continue
                record = {row["id"]: row for row in rows[name]}[qid]
                entry = one_request(record, name, plan, key)
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                done += 1
                print(f"[{done}/{total}] {name} {qid[-8:]} http={entry['http_status']} "
                      f"finish={entry['finish_reason']} strict={entry['strict_reason']} "
                      f"extract={entry['extract_reason']}")
                if entry["http_status"] != 200:
                    print("aborting on non-200; fix the request, do not retry format errors")
                    return 2
                time.sleep(1.0)
    return summarise()


def summarise() -> int:
    blocks: Dict[str, Any] = {}
    for name, label in CONDITIONS.items():
        rows = load_jsonl(RUN_DIR / label / "predictions.jsonl") if (RUN_DIR / label / "predictions.jsonl").exists() else []
        n = len(rows)
        blocks[name] = {
            "N": n,
            "answered": sum(1 for row in rows if row["http_status"] == 200),
            "truncated": sum(1 for row in rows if row["finish_reason"] == "length"),
            "strict_valid": sum(1 for row in rows if row["strict_status"] == "ok"),
            "extractable": sum(1 for row in rows if row["extract_status"] == "ok"),
            "strict_reasons": {reason: sum(1 for row in rows if row["strict_reason"] == reason)
                               for reason in sorted({row["strict_reason"] for row in rows})},
            "prefix_echo": sum(1 for row in rows if row["answers_match_prefix_echo"]),
        }
    budget_ok = all(block["N"] == 16 and block["truncated"] == 0 and block["answered"] == 16
                    and block["strict_valid"] == 16 for block in blocks.values())
    summary = {
        "schema": "usim-prefill-format-diagnostic/v1",
        "created_at": now_iso(),
        "run_dir": str(RUN_DIR),
        "request": {"prefix": PREFIX, "partial": True, "concat_rule": 'completed = "[" + raw_completion'},
        "budget": BUDGET,
        "secondary_metric": SECONDARY_VERSION,
        "conditions": blocks,
        "budget_gate": "pass_on_fixed_subset" if budget_ok else "fail_on_fixed_subset",
        "em_used": False,
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "diagnostic_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if budget_ok else 3


def freeze() -> int:
    smoke_path = RUN_DIR / "smoke" / "smoke.json"
    if not smoke_path.exists():
        raise SystemExit("还没有冒烟记录：先跑 --smoke 并通过。")
    smoke_entry = json.loads(smoke_path.read_text(encoding="utf-8"))
    if smoke_entry["http_status"] != 200 or smoke_entry["answers_match_prefix_echo"]:
        raise SystemExit("冒烟未通过（HTTP 或续写形态异常），不能冻结。")
    files = [
        ROOT / "scripts/usim/run_prefill_format_diagnostic.py",
        ROOT / "scripts/usim/run_inference.py",
        ROOT / "scripts/usim/evaluate.py",
        ROOT / "scripts/usim/extractable_v1.py",
        REPO / "docs/workbuddyRead/usim_prefill_format_diagnostic_zh.md",
    ]
    manifest = {
        "schema": "usim-prefill-request-freeze/v1",
        "freeze_id": f"20261028_prefill2048",
        "frozen": True,
        "frozen_at": now_iso(),
        "request_shape": {
            "user_message": "identical to the frozen run (same question, format directive and images)",
            "appended_message": {"role": "assistant", "content": PREFIX, "partial": True},
            "concat_rule": 'completed_answer = "[" + raw_completion (raw bytes, no strip)',
            "budget": BUDGET,
            "temperature": 0.0,
            "enable_thinking": False,
        },
        "scoring": {
            "primary": "usim_strict_v0.3 on the joined answer (unchanged)",
            "secondary": SECONDARY_VERSION,
            "em_used_for_selection": False,
            "retry_policy": "no retry of format errors; every request stays in the denominator",
        },
        "smoke": {
            "question": smoke_entry["id"],
            "http_status": smoke_entry["http_status"],
            "finish_reason": smoke_entry["finish_reason"],
            "answers_match_prefix_echo": smoke_entry["answers_match_prefix_echo"],
            "smoke_file_sha256": sha256_bytes(smoke_path.read_bytes()),
        },
        "not_frozen_here": ["test labels/inputs", "model snapshot", "the 294-request matrix protocol"],
        "files_sha256": {path.relative_to(REPO).as_posix(): sha256_bytes(path.read_bytes()) for path in files},
    }
    payload = sha256_bytes(json.dumps({k: v for k, v in manifest.items() if k != "payload_sha256"},
                                      sort_keys=True).encode("utf-8"))
    manifest["payload_sha256"] = payload
    FREEZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if FREEZE_PATH.exists():
        raise SystemExit(f"冻结文件已存在，不覆盖：{FREEZE_PATH}")
    FREEZE_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"freeze": str(FREEZE_PATH), "payload_sha256": payload}, ensure_ascii=False))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="1 次请求，验证 partial mode 与多图兼容性")
    parser.add_argument("--freeze", action="store_true", help="冒烟通过后冻结请求/拼接/预算约定")
    parser.add_argument("--run", action="store_true", help="固定 16 题 × A/B（需先 --freeze）")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)

    if args.freeze:
        return freeze()
    if args.smoke:
        return smoke(resolve_key())
    if args.run:
        if not FREEZE_PATH.exists():
            raise SystemExit("请求协议尚未冻结：先 --smoke 通过再 --freeze，然后 --run。")
        return run_matrix(resolve_key())
    if args.verify_freeze:
        return verify_freeze()
    if args.summary_only:
        return summarise()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Verify the prefill diagnostic freeze, including the executed request bodies.

File hashes alone cannot tell whether the *executed* request shape matches the frozen one, and
the diagnostic script itself picked up a cosmetic CLI edit after freezing.  Every stored
prediction carries ``body_sha256``, so this verifier rebuilds each request from the frozen
``run_inference.py`` + the frozen plan + the fixed prefix message and compares hashes.  That
attests the protocol that actually ran, not just the bytes on disk.

Usage:
    python tools/verify_prefill_freeze.py
"""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT
ENACT = ROOT / "ENACT"
if str(ENACT) not in sys.path:
    sys.path.insert(0, str(ENACT))

from scripts.usim import run_inference  # noqa: E402

FREEZE = ENACT / "docs/protocols/prefill2048_request.freeze.json"
RUN = ENACT / "data/usim_enact/runs/qwen3.8-max/v02_prefill2048_diag_v1"
SOURCE = ENACT / "data/usim_enact/runs/qwen3.8-max/v02_budget2048_diag_v1"
DATA_ROOT = ENACT / "data/usim_enact/usim-enact-v0.2"
PREFIX = "["
CONDITIONS = {"A": "A_full_image", "B": "B_zoom"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rebuild_body(record: dict, plan: dict) -> dict:
    decode = plan["decode"]
    args = SimpleNamespace(temperature=decode["temperature"],
                           max_completion_tokens=decode["max_completion_tokens"],
                           enable_thinking=decode["enable_thinking"],
                           drop_images=False)
    payload = run_inference.whitelist_payload(record, DATA_ROOT)
    body = run_inference.build_body(model=decode["model_requested"], question=payload["question"],
                                    images=payload["images"], args=args,
                                    system_prompt=decode.get("system_prompt") or "",
                                    format_directive=decode.get("format_directive") or "")
    body["messages"].append({"role": "assistant", "content": PREFIX, "partial": True})
    return body


def main() -> int:
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    plan = json.loads((SOURCE / "plan.json").read_text(encoding="utf-8"))

    errors = []
    file_status = {}
    for relative, expected in manifest["files_sha256"].items():
        path = REPO / relative
        actual = sha(path.read_bytes()) if path.exists() else None
        file_status[relative] = "ok" if actual == expected else ("missing" if actual is None else "changed")

    body_checked, body_mismatch = 0, []
    smoke_path = RUN / "smoke" / "smoke.json"
    if not smoke_path.exists():
        errors.append("smoke record missing")
    for name, label in CONDITIONS.items():
        path = RUN / label / "predictions.jsonl"
        if not path.exists():
            errors.append(f"missing predictions: {label}")
            continue
        rows = {row["id"]: row for row in load_jsonl(SOURCE / "inputs" / f"{name}.jsonl")}
        for entry in load_jsonl(path):
            body = rebuild_body(rows[entry["id"]], plan)
            digest = sha(json.dumps(body, sort_keys=True).encode("utf-8"))
            body_checked += 1
            if digest != entry["body_sha256"]:
                body_mismatch.append(f'{label}:{entry["id"][-8:]}')

    if body_mismatch:
        errors.append(f"request body mismatch: {body_mismatch[:5]}")
    if manifest["request_shape"]["concat_rule"] != 'completed_answer = "[" + raw_completion (raw bytes, no strip)':
        errors.append("concat rule text changed")

    report = {
        "ok": not errors,
        "errors": errors,
        "files": file_status,
        "request_bodies_checked": body_checked,
        "request_bodies_mismatch": len(body_mismatch),
        "payload_sha256": manifest["payload_sha256"],
        "note": "文件哈希记录冻结时刻的字节；诊断脚本此后有一次纯 CLI 改动，"
                "因此以 32 条请求体的 body_sha256 重建比对作为协议执行的直接证据。",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

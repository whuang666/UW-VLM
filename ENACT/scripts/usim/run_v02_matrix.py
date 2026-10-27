"""Drive the whole v0.2 A/B/C/D condition matrix from one source version.

Why this exists: the v0.1 development matrix was produced by three different
``run_inference.py`` versions, which makes the A/B/C comparison unfalsifiable (P1 in
the v0.2 build report).  This driver pins one source version, one decode
configuration and one question set per condition, runs them in a fixed order, then
scores each one, and writes a manifest that records the exact hashes so the "same
version" claim is checkable instead of asserted.

Conditions (dev split only -- val is never reported before the final test run):

* ``A_full_image``      ego full frame, dev.jsonl
* ``B_zoom``            [full | 2x zoom] composites, dev_B.jsonl
* ``C_text_only``       same questions with ``--drop-images``, dev.jsonl
* ``D_no_action_text``  forward questions with the action list removed, filtered to
                        the dev episodes (42 of 60)

Derived inputs go to ``_protocol/derived/`` on purpose: ``<run>/inputs/`` is inside
the frozen ``inputs`` group glob, so adding files there would break ``--verify`` on
the existing freeze.

The API key is read from ``VLM_API_KEY`` by ``run_inference.py`` itself.  This driver
never reads, echoes or writes it; it only records ``api_key_present``.

Usage:
    python scripts/usim/run_v02_matrix.py --dry-run          # validate inputs only
    python scripts/usim/run_v02_matrix.py --conditions A,B   # real run, subset
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_ROOT = ROOT / "data" / "usim_enact" / "usim-enact-v0.2"
RUN_DIR = ROOT / "data" / "usim_enact" / "runs" / "qwen3.8-max" / "v02_dev_001"
DERIVED_DIR = ROOT / "data" / "usim_enact" / "_protocol" / "derived"
D_QA = ROOT / "data" / "usim_enact" / "_protocol" / "conditions" / "D_no_action_text_v0.2" / "enact_ordering.jsonl"
TZ = timezone(timedelta(hours=8))

DEFAULT_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3.8-max"

# Same decode configuration for every condition -- changing one of these changes all of them.
DECODE = {
    "enable_thinking": "false",
    "temperature": "0.0",
    "max_completion_tokens": "256",
    "max_attempts": "3",
    "timeout": "180",
    "sleep": "1.0",
}

CONDITIONS: Dict[str, Dict[str, Any]] = {
    "A": {"label": "A_full_image", "qa": "dev.jsonl", "extra": []},
    "B": {"label": "B_zoom", "qa": "dev_B.jsonl", "extra": []},
    "C": {"label": "C_text_only", "qa": "dev.jsonl", "extra": ["--drop-images"]},
    "D": {"label": "D_no_action_text", "qa": None, "extra": []},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_dev_d_qa(inputs_dir: Path) -> Path:
    """Filter the forward-only condition-D QA to the dev episodes (deterministic order)."""
    manifest = json.loads((inputs_dir / "splits_manifest.json").read_text(encoding="utf-8"))
    dev_episodes = set(manifest["splits"]["dev"]["episodes"])
    records = [record for record in load_jsonl(D_QA) if record["task_name"] in dev_episodes]
    records.sort(key=lambda record: record["id"])
    out = DERIVED_DIR / "dev_D_forward.jsonl"
    write_jsonl(out, records)
    return out


def run(cmd: List[str], dry_run: bool) -> int:
    shown = " ".join(str(part) for part in cmd)
    print(("  [dry-run] " if dry_run else "  [run] ") + shown, flush=True)
    if dry_run:
        return 0
    completed = subprocess.run(cmd, cwd=str(ROOT))
    return completed.returncode


def public_view(info: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the internal ID set and stringify paths so the record is JSON-safe."""
    view = {key: value for key, value in info.items() if key != "ids"}
    view["qa_path"] = str(view["qa_path"])
    return view


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DATA_ROOT))
    parser.add_argument("--run-dir", default=str(RUN_DIR))
    parser.add_argument("--conditions", default="A,B,C,D")
    parser.add_argument("--api-url", default=os.environ.get("VLM_API_URL", DEFAULT_API_URL))
    parser.add_argument("--model", default=os.environ.get("VLM_MODEL_NAME", DEFAULT_MODEL))
    parser.add_argument("--limit", type=int, default=0, help="only the first N questions per condition")
    parser.add_argument("--sleep", default=DECODE["sleep"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--new-run", action="store_true")
    parser.add_argument("--skip-score", action="store_true")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root).resolve()
    run_dir = Path(args.run_dir).resolve()
    inputs_dir = run_dir / "inputs"
    python = sys.executable

    selected = [name.strip().upper() for name in args.conditions.split(",") if name.strip()]
    unknown = [name for name in selected if name not in CONDITIONS]
    if unknown:
        raise SystemExit(f"未知条件：{unknown}；可选 {sorted(CONDITIONS)}")

    key_present = bool(os.environ.get("VLM_API_KEY", "").strip())
    if not args.dry_run and not key_present:
        raise SystemExit(
            "缺少 VLM_API_KEY：只有环境变量方式（不要写进命令行或文件）。\n"
            "  PowerShell:  $env:VLM_API_KEY='<your-key>'\n"
            "  然后重跑本脚本；或先用 --dry-run 校验输入。"
        )

    runner = ROOT / "scripts" / "usim" / "run_inference.py"
    evaluator = ROOT / "scripts" / "usim" / "evaluate.py"
    source = {
        "run_inference.py": sha256_file(runner),
        "evaluate.py": sha256_file(evaluator),
    }

    # one question set per condition, resolved before any request is sent
    dev_d_qa = build_dev_d_qa(inputs_dir)
    resolved: Dict[str, Dict[str, Any]] = {}
    for name in selected:
        spec = dict(CONDITIONS[name])
        qa_path = dev_d_qa if spec["qa"] is None else (inputs_dir / spec["qa"])
        if not qa_path.exists():
            raise SystemExit(f"条件 {name} 的题集不存在：{qa_path}")
        records = load_jsonl(qa_path)
        resolved[name] = {
            "label": spec["label"],
            "qa_path": qa_path,
            "extra": spec["extra"],
            "questions": len(records),
            "qa_sha256": sha256_file(qa_path),
            "ids": {record["id"] for record in records},
            "by_type": {task_type: sum(1 for record in records if record["type"] == task_type)
                        for task_type in sorted({record["type"] for record in records})},
        }

    print(json.dumps({name: public_view(info) for name, info in resolved.items()},
                     indent=2, ensure_ascii=False), flush=True)

    failures: Dict[str, int] = {}
    for name in selected:
        info = resolved[name]
        condition_dir = run_dir / info["label"]
        condition_dir.mkdir(parents=True, exist_ok=True)
        if args.new_run and (condition_dir / "predictions.jsonl").exists():
            (condition_dir / "predictions.jsonl").unlink()

        cmd = [
            python, str(runner),
            "--backend", "openai",
            "--data-root", str(data_root),
            "--qa", str(info["qa_path"]),
            "--out", str(condition_dir / "predictions.jsonl"),
            "--api-url", args.api_url,
            "--model", args.model,
            "--condition-label", info["label"],
            "--enable-thinking", DECODE["enable_thinking"],
            "--temperature", DECODE["temperature"],
            "--max-completion-tokens", DECODE["max_completion_tokens"],
            "--max-attempts", DECODE["max_attempts"],
            "--timeout", DECODE["timeout"],
            "--sleep", str(args.sleep),
        ] + info["extra"]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.new_run:
            cmd.append("--new-run")

        print(f"\n=== condition {name} ({info['label']}) : {info['questions']} questions ===", flush=True)
        if args.dry_run:
            env_backup = os.environ.get("VLM_API_KEY")
            os.environ["VLM_API_KEY"] = "dry-run-placeholder"
            try:
                code = run(cmd, dry_run=False)
            finally:
                if env_backup is None:
                    os.environ.pop("VLM_API_KEY", None)
                else:
                    os.environ["VLM_API_KEY"] = env_backup
        else:
            code = run(cmd, dry_run=False)
        if code not in (0, 3):  # 3 = completed_with_failures, still scoreable
            failures[name] = code
            print(f"  condition {name} aborted with exit code {code}; stopping the matrix", flush=True)
            break

        if not args.skip_score and not args.dry_run:
            score_cmd = [
                python, str(evaluator),
                "--data-root", str(data_root),
                "--qa", str(info["qa_path"]),
                "--predictions", str(condition_dir / "predictions.jsonl"),
                "--out", str(condition_dir / "report.json"),
            ]
            if run(score_cmd, dry_run=False) != 0:
                failures[name] = failures.get(name, 0) or 1

    summary = {
        "schema": "usim-v02-matrix/1",
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "model_requested": args.model,
        "api_url": args.api_url,
        "source_sha256": source,
        "decode": DECODE,
        "conditions": {name: public_view(info) for name, info in resolved.items()},
        "api_key_present": key_present,
        "failures": failures,
    }
    out = DERIVED_DIR / f"matrix_manifest_{'dryrun' if args.dry_run else 'run'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nmanifest: {out}", flush=True)
    if failures:
        print(f"failures: {failures}", flush=True)
        return 1
    print("matrix complete" + (" (dry-run: no request sent)" if args.dry_run else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

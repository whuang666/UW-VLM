"""Prepare or run the fixed v0.2 A/B output-budget diagnostic (16 pairs).

Default: freeze inputs and run offline asset/scoring checks. ``--run`` sends at
most 32 logical requests with a 1024-token output cap. Credentials come only from
VLM_API_KEY. Old runs, frozen inputs and inference/scoring code are never edited.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = ROOT / "data/usim_enact"
DATA_ROOT = BASE / "usim-enact-v0.2"
SOURCE_RUN = BASE / "runs/qwen3.8-max/v02_dev_001"
DEFAULT_RUN = BASE / "runs/qwen3.8-max/v02_budget1024_diag_v1"
FREEZE = BASE / "_protocol/freeze_usim-enact-v0.2_20261027b.json"
SEED = 20261028
STRATA = (("forward", 3, 4), ("forward", 4, 4), ("forward", 5, 2),
          ("inverse", 3, 2), ("inverse", 4, 2), ("inverse", 5, 2))
CONDITIONS = {"A": "A_full_image", "B": "B_zoom"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def index_rows(rows: list[dict]) -> dict[str, dict]:
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate IDs are not allowed")
    return indexed


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def jsonl_bytes(rows: list[dict]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")


def write_once(path: Path, data: bytes) -> None:
    """Refuse input/provenance drift, including after a run has started."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Frozen diagnostic file differs; use a separately versioned plan: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def select_questions(rows: list[dict]) -> list[dict]:
    """Only type, L, episode and ID enter selection; answers/outcomes do not."""
    index_rows(rows)
    selected: list[dict] = []
    episode_counts: Counter = Counter()
    for direction, length, count in STRATA:
        candidates = [row for row in rows
                      if row["type"] == f"{direction}_world_modeling_{length}_steps"
                      and len(row["key_frame_ids"]) == length]
        if len(candidates) < count:
            raise ValueError(f"Insufficient {direction} L={length} candidates")
        for _ in range(count):
            row = min(candidates, key=lambda item: (
                episode_counts[item["task_name"]], digest(f"{SEED}:{item['id']}".encode("utf-8"))))
            candidates.remove(row)
            episode_counts[row["task_name"]] += 1
            selected.append(row)
    return selected


def validate_pairs(a_rows: list[dict], b_rows: list[dict]) -> None:
    a, b = index_rows(a_rows), index_rows(b_rows)
    if set(a) != set(b):
        raise ValueError("A/B ID sets differ")
    for qid, row in a.items():
        other = b[qid]
        for key in ("question", "gt_answer", "key_frame_ids", "task_name", "type", "options"):
            if row.get(key) != other.get(key):
                raise ValueError(f"A/B {key} conflict: {qid}")
        if other.get("source_images") != row["images"]:
            raise ValueError(f"B source image order differs from A: {qid}")


def validate_destination(run_dir: Path) -> None:
    resolved = run_dir.resolve()
    for protected in (SOURCE_RUN, DATA_ROOT, BASE / "_protocol"):
        if resolved == protected.resolve() or protected.resolve() in resolved.parents:
            raise ValueError(f"Diagnostic output overlaps protected evidence: {run_dir}")


def prepare(run_dir: Path) -> dict:
    from scripts.usim.freeze_protocol import verify_manifest

    validate_destination(run_dir)
    verification = verify_manifest(read_json(FREEZE), root_override=ROOT)
    if not verification["ok"]:
        raise ValueError(f"Original protocol freeze failed: {verification['errors'][:5]}")

    configs = {key: read_json(SOURCE_RUN / label / "run_config.json")
               for key, label in CONDITIONS.items()}
    keys = ("model_requested", "api_url", "enable_thinking", "temperature", "max_completion_tokens",
            "stream", "system_prompt", "format_directive", "prompt_policy", "timeout_seconds", "max_attempts")
    original = {key: configs["A"][key] for key in keys}
    if original != {key: configs["B"][key] for key in keys}:
        raise ValueError("Original A/B prompt or decode configuration differs")
    if original["model_requested"] != "qwen3.8-max" or original["max_completion_tokens"] != 256:
        raise ValueError("Unexpected original model/budget")
    for variable, expected in (("VLM_API_URL", original["api_url"]),
                               ("VLM_MODEL_NAME", original["model_requested"])):
        if os.environ.get(variable, "").strip() not in ("", expected):
            raise ValueError(f"{variable} differs from the fixed diagnostic configuration")

    sources: dict[str, str] = {}
    for config in configs.values():
        for relative, expected in config["code_sha256"].items():
            relative = relative.replace("\\", "/")
            actual = digest((ROOT / relative).read_bytes())
            if actual != expected:
                raise ValueError(f"Frozen inference/scoring dependency changed: {relative}")
            sources[relative] = actual
    sources["scripts/usim/run_v02_budget_diagnostic.py"] = digest(Path(__file__).read_bytes())

    all_rows = {}
    source_files = [FREEZE]
    for key, filename in (("A", "dev.jsonl"), ("B", "dev_B.jsonl")):
        qa = SOURCE_RUN / "inputs" / filename
        if digest(qa.read_bytes()) != configs[key]["qa_sha256"]:
            raise ValueError(f"Original QA hash mismatch: {qa}")
        all_rows[key] = load_rows(qa)
        source_files.extend([qa, SOURCE_RUN / CONDITIONS[key] / "run_config.json",
                             SOURCE_RUN / CONDITIONS[key] / "input_manifest.json",
                             SOURCE_RUN / CONDITIONS[key] / "predictions.jsonl"])
    validate_pairs(all_rows["A"], all_rows["B"])
    selected_a = select_questions(all_rows["A"])
    b_lookup = index_rows(all_rows["B"])
    rows = {"A": selected_a, "B": [b_lookup[row["id"]] for row in selected_a]}
    inputs = {key: jsonl_bytes(value) for key, value in rows.items()}

    images = {}
    for key, label in CONDITIONS.items():
        old_manifest = read_json(SOURCE_RUN / label / "input_manifest.json")
        old_images = index_rows(old_manifest["records"])
        images[key] = []
        for row in rows[key]:
            entries = old_images[row["id"]]["images"]
            if [image["path"].replace("\\", "/") for image in entries] != [
                    path.replace("\\", "/") for path in row["images"]]:
                raise ValueError(f"Frozen image order differs: {row['id']}")
            for image in entries:
                path = DATA_ROOT / image["path"].replace("\\", "/")
                if digest(path.read_bytes()) != image["sha256"]:
                    raise ValueError(f"Frozen image changed: {path}")
            images[key].append({"id": row["id"], "images": entries})

    decode = dict(original, max_completion_tokens=1024)
    plan = {
        "schema": "usim-v02-budget-diagnostic/v1", "scope": "dev diagnostic; not val/test",
        "selection_seed": SEED, "selection_rule": "stratum order; fewest previously selected episode questions; SHA256(seed:ID)",
        "selection_uses": ["type", "key_frame_ids length", "task_name", "id"],
        "strata": [{"direction": d, "L": length, "count": n} for d, length, n in STRATA],
        "questions_per_condition": len(selected_a), "logical_requests": 2 * len(selected_a),
        "max_http_attempts": 2 * len(selected_a) * decode["max_attempts"],
        "episodes": sorted({row["task_name"] for row in selected_a}),
        "selected_ids": [row["id"] for row in selected_a],
        "decode": decode, "request_order": "A then B; identical selected ID order",
        "budget_gate": "both conditions complete; zero length stops, missing/failed responses, or strict parser failures; EM excluded",
        "budget_gate_limit": "Passing only supports this small development subset; it does not prove a universal adequate budget.",
        "comparison_limit": "256-token responses are historical; alias snapshot/time drift prevents a clean causal estimate.",
        "source_files_sha256": {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in source_files},
        "source_code_sha256": sources,
        "inputs": {key: {"path": f"inputs/{key}.jsonl", "sha256": digest(inputs[key]),
                          "images": images[key]} for key in CONDITIONS},
    }
    plan["plan_sha256"] = digest(json_bytes(plan))
    # Check every existing immutable file before writing any new one.
    files = {run_dir / "plan.json": json_bytes(plan)}
    files.update({run_dir / "inputs" / f"{key}.jsonl": value for key, value in inputs.items()})
    for path, value in files.items():
        if path.exists() and path.read_bytes() != value:
            raise ValueError(f"Frozen diagnostic file differs: {path}")
    for path, value in files.items():
        write_once(path, value)
    (run_dir / "_preflight").mkdir(parents=True, exist_ok=True)
    (run_dir / "_preflight/freeze_verification.json").write_bytes(json_bytes(verification))
    return plan


def runner_args(run_dir: Path, plan: dict, key: str) -> list[str]:
    decode = plan["decode"]
    args = ["--data-root", str(DATA_ROOT), "--qa", str(run_dir / "inputs" / f"{key}.jsonl"),
            "--out", str(run_dir / CONDITIONS[key] / "predictions.jsonl"), "--api-url", decode["api_url"],
            "--model", decode["model_requested"], "--enable-thinking", str(decode["enable_thinking"]).lower(),
            "--temperature", str(decode["temperature"]), "--max-completion-tokens", "1024",
            "--timeout", str(decode["timeout_seconds"]), "--max-attempts", str(decode["max_attempts"]),
            "--sleep", "1.0", "--condition-label", CONDITIONS[key]]
    if decode["system_prompt"]:
        args.extend(["--system-prompt", decode["system_prompt"]])
    if decode["format_directive"]:
        args.extend(["--format-directive", decode["format_directive"]])
    else:
        args.append("--no-format-directive")
    return args


def checked_process(script: str, args: list[str], *, env: dict | None = None,
                    accepted: tuple = (0,)) -> int:
    result = subprocess.run([sys.executable, str(ROOT / "scripts/usim" / script), *args],
                            cwd=ROOT, env=env, check=False)
    if result.returncode not in accepted:
        raise ValueError(f"{script} exited {result.returncode}")
    return result.returncode


def execution_environment() -> dict[str, str]:
    """Refresh the named user variable when an already-open app has stale env."""
    env = dict(os.environ)
    if not env.get("VLM_API_KEY", "").strip() and os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                value, _ = winreg.QueryValueEx(handle, "VLM_API_KEY")
            if isinstance(value, str) and value.strip():
                env["VLM_API_KEY"] = value
        except FileNotFoundError:
            pass
    return env


def offline_checks(run_dir: Path, plan: dict) -> None:
    from scripts.usim.evaluate import USIMEvaluator
    from scripts.usim import run_inference

    env = dict(os.environ, VLM_API_KEY="offline-dry-run-placeholder")
    for key in CONDITIONS:
        rows = load_rows(run_dir / "inputs" / f"{key}.jsonl")
        USIMEvaluator(DATA_ROOT).precheck(rows)
        # A separate directory keeps preflight sidecars out of the real run.
        args = runner_args(run_dir, plan, key)
        args[args.index("--out") + 1] = str(run_dir / "_preflight" / key / "predictions.jsonl")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/usim/run_inference.py"),
                                 *args, "--dry-run"], cwd=ROOT, env=env, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr.decode("utf-8", errors="replace"))
        (run_dir / "_preflight" / key / "dry_run.txt").write_bytes(result.stdout)
        checked_process("evaluate.py", ["--data-root", str(DATA_ROOT), "--qa", str(run_dir / "inputs" / f"{key}.jsonl"),
                                        "--synthetic", "oracle", "--out", str(run_dir / "_preflight" / key / "oracle.json")])
        # Verify locally that only the frozen prompt and images enter the body.
        for row in rows:
            payload = run_inference.whitelist_payload(row, DATA_ROOT)
            if set(payload) != {"id", "question", "images"}:
                raise ValueError("Unexpected model input fields")
    (run_dir / "_preflight/status.json").write_bytes(json_bytes({
        "state": "offline_checks_passed", "authenticated_api_called": False,
        "dry_run_credential": "placeholder; not an authentication test", "plan_sha256": plan["plan_sha256"],
    }))


def reliability(rows: list[dict], predictions: list[dict]) -> dict:
    from scripts.usim.evaluate import USIMEvaluator

    lookup = index_rows(predictions)
    wanted = {row["id"] for row in rows}
    if set(lookup) - wanted:
        raise ValueError("Predictions contain IDs outside this diagnostic")
    failures: Counter = Counter()
    stops: Counter = Counter()
    valid = 0
    failed = 0
    tokens = []
    for row in rows:
        prediction = lookup.get(row["id"], {})
        stops[str(prediction.get("finish_reason", "missing"))] += 1
        failed += prediction.get("status") == "failed"
        answer = prediction.get("answer") if prediction.get("status") not in ("failed", "invalid") else None
        parsed, reason = USIMEvaluator.parse_strict(answer, len(row["gt_answer"]))
        valid += parsed is not None
        if parsed is None:
            failures[reason] += 1
        usage = prediction.get("usage") or {}
        if isinstance(usage.get("completion_tokens"), int):
            tokens.append(usage["completion_tokens"])
    n = len(rows)
    return {"N": n, "answered": len(lookup), "missing": n - len(lookup), "failed": failed,
            "strict_valid": valid, "strict_valid_rate": valid / n, "invalid_reasons": dict(failures),
            "finish_reasons": dict(stops), "truncated": stops["length"], "truncation_rate": stops["length"] / n,
            "max_completion_tokens_observed": max(tokens) if tokens else None,
            "gate_passed": len(lookup) == n and valid == n and not failed and stops["stop"] == n}


def summarize(run_dir: Path, plan: dict) -> dict:
    summary = {"plan_sha256": plan["plan_sha256"], "historical_256": {}, "diagnostic_1024": {}}
    for key, label in CONDITIONS.items():
        rows = load_rows(run_dir / "inputs" / f"{key}.jsonl")
        wanted = {row["id"] for row in rows}
        old = SOURCE_RUN / label / "predictions.jsonl"
        # Validate all source IDs before restricting to the matched subset.
        old_rows = index_rows(load_rows(old))
        if not wanted <= set(old_rows):
            raise ValueError("Historical predictions do not cover the fixed subset")
        summary["historical_256"][key] = reliability(rows, [old_rows[row["id"]] for row in rows])
        summary.setdefault("historical_predictions_sha256", {})[key] = digest(old.read_bytes())
        current = run_dir / label / "predictions.jsonl"
        summary["diagnostic_1024"][key] = reliability(rows, load_rows(current) if current.exists() else [])
    complete = all(block["answered"] == block["N"] for block in summary["diagnostic_1024"].values())
    summary["state"] = "complete" if complete else "not_run_or_incomplete"
    summary["budget_gate"] = ("pass_on_fixed_subset" if all(block["gate_passed"] for block in summary["diagnostic_1024"].values())
                              else "fail_on_fixed_subset") if complete else "pending"
    summary["limitations"] = [plan["comparison_limit"], plan["budget_gate_limit"], "No EM-based budget selection; no final test result."]
    (run_dir / "diagnostic_summary.json").write_bytes(json_bytes(summary))
    return summary


def run_real(run_dir: Path, plan: dict, resume: bool) -> None:
    env = execution_environment()
    if not env.get("VLM_API_KEY", "").strip():
        raise ValueError("VLM_API_KEY is absent in this process; prepared inputs are ready, no API request was sent")
    for label in CONDITIONS.values():
        path = run_dir / label / "predictions.jsonl"
        if path.exists():
            if not resume:
                raise ValueError("Predictions already exist; use --resume for unattempted IDs only")
            wanted = set(plan["selected_ids"])
            existing = index_rows(load_rows(path))
            if set(existing) - wanted:
                raise ValueError("Existing predictions include unknown IDs")
            if any(row.get("status") not in ("success", "truncated", "invalid", "failed")
                   for row in existing.values()):
                raise ValueError("Existing predictions include nonterminal/corrupt rows")
    for key, label in CONDITIONS.items():
        checked_process("run_inference.py", runner_args(run_dir, plan, key), env=env, accepted=(0, 3))
        checked_process("evaluate.py", ["--data-root", str(DATA_ROOT), "--qa", str(run_dir / "inputs" / f"{key}.jsonl"),
                                        "--predictions", str(run_dir / label / "predictions.jsonl"),
                                        "--out", str(run_dir / label / "report.json")])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--run", action="store_true", help="send the fixed 32 logical requests")
    parser.add_argument("--resume", action="store_true", help="only continue unattempted IDs; never retry terminal answers")
    args = parser.parse_args(argv)
    try:
        if args.resume and not args.run:
            raise ValueError("--resume requires --run")
        run_dir = args.run_dir.resolve()
        plan = prepare(run_dir)
        offline_checks(run_dir, plan)
        if args.run:
            run_real(run_dir, plan, args.resume)
        summary = summarize(run_dir, plan)
        print(json.dumps({"run_dir": str(run_dir), "plan_sha256": plan["plan_sha256"],
                          "questions_per_condition": plan["questions_per_condition"],
                          "logical_requests": plan["logical_requests"], "state": summary["state"],
                          "budget_gate": summary["budget_gate"]}, ensure_ascii=False))
        if args.run and summary["budget_gate"] != "pass_on_fixed_subset":
            return 3
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

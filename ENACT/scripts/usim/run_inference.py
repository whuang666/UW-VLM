"""Multi-image inference runner for the USIM-ENACT question set (DashScope-ready).

Design rules that come from docs/WBR:

* ``--api-url`` takes a **complete** endpoint and posts to it verbatim; legacy
  ``--base-url`` appends ``/chat/completions``.  They are mutually exclusive and a
  duplicated suffix is rejected.
* The key is read from ``VLM_API_KEY``; it is never written to disk, never echoed,
  and never stored in ``run_config.json`` (only ``api_key_present``).
* Option A prompt policy: by default **no system message**.  The frozen question text
  already carries the role and output-format instructions, which matches the
  provider's advice to put such instructions in the user message.
* Every attempt is logged; final failures keep their ID and count as 0 in scoring.
* Resuming compares configuration / QA / image hashes, not just IDs.
* Only whitelisted fields reach the model: question text + images in frozen order.
  ``key_frame_ids``, ``gt_answer``, timestamps and file names are never sent.

Exit codes: 0 completed, 3 completed_with_failures, 2 aborted (config/asset/auth).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
CHAT_SUFFIX = "/chat/completions"
DEFAULT_FORMAT_DIRECTIVE = (
    "IMPORTANT: Respond with ONLY the Python list of integers, for example [2, 1]. "
    "Do not write any explanation, reasoning steps, or extra words."
)
TZ = timezone(timedelta(hours=8))

AUTH_STATUS = {401, 403}
FATAL_STATUS = {400, 404, 422}
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
TERMINAL_STATES = ("success", "truncated", "invalid", "failed")


# --------------------------------------------------------------------------- util
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def code_hashes() -> Dict[str, str]:
    targets = [
        ROOT / "scripts" / "usim" / name
        for name in ("run_inference.py", "evaluate.py", "build_qa.py", "build_dataset.py", "reseed_answers.py")
    ]
    targets += sorted((ROOT / "enact" / "adapters").glob("*.py"))
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in targets if path.exists()}


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


# ------------------------------------------------------------------- validation
def resolve_api_url(args: argparse.Namespace) -> str:
    if args.api_url and args.base_url:
        raise SystemExit("--api-url 与 --base-url 互斥，请只给一个。")
    if args.api_url:
        url = args.api_url.strip()
        if url.count(CHAT_SUFFIX) > 1:
            raise SystemExit(f"--api-url 里 {CHAT_SUFFIX} 出现多次，URL 可能被重复拼接：{url}")
        if not url.endswith(CHAT_SUFFIX):
            raise SystemExit(f"--api-url 应为完整地址并以 {CHAT_SUFFIX} 结尾，当前为：{url}")
        return url
    if args.base_url:
        base = args.base_url.strip().rstrip("/")
        if base.endswith(CHAT_SUFFIX):
            raise SystemExit(f"--base-url 已包含 {CHAT_SUFFIX}，会再追加一次；请改用 --api-url。")
        return base + CHAT_SUFFIX
    raise SystemExit("缺少接口地址：请设置 VLM_API_URL（完整地址）或传 --api-url。")


def resolve_model(args: argparse.Namespace) -> str:
    model = args.model or os.environ.get("VLM_MODEL_NAME", "")
    if not model:
        raise SystemExit("缺少模型名：请设置 VLM_MODEL_NAME 或传 --model。")
    return model


def resolve_key(args: argparse.Namespace) -> str:
    key = os.environ.get("VLM_API_KEY", "").strip() or args.api_key.strip()
    if not key:
        raise SystemExit("缺少密钥：请在本会话设置环境变量 VLM_API_KEY（不要写进命令行或文件）。")
    return key


def whitelist_payload(record: Dict, data_root: Path) -> Dict:
    """The only view of a frozen record that may reach the model."""
    images = []
    for relative in record["images"]:
        path = data_root / str(relative).replace("\\", "/")
        if not path.exists():
            raise FileNotFoundError(f"missing image: {path}")
        images.append(path)
    expected = len(record["key_frame_ids"])
    if len(images) != expected:
        raise ValueError(f"{record['id']}: {len(images)} images for L={expected}")
    return {"id": record["id"], "question": record["question"], "images": images}


def build_body(
    model: str,
    question: str,
    images: List[Path],
    args: argparse.Namespace,
    system_prompt: str,
    format_directive: str,
) -> Dict[str, Any]:
    text = question
    if format_directive.strip():
        text = question.rstrip() + "\n\n" + format_directive.strip()
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    if not getattr(args, "drop_images", False):
        for image in images:
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})

    messages: List[Dict[str, Any]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    return {
        "model": model,
        "messages": messages,
        "temperature": args.temperature,
        "stream": False,
        "max_completion_tokens": args.max_completion_tokens,
        "enable_thinking": args.enable_thinking,
    }


# ------------------------------------------------------------------------ http
def post_json(url: str, body: Dict, api_key: str, timeout: int) -> Tuple[int, Dict[str, str], Dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, headers, json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        headers = {k.lower(): v for k, v in (error.headers.items() if error.headers else [])}
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"raw": raw[:2000]}
        return error.code, headers, detail


def classify(status: Optional[int]) -> str:
    if status is None:
        return "network"
    if status in AUTH_STATUS:
        return "auth"
    if status in FATAL_STATUS:
        return "config"
    if status == 429:
        return "rate_limit"
    if status in RETRY_STATUS:
        return "server"
    return "unknown"


def request_with_retry(url: str, body: Dict, api_key: str, args: argparse.Namespace) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    for attempt in range(1, args.max_attempts + 1):
        started = time.time()
        try:
            status, headers, payload = post_json(url, body, api_key, args.timeout)
        except Exception as error:  # URLError / timeout / socket
            status, headers, payload = None, {}, {"error": f"{type(error).__name__}: {error}"}
        elapsed = round(time.time() - started, 2)
        error_class = "ok" if status == 200 else classify(status)
        last = {
            "attempt": attempt,
            "http_status": status,
            "error_class": error_class,
            "elapsed_seconds": elapsed,
            "retry_after": headers.get("retry-after"),
            "request_id": headers.get("x-request-id") or headers.get("x-dashscope-request-id"),
            "payload": payload,
        }
        if status == 200 or error_class in ("auth", "config"):
            return last
        if attempt < args.max_attempts:
            try:
                wait = float(last["retry_after"]) if last["retry_after"] else min(8.0, 2.0 * attempt)
            except (TypeError, ValueError):
                wait = 2.0
            time.sleep(wait + random.uniform(0, 0.3))
    return last


def extract_answer(payload: Dict) -> Tuple[str, str, Optional[str]]:
    choices = payload.get("choices") or []
    if not choices:
        return "", "invalid", None
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    content = (choice.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = (content or "").strip()
    if not text:
        return "", "invalid", finish_reason
    if finish_reason == "length":
        return text, "truncated", finish_reason
    return text, "success", finish_reason


# ----------------------------------------------------------------------- config
def compatibility_manifest(url: str, model: str, args: argparse.Namespace, qa_hash: str, image_hash: str) -> Dict[str, Any]:
    return {
        "api_url": url,
        "model_requested": model,
        "enable_thinking": args.enable_thinking,
        "temperature": args.temperature,
        "max_completion_tokens": args.max_completion_tokens,
        "system_prompt_sha256": sha256_text(args.system_prompt) if args.system_prompt.strip() else None,
        "format_directive_sha256": sha256_text(args.format_directive) if args.format_directive.strip() else None,
        "qa_sha256": qa_hash,
        "image_manifest_sha256": image_hash,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", required=True)
    parser.add_argument("--out", required=True, help="predictions.jsonl；其父目录即 run 目录")
    parser.add_argument("--backend", default="openai", choices=["openai", "oracle", "identity", "random"])
    parser.add_argument("--api-url", default=os.environ.get("VLM_API_URL", ""))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="", help="不推荐；默认从 VLM_API_KEY 读取")
    parser.add_argument("--system-prompt", default="", help="默认空 = 不发 system message（方案 A）")
    parser.add_argument("--format-directive", default=DEFAULT_FORMAT_DIRECTIVE,
                        help="追加到 user message 末尾的格式指令；传空串可关闭")
    parser.add_argument("--no-format-directive", action="store_true")
    parser.add_argument("--drop-images", action="store_true",
                        help="对照条件 C：不发送任何图片，只给题干文本")
    parser.add_argument("--condition-label", default="",
                        help="写入 run_config 的观测条件名，如 B_zoom；缺省按是否发图推断")
    parser.add_argument("--enable-thinking", default="false", choices=["true", "false"])
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-completion-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only-ids", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--new-run", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    args.enable_thinking = args.enable_thinking == "true"
    if args.no_format_directive:
        args.format_directive = ""

    data_root = Path(args.data_root)
    qa_path = Path(args.qa)
    out_path = Path(args.out)
    run_dir = out_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(qa_path)
    if args.only_ids:
        wanted = {value.strip() for value in args.only_ids.split(",") if value.strip()}
        records = [record for record in records if record["id"] in wanted]
    if args.limit:
        records = records[: args.limit]
    if not records:
        raise SystemExit(f"没有可运行的题目：{qa_path}")
    if len({record["id"] for record in records}) != len(records):
        raise SystemExit("题目 ID 有重复，拒绝运行。")

    # ---- asset pre-check (always, not only in dry-run)
    failures: List[str] = []
    image_rows: List[Dict] = []
    for record in records:
        try:
            payload = whitelist_payload(record, data_root)
        except (FileNotFoundError, ValueError, KeyError) as error:
            failures.append(str(error))
            continue
        image_rows.append(
            {
                "id": record["id"],
                "images": [
                    {
                        "path": str(image.relative_to(data_root)),
                        "sha256": sha256_file(image),
                        "bytes": image.stat().st_size,
                    }
                    for image in payload["images"]
                ],
            }
        )
    if failures:
        print("资产检查失败，未发起任何请求：", file=sys.stderr)
        for item in failures[:20]:
            print("  -", item, file=sys.stderr)
        return 2

    qa_hash = sha256_file(qa_path)
    image_hash = sha256_text(json.dumps(image_rows, sort_keys=True, ensure_ascii=False))

    if args.backend == "openai":
        url = resolve_api_url(args)
        model = resolve_model(args)
        # key presence is part of the no-network check: a dry-run without a key must fail
        api_key = resolve_key(args)
    else:
        url, model, api_key = "", args.backend, ""

    manifest = compatibility_manifest(url, model, args, qa_hash, image_hash)
    config_path = run_dir / "run_config.json"
    if config_path.exists() and not args.new_run:
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        diffs = {
            key: {"previous": previous.get(key), "current": value}
            for key, value in manifest.items()
            if key in previous and previous.get(key) != value
        }
        if diffs:
            print("已有 run 配置与本次不一致，拒绝续跑（换配置请 --new-run 并另开目录）：", file=sys.stderr)
            print(json.dumps(diffs, indent=2, ensure_ascii=False), file=sys.stderr)
            return 2

    summary = {
        "dry_run": bool(args.dry_run),
        "questions": len(records),
        "images_total": sum(len(row["images"]) for row in image_rows),
        "api_url": url,
        "model": model,
        "api_key_present": bool(api_key) if args.backend == "openai" else None,
        "enable_thinking": args.enable_thinking,
        "temperature": args.temperature,
        "max_completion_tokens": args.max_completion_tokens,
        "timeout": args.timeout,
        "max_attempts": args.max_attempts,
        "system_message": "none (option A)" if not args.system_prompt.strip() else "custom",
        "format_directive_sha256": sha256_text(args.format_directive) if args.format_directive.strip() else None,
        "qa_sha256": qa_hash,
        "image_manifest_sha256": image_hash,
        "run_dir": str(run_dir),
    }

    (run_dir / "input_manifest.json").write_text(
        json.dumps({"qa": str(qa_path), "qa_sha256": qa_hash, "records": image_rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if args.dry_run:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print("dry-run: 未发起任何网络请求。")
        return 0

    config = dict(manifest)
    config.update(
        {
            "api_key_env": "VLM_API_KEY",
            "api_key_present": bool(api_key) if args.backend == "openai" else None,
            "stream": False,
            "timeout_seconds": args.timeout,
            "max_attempts": args.max_attempts,
            "backend": args.backend,
            "qa_path": str(qa_path),
            "started_at": now_iso(),
            "code_sha256": code_hashes(),
            "system_prompt": args.system_prompt if args.system_prompt.strip() else None,
            "prompt_policy": "custom_system_message" if args.system_prompt.strip() else "option_a_no_system_message",
            "format_directive": args.format_directive if args.format_directive.strip() else None,
            "image_condition": args.condition_label or ("none" if args.drop_images else "ego_full"),
        }
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    predictions_path = out_path
    attempts_path = run_dir / "attempts.jsonl"
    responses_path = run_dir / "responses.jsonl"

    done: Dict[str, Dict] = {}
    if predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print("predictions 里存在损坏行，拒绝续跑；请检查或换新 run。", file=sys.stderr)
                return 2
            if row.get("status") in TERMINAL_STATES:
                done[row["id"]] = row

    pending = [record for record in records if record["id"] not in done]
    print(f"questions={len(records)} already_done={len(done)} pending={len(pending)}")

    abort_reason: Optional[str] = None
    with (
        predictions_path.open("a", encoding="utf-8") as pred_handle,
        attempts_path.open("a", encoding="utf-8") as attempt_handle,
        responses_path.open("a", encoding="utf-8") as response_handle,
    ):
        for index, record in enumerate(pending, start=1):
            payload = whitelist_payload(record, data_root)
            row: Dict[str, Any] = {
                "id": record["id"],
                "type": record["type"],
                "task_name": record["task_name"],
                "num_states": len(record["key_frame_ids"]),
                "backend": args.backend,
                "model": model or args.backend,
                "timestamp": now_iso(),
            }

            if args.backend in ("oracle", "identity", "random"):
                length = len(record["gt_answer"])
                if args.backend == "oracle":
                    value = list(record["gt_answer"])
                elif args.backend == "identity":
                    value = list(range(1, length + 1))
                else:
                    value = list(range(1, length + 1))
                    random.Random(args.seed + index).shuffle(value)
                row.update({"answer": json.dumps(value), "status": "success", "attempts": 1,
                            "finish_reason": "synthetic", "usage": None, "model_returned": args.backend})
            else:
                body = build_body(model, payload["question"], payload["images"], args, args.system_prompt, args.format_directive)
                outcome = request_with_retry(url, body, api_key, args)
                attempt_handle.write(
                    json.dumps(
                        {
                            "id": record["id"],
                            "attempt": outcome["attempt"],
                            "http_status": outcome["http_status"],
                            "error_class": outcome["error_class"],
                            "elapsed_seconds": outcome["elapsed_seconds"],
                            "request_id": outcome["request_id"],
                            "response_model": (outcome["payload"] or {}).get("model"),
                            "usage": (outcome["payload"] or {}).get("usage"),
                            "error": None if outcome["http_status"] == 200
                            else json.dumps(outcome["payload"], ensure_ascii=False)[:600],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                attempt_handle.flush()

                if outcome["http_status"] == 200:
                    text, status, finish_reason = extract_answer(outcome["payload"])
                    response_handle.write(
                        json.dumps({"id": record["id"], "response": outcome["payload"]}, ensure_ascii=False) + "\n"
                    )
                    response_handle.flush()
                    row.update(
                        {
                            "answer": text,
                            "status": status,
                            "attempts": outcome["attempt"],
                            "finish_reason": finish_reason,
                            "usage": (outcome["payload"] or {}).get("usage"),
                            "model_returned": (outcome["payload"] or {}).get("model"),
                            "request_id": outcome["request_id"] or (outcome["payload"] or {}).get("id"),
                        }
                    )
                else:
                    row.update(
                        {
                            "answer": "",
                            "status": "failed",
                            "attempts": outcome["attempt"],
                            "error_class": outcome["error_class"],
                            "http_status": outcome["http_status"],
                            "error": json.dumps(outcome["payload"], ensure_ascii=False)[:800],
                        }
                    )
                    if outcome["error_class"] in ("auth", "config"):
                        abort_reason = f"{outcome['error_class']}: HTTP {outcome['http_status']}"

            pred_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            pred_handle.flush()

            if abort_reason:
                print(f"遇到不可重试错误，停止本轮：{abort_reason}", file=sys.stderr)
                break

            if index % 5 == 0 or index == len(pending):
                usage = row.get("usage") or {}
                print(f"  {index}/{len(pending)} {row['status']} finish={row.get('finish_reason')} usage={usage}")
            if args.sleep:
                time.sleep(args.sleep)

    # ---- recompute run status from the full predictions file (resume-safe)
    counts = {state: 0 for state in TERMINAL_STATES}
    present: Dict[str, str] = {}
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") in TERMINAL_STATES:
            present[row["id"]] = row["status"]
    for status in present.values():
        counts[status] = counts.get(status, 0) + 1
    missing = [record["id"] for record in records if record["id"] not in present]
    unusable = counts["invalid"] + counts["truncated"] + counts["failed"] + len(missing)

    state = "failed" if abort_reason else ("completed_with_failures" if unusable else "completed")
    status_payload = {
        "state": state,
        "abort_reason": abort_reason,
        "planned": len(records),
        "answered": len(present),
        "success": counts["success"],
        "truncated": counts["truncated"],
        "invalid": counts["invalid"],
        "failed": counts["failed"],
        "missing": len(missing),
        "finished_at": now_iso(),
        "config": str(config_path),
    }
    (run_dir / "run_status.json").write_text(
        json.dumps(status_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(status_payload, ensure_ascii=False))
    return {"completed": 0, "completed_with_failures": 3}.get(state, 2)


if __name__ == "__main__":
    raise SystemExit(main())

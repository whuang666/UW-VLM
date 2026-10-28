"""Freeze/verify the supplementary extraction rule, independently of model runs.

Creation runs the tools test suite and pins the rule, implementation, primary
parser dependency and tests. Verification is read-only. No model API is used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[3]
DEFAULT_OUT = WORKSPACE / "ENACT/docs/protocols/extractable_permutation_v1.freeze.json"
SCHEMA = "usim-supplementary-rule-freeze/v1"
VERSION = "extractable_permutation_v1"
FILES = (
    "ENACT/docs/protocols/extractable_permutation_v1.md",
    "ENACT/scripts/usim/extractable_v1.py",
    "ENACT/scripts/usim/report_extractable_v1.py",
    "ENACT/scripts/usim/evaluate.py",
    "ENACT/scripts/usim/freeze_extractable_v1.py",
    "tools/test_extractable_v1.py",
    "tools/test_report_extractable_v1.py",
    "tools/test_freeze_extractable_v1.py",
)


def payload_hash(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def file_hashes(root: Path, paths: tuple | list) -> dict[str, str]:
    result = {}
    for relative in paths:
        path = (root / relative).resolve()
        if root.resolve() not in path.parents:
            raise ValueError("Freeze file path escapes the workspace")
        result[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError("A freeze must pin at least one file")
    return result


def build_manifest(root: Path, paths: tuple | list, tests: dict, freeze_id: str) -> dict:
    manifest = {
        "schema": SCHEMA, "metric_version": VERSION, "freeze_id": freeze_id, "frozen": True,
        "frozen_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "primary_metric": "usim_strict_v0.3", "primary_metric_unchanged": True,
        "existing_dev_analysis_is_post_hoc": True, "affects_budget_gate": False,
        "scope": "supplementary rule, implementation, primary parser dependency and tests only",
        "not_frozen_here": ["test labels/inputs", "model snapshot", "prompt", "decoding budget"],
        "punctuation_tolerance": False, "expected_length": "num_states - 1",
        "unified_output_budget": None, "diagnostic_1024_gate": "fail_on_fixed_subset",
        "files_sha256": file_hashes(root, paths), "tests": tests,
    }
    manifest["payload_sha256"] = payload_hash(manifest)
    return manifest


def verify_manifest(manifest: dict, root: Path = WORKSPACE) -> dict:
    errors = []
    payload = dict(manifest)
    recorded = payload.pop("payload_sha256", None)
    if recorded != payload_hash(payload):
        errors.append("payload hash mismatch")
    if manifest.get("schema") != SCHEMA or manifest.get("metric_version") != VERSION:
        errors.append("unsupported schema or metric version")
    if manifest.get("frozen") is not True or not manifest.get("files_sha256"):
        errors.append("missing frozen status or file inventory")
    for relative, expected in manifest.get("files_sha256", {}).items():
        try:
            actual = file_hashes(root, [relative])[relative]
            if actual != expected:
                errors.append(f"file hash mismatch: {relative}")
        except (OSError, ValueError):
            errors.append(f"missing or unsafe file: {relative}")
    return {"ok": not errors, "errors": errors, "files_checked": len(manifest.get("files_sha256", {})),
            "payload_sha256": recorded}


def suite_ids(suite: unittest.TestSuite) -> list[str]:
    ids = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            ids.extend(suite_ids(test))
        else:
            ids.append(test.id())
    return ids


def write_manifest(path: Path, manifest: dict) -> None:
    # Never rewrite an existing registration, even with the same CLI arguments.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--freeze-id", default="20261028_extractable_v1")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            report = verify_manifest(json.loads(args.verify.read_text(encoding="utf-8")))
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report["ok"] else 2
        if args.out.exists():
            raise ValueError("Registration already exists; verify it or use a new, explicitly versioned registration")
        before = file_hashes(WORKSPACE, FILES)
        suite = unittest.TestLoader().discover(str(WORKSPACE / "tools"), pattern="test_*.py")
        ids = suite_ids(suite)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or result.skipped:
            raise ValueError("Freeze requires a passing tools suite with no skipped tests")
        if file_hashes(WORKSPACE, FILES) != before:
            raise ValueError("Source changed during validation; refusing to freeze")
        relevant = sorted(qid for qid in ids if qid.startswith((
            "test_extractable_v1.", "test_report_extractable_v1.", "test_freeze_extractable_v1.")))
        tests = {"command": "python -m unittest discover -s tools -p test_*.py -v",
                 "full_suite_count": result.testsRun, "full_suite_passed": True, "skipped": 0,
                 "supplementary_test_count": len(relevant), "supplementary_test_ids": relevant}
        manifest = build_manifest(WORKSPACE, FILES, tests, args.freeze_id)
        write_manifest(args.out, manifest)
        print(json.dumps({"manifest": str(args.out), **verify_manifest(manifest)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Verify a snapshot's content hashes and optionally promote downloaded partials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from hf_snapshot_download import local_path, verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", nargs="?", default="tools/_hfcache/expected.json")
    parser.add_argument("root", nargs="?", default="usim")
    parser.add_argument("--promote-partials", action="store_true")
    parser.add_argument("--report", default="tools/_hfcache/verification.json")
    args = parser.parse_args()
    items = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    root = Path(args.root).resolve()
    missing, bad, ok, promoted = [], [], 0, 0
    for item in items:
        target = local_path(root, item["path"])
        partial = target.with_name(target.name + ".incomplete")
        if args.promote_partials and partial.is_file() and verified(partial, item):
            partial.replace(target)
            promoted += 1
            ok += 1
            continue
        if not target.is_file():
            missing.append(item["path"])
        elif not verified(target, item):
            bad.append(item["path"])
        else:
            ok += 1
    report = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(root), "expected_files": len(items),
        "expected_bytes": sum(item["size"] for item in items),
        "verified_files": ok, "promoted_files": promoted,
        "sha256_files": sum("sha256" in item for item in items),
        "git_blob_sha1_files": sum("git_blob_sha1" in item for item in items),
        "missing": missing, "hash_or_size_mismatch": bad,
        "complete": not missing and not bad,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"expected={len(items)} files, {report['expected_bytes']:,} bytes")
    print(f"verified={ok} promoted={promoted} missing={len(missing)} mismatch={len(bad)}")
    for path in missing[:20]:
        print("  MISSING", path)
    for path in bad[:20]:
        print("  MISMATCH", path)
    print(f"report={report_path.resolve()}")
    raise SystemExit(0 if report["complete"] else 2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Plan a complete, commit-pinned Hugging Face dataset download.

    python tools/hf_snapshot_download.py Vincent2025hello/usim usim
    curl.exe -K tools/_hfcache/curl_all.cfg
    python tools/hf_verify.py tools/_hfcache/expected.json usim --promote-partials

Every tree API page is followed and checked against the repository's sibling
list. Existing files are skipped only after content verification. Downloads go
to .incomplete files; the verifier promotes them only after verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import quote, urlparse
from urllib.request import Request, getproxies, urlopen

DEFAULT_ENDPOINT = "https://huggingface.co"


def get_json(url):
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "hf-snapshot-repair/1.0"})
            with urlopen(request, timeout=30) as response:
                return json.load(response), response.headers.get("Link", "")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def list_snapshot(endpoint, repo_id, revision):
    base = f"{endpoint}/api/datasets/{repo_id}"
    info, _ = get_json(f"{base}/revision/{quote(revision, safe='')}")
    commit = info["sha"]
    url = f"{base}/tree/{commit}?recursive=true&expand=false&limit=1000"
    seen, files, pages = set(), {}, []
    while url:
        if url in seen or urlparse(url).netloc != urlparse(endpoint).netloc:
            raise ValueError("Invalid or repeated tree pagination URL")
        seen.add(url)
        entries, links = get_json(url)
        pages.append({"url": url, "entries": len(entries)})
        for entry in entries:
            if entry["type"] == "file":
                path = entry["path"]
                if path in files:
                    raise ValueError(f"Duplicate file in tree listing: {path}")
                files[path] = entry
        print(f"[tree] page={len(pages)} entries={len(entries)} files={len(files)}", flush=True)
        match = re.search(r'<([^>]+)>;\s*rel="next"', links)
        url = match.group(1) if match else None
    siblings = {entry["rfilename"] for entry in info["siblings"]}
    if set(files) != siblings:
        raise ValueError("Paginated tree differs from repository sibling list; refusing partial plan")
    return {"repo_id": repo_id, "endpoint": endpoint, "commit": commit,
            "pages": pages, "files": [files[path] for path in sorted(files)]}


def expected_file(entry):
    item = {"path": entry["path"], "size": entry["size"]}
    if entry.get("lfs"):
        item["sha256"] = entry["lfs"]["oid"]
    else:
        item["git_blob_sha1"] = entry["oid"]
    return item


def local_path(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError(f"Unsafe repository path: {relative}")
    result = root.joinpath(*path.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Repository path escapes destination: {relative}")
    return result


def verified(path, item):
    if not path.is_file() or path.stat().st_size != item["size"]:
        return False
    if "sha256" in item:
        digest = hashlib.sha256()
        expected = item["sha256"]
    elif "git_blob_sha1" in item:
        digest = hashlib.sha1()
        digest.update(f"blob {item['size']}\0".encode())
        expected = item["git_blob_sha1"]
    else:
        raise ValueError(f"No content hash for {item['path']}; regenerate the manifest")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def curl_string(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_id")
    parser.add_argument("dest")
    parser.add_argument("--cache", default="tools/_hfcache")
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--revision", default="main")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--proxy", default=getproxies().get("https") or getproxies().get("http"),
                        help="Transfer proxy; defaults to the OS/environment HTTPS proxy")
    parser.add_argument("--trees", nargs="*", help="Deprecated; full remote listing is always fetched")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    cache, root = Path(args.cache), Path(args.dest).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    if args.trees:
        print("[i] Ignoring legacy single-page --trees caches; fetching all remote pages")
    endpoint = args.endpoint.rstrip("/")
    snapshot = list_snapshot(endpoint, args.repo_id, args.revision)
    items = [expected_file(entry) for entry in snapshot["files"]]
    todo = []
    for item in items:
        target = local_path(root, item["path"])
        if verified(target, item):
            continue
        partial = target.with_name(target.name + ".incomplete")
        if verified(partial, item):
            partial.replace(target)
        else:
            todo.append(item)
    # A damaged same-size partial must be overwritten on a retry.
    config = ["parallel", f"parallel-max = {args.workers}", "silent", "show-error",
              "location", "fail", "create-dirs", "retry = 4", "retry-delay = 2",
              "connect-timeout = 20", "max-time = 180", "speed-limit = 1024",
              "speed-time = 30"]
    # curl does not read the Windows system proxy that urllib uses for the API.
    if args.proxy:
        config.append("proxy = " + curl_string(args.proxy))
    for item in todo:
        target = local_path(root, item["path"])
        url = f"{endpoint}/datasets/{args.repo_id}/resolve/{snapshot['commit']}/{quote(item['path'])}"
        config.extend(["url = " + curl_string(url),
                       "output = " + curl_string(target.as_posix() + ".incomplete")])
    (cache / "curl_all.cfg").write_text("\n".join(config) + "\n", encoding="utf-8")
    (cache / "expected.json").write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    (cache / "remote_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"[i] commit={snapshot['commit']} pages={len(snapshot['pages'])}")
    print(f"[i] expected={len(items)} files, {sum(item['size'] for item in items):,} bytes")
    print(f"[i] verified existing={len(items) - len(todo)}; download={len(todo)} files, "
          f"{sum(item['size'] for item in todo):,} bytes")
    if todo:
        print(f'[>] curl.exe -K "{cache / "curl_all.cfg"}"')
        print(f'[>] python tools/hf_verify.py "{cache / "expected.json"}" "{root}" --promote-partials')
    else:
        print("[i] All published files are already complete and content-verified")


if __name__ == "__main__":
    main()

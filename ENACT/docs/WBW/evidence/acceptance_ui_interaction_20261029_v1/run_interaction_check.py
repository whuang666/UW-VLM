"""Exercise the real offline page using synthetic, explicitly nonhuman input.

Downloads and temporary files stay in a separate UI-test directory. Source
worksheets and candidate annotations remain untouched; no human acceptance is
asserted by these browser interactions.
"""

from __future__ import annotations

import copy
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

WORKSPACE = Path(__file__).resolve().parents[5]
PACKET = WORKSPACE / "ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v1"
EVIDENCE = Path(__file__).resolve().parent
WORK = WORKSPACE / "ENACT/data/usim_enact/_review/test_reserve/acceptance_ui_smoke_20261029_v1/tools_out"
IDENTITY = "AUTOMATED_UI_TEST_NOT_A_HUMAN_REVIEW"
NOTE = "AUTOMATED SYNTHETIC INPUT; not image evidence or human annotation."
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export(page, name: str) -> tuple[Path, dict]:
    with page.expect_download() as event:
        page.locator("#export").click()
    download = event.value
    assert download.suggested_filename == "completed_reviews.json"
    target = WORK / name
    download.save_as(target)
    return target, read(target)


def fields_like(template, value) -> bool:
    if isinstance(template, dict):
        return isinstance(value, dict) and set(template) == set(value) and all(fields_like(template[k], value[k]) for k in template)
    if isinstance(template, list):
        return isinstance(value, list) and len(template) == len(value) and all(fields_like(a, b) for a, b in zip(template, value))
    return True


def validator(path: Path, name: str) -> dict:
    output = EVIDENCE / name
    result = subprocess.run([sys.executable, "-X", "utf8", str(WORKSPACE / "ENACT/scripts/usim/validate_acceptance_reviews.py"),
                             "--packet-dir", str(PACKET), "--reviews", str(path), "--out", str(output)], cwd=WORKSPACE,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    value = read(output)
    assert value["complete_review_declarations"] == 0 and value["accepted_current_snapshot_episodes"] == 0
    assert value["reviewer_declaration_valid"] is False and value["release_eligible"] is False
    return {"exit": result.returncode, "accepted": 0, "report_sha256": sha(output)}


def main() -> None:
    global PACKET, WORK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-dir", type=Path, default=PACKET)
    parser.add_argument("--work-dir", type=Path, default=WORK)
    parser.add_argument("--result-name", default="initial_interaction_result.json")
    args = parser.parse_args()
    PACKET, WORK = args.packet_dir.resolve(), args.work_dir.resolve()
    if WORK.exists():
        raise FileExistsError("Use a new UI-test artifact directory instead of overwriting")
    WORK.mkdir(parents=True)
    template = read(PACKET / "review_templates.json")
    before = {name: sha(PACKET / name) for name in ("review.html", "packet_manifest.json", "review_templates.json")}
    result = {"schema": "usim-acceptance-ui-smoke/v1", "test_identity": IDENTITY, "synthetic_only": True,
              "page_sha256": before["review.html"], "playwright_browser": "Microsoft Edge headless",
              "human_acceptance_asserted": False, "model_api_calls": 0, "tests": {}}
    checks = result["tests"]
    browser_errors, requests = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(EDGE), headless=True,
                    args=["--disable-background-networking", "--no-first-run", "--disable-extensions"])
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1100})

        def network_route(route):
            requests.append(route.request.url)
            route.abort()

        context.route(re.compile(r"^https?://"), network_route)
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.goto((PACKET / "review.html").as_uri(), wait_until="load")
        assert page.locator("#episodes section").count() == 10
        images = page.locator("#episodes img")
        assert images.count() == 94
        assert images.evaluate_all("imgs => imgs.every(i => i.complete && i.naturalWidth > 0)")
        assert page.locator('input[type="checkbox"]:checked').count() == 0
        _, empty = export(page, "empty_export.json")
        assert empty == template
        checks["initial_export_exactly_matches_blank_template"] = True
        checks["rendered_episode_count"] = 10
        checks["decoded_browser_images"] = 94

        page.locator("#identity").fill(IDENTITY)
        for name in ("human", "independent", "exposure"):
            page.locator("#" + name).select_option("false")
        section = page.locator("#episodes section").first
        for frame_index in range(section.locator(".frame").count()):
            frame = section.locator(".frame").nth(frame_index)
            for index, select in enumerate(frame.locator("select").all()):
                select.select_option("true" if index % 2 == 0 else "false")
            frame.locator("textarea").fill(NOTE + f" frame-control-{frame_index}")
        # Transition controls, criteria and the disposition are outside .frame.
        selects = section.locator("select").all()
        for select in selects:
            if select.evaluate("e => Boolean(e.closest('.frame'))"):
                continue
            values = select.locator("option").evaluate_all("options => options.map(o => o.value)")
            select.select_option("changes_required" if "changes_required" in values else "true")
        for area in section.locator("textarea").all():
            if not area.input_value():
                area.fill(NOTE)
        section.locator('input:not([type="checkbox"])').fill(IDENTITY)
        section.locator('input[type="checkbox"]').check()
        exported_path, exported = export(page, "filled_export.json")
        assert fields_like(template, exported)
        assert exported["reviewer_is_human"] is False and exported["reviewer_independent_of_first_pass"] is False
        worksheet = exported["worksheets"][0]
        assert worksheet["decision"] == "changes_required" and worksheet["review_complete"] is True
        assert worksheet["signature_name"] == IDENTITY and worksheet["signed_at"] and worksheet["attestation"]
        assert all(f["evidence_note"].startswith(NOTE) for f in worksheet["frames"])
        assert all(type(fact["value"]) is bool for f in worksheet["frames"] for fact in f["facts"])
        assert exported["worksheets"][1:] == template["worksheets"][1:]
        checks["filled_all_first_worksheet_controls"] = True
        checks["export_preserves_all_template_fields"] = True
        checks["nine_other_worksheets_stay_blank"] = True
        checks["downstream_rejects_automated_nonhuman_test"] = validator(exported_path, "synthetic_validator_" + args.result_name)
        page.screenshot(path=str(WORK / "filled_page.png"), full_page=False)

        page.reload(wait_until="load")
        assert page.locator("#identity").input_value() == ""
        page.locator("#import").set_input_files(str(exported_path))
        page.wait_for_function("document.querySelector('#status').textContent.includes('已载入')")
        assert page.locator("#identity").input_value() == IDENTITY
        assert page.locator("#human").input_value() == "false"
        assert page.locator("#episodes section").first.locator('input[type="checkbox"]').is_checked()
        _, roundtrip = export(page, "roundtrip_export.json")
        assert roundtrip == exported
        checks["import_export_roundtrip_exact_json_values"] = True

        wrong = copy.deepcopy(exported)
        wrong["packet_manifest_sha256"] = "0" * 64
        wrong_path = WORK / "wrong_packet.json"
        write(wrong_path, wrong)
        page.locator("#import").set_input_files(str(wrong_path))
        page.wait_for_function("document.querySelector('#status').textContent.includes('不同')")
        _, after_wrong = export(page, "after_wrong_packet.json")
        assert after_wrong == exported
        checks["wrong_packet_import_rejected_without_data_loss"] = True

        # Same hash/episode list, but malformed nested review shape. Rejection
        # must preserve the user's already-entered state as an atomic operation.
        malformed = copy.deepcopy(exported)
        malformed["worksheets"][0]["frames"] = None
        malformed_path = WORK / "malformed_shape.json"
        write(malformed_path, malformed)
        page.locator("#import").set_input_files(str(malformed_path))
        page.wait_for_function("/导入失败|TypeError/.test(document.querySelector('#status').textContent)")
        _, after_malformed = export(page, "after_malformed.json")
        checks["malformed_nested_import_preserves_previous_state"] = after_malformed == exported
        checks["malformed_nested_import_keeps_10_rendered_episodes"] = page.locator("#episodes section").count() == 10
        checks["malformed_nested_import_downstream_rejection"] = validator(malformed_path, "malformed_downstream_" + args.result_name)
        if after_malformed == exported:
            variants = []
            wrong_frame = copy.deepcopy(exported)
            wrong_frame["worksheets"][0]["frames"][0]["source_frame"] += 1
            variants.append(("changed_source_frame", wrong_frame))
            wrong_type = copy.deepcopy(exported)
            wrong_type["worksheets"][0]["frames"][0]["facts"][0]["value"] = "false"
            variants.append(("string_fact_boolean", wrong_type))
            missing_key = copy.deepcopy(exported)
            del missing_key["worksheets"][0]["attestation"]
            variants.append(("missing_attestation", missing_key))
            for label, value in variants:
                target = WORK / (label + ".json")
                write(target, value)
                page.locator("#import").set_input_files(str(target))
                page.wait_for_function("document.querySelector('#status').textContent.includes('导入失败')")
                _, after = export(page, "after_" + label + ".json")
                assert after == exported
            checks["bad_types_missing_keys_and_frame_changes_keep_state"] = True
            # Upload the same valid file after a failure; the input must permit
            # reselecting a file rather than silently suppressing change events.
            page.locator("#import").set_input_files(str(exported_path))
            page.wait_for_function("document.querySelector('#status').textContent.includes('已载入')")
            _, final_roundtrip = export(page, "final_roundtrip.json")
            assert final_roundtrip == exported
            checks["valid_reimport_after_failed_imports"] = True
        result["browser_page_errors"] = browser_errors
        result["http_requests_intercepted"] = requests
        result["source_packet_hashes_unchanged"] = all(sha(PACKET / n) == h for n, h in before.items())
        browser.close()
    result["passed"] = all(value if type(value) is bool else isinstance(value, (dict, int)) for value in checks.values()) and not browser_errors and not requests
    write(EVIDENCE / args.result_name, result)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

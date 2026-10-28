"""P0: fault injection and offline end-to-end tests, with no model API calls."""

import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "ENACT"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from scripts.usim import protocol_ablation_v1 as contract
from scripts.usim import run_v02_protocol_ablation as driver
from tools.verify_protocol_ablation import verify

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4GQAAAAASUVORK5CYII=")


def http_result(content, *, status=200, finish="stop"):
    payload = {"id": "offline-response", "model": "qwen3.8-max", "choices": [{
        "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5}}
    raw = json.dumps(payload).encode()
    return {"http_status": status, "payload": payload, "response_wire_b64": base64.b64encode(raw).decode(),
            "response_wire_sha256": contract.sha(raw), "network_error": None, "headers": {"x-request-id": "offline-request"}}


def mock_http(url, wire, key, timeout):
    body = json.loads(wire)
    content = "2, 1]" if body["messages"][-1]["role"] == "assistant" else "[2, 1]"
    return http_result(content)


class MatrixFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="uwvlm_p0_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.data = self.root / "data"
        self.bundle = self.root / "run"
        for relative in contract.SOURCE_FILES:
            path = self.workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
        self.data.mkdir()
        (self.data / "a.png").write_bytes(PNG)
        (self.data / "b.png").write_bytes(PNG)
        a = [{"id": f"q{i}", "type": "forward_world_modeling_3_steps", "task_name": f"episode{i}",
              "key_frame_ids": ["0", "1", "2"], "images": ["a.png"] * 3,
              "gt_answer": [2, 1], "question": f"Arrange these states; example {i}. [Action 1] approach."} for i in range(2)]
        b = [dict(row, images=["b.png"] * 3, source_images=row["images"]) for row in a]
        d = [dict(row, question=f"Arrange these future states; example {index}.") for index, row in enumerate(a)]
        self.conditions = {"A": a, "B": b, "C": a, "D": d}
        self.decode = {"api_url": "https://example.invalid/v1/chat/completions", "model_requested": "qwen3.8-max",
                       "temperature": 0.0, "enable_thinking": False, "stream": False,
                       "max_completion_tokens": 2048, "system_prompt": None, "format_directive": "Only output the integer list."}
        self.plan = contract.create_bundle(self.bundle, self.workspace, self.data, self.conditions, self.decode, scope="fixture")

    def complete(self, transport=mock_http):
        with contextlib.redirect_stdout(io.StringIO()):
            result = driver.execute(self.bundle, workspace=self.workspace, transport=transport, sleeper=lambda _: None,
                                    key_reader=lambda: "offline-test-placeholder")
        self.assertTrue(result["ok"], result["errors"])
        return result

    def prediction_path(self):
        return self.bundle / "prefill/A_full_image/predictions.jsonl"

    def rewrite(self, path, rows):
        path.write_bytes(contract.rows_bytes(rows))

    def assert_rejected(self, **kwargs):
        result = verify(self.bundle, workspace=self.workspace, **kwargs)
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["execution_verified"])
        return result

    def change_final_response(self, transform):
        directory = self.prediction_path().parent
        predictions = contract.read_rows(self.prediction_path())
        responses = contract.read_rows(directory / "responses.jsonl")
        attempts = contract.read_rows(directory / "attempts.jsonl")
        identity = predictions[0]["job_id"]
        response = next(row for row in responses if row["job_id"] == identity)
        transform(response)
        response["response_wire_b64"] = base64.b64encode(json.dumps(response["payload"]).encode()).decode()
        response["response_wire_sha256"] = contract.sha(base64.b64decode(response["response_wire_b64"]))
        outcome = contract.decode_response_record(response)
        predictions[0].update(contract.score_response(outcome, "prefill", 2))
        predictions[0]["http_status"] = response["http_status"]
        predictions[0]["response_record_sha256"] = contract.sha(contract.canonical(response))
        for row in attempts:
            if row["job_id"] == identity:
                row["http_status"] = response["http_status"]
        self.rewrite(self.prediction_path(), predictions)
        self.rewrite(directory / "responses.jsonl", responses)
        self.rewrite(directory / "attempts.jsonl", attempts)


class PreparationTests(MatrixFixture):
    def test_prepared_is_not_complete_execution(self):
        report = verify(self.bundle, workspace=self.workspace, prepared_only=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["scope"], "prepared_inputs")
        self.assertFalse(report["execution_verified"])
        self.assert_rejected()

    def test_request_difference_and_c_has_zero_images(self):
        row = self.conditions["C"][0]
        body = contract.build_body(row, self.plan, "no_prefill", "C")
        self.assertEqual(len(body["messages"][0]["content"]), 1)
        prefill = contract.build_body(row, self.plan, "prefill", "C")
        self.assertEqual(prefill["messages"][:-1], body["messages"])
        self.assertEqual(prefill["messages"][-1], {"role": "assistant", "content": "[", "partial": True})
        self.assertNotIn("gt_answer", json.dumps(body))

    def test_payload_tampering_rejected(self):
        path = self.bundle / "candidate.freeze.json"
        manifest = contract.read_json(path)
        manifest["unified_output_budget"] = 2048
        path.write_bytes(contract.json_bytes(manifest))
        self.assert_rejected(prepared_only=True)

    def test_qa_change_rejected(self):
        path = self.bundle / "inputs/A.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assert_rejected(prepared_only=True)

    def test_image_change_rejected(self):
        (self.data / "a.png").write_bytes(PNG + b"changed")
        result = self.assert_rejected(prepared_only=True)
        self.assertIn("data:a.png", result["file_freeze"]["changed"])

    def test_source_drift_cannot_be_cancelled_by_body_hashes(self):
        path = self.workspace / contract.SOURCE_FILES[1]
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        result = self.assert_rejected(prepared_only=True)
        self.assertTrue(result["file_freeze"]["changed"])

    def test_resume_configuration_change_rejected_before_key(self):
        path = self.bundle / "prefill/A_full_image/run_config.json"
        value = contract.read_json(path)
        value["decode"]["max_completion_tokens"] = 4096
        path.write_bytes(contract.json_bytes(value))
        key = Mock()
        transport = Mock()
        with self.assertRaises(contract.IntegrityError):
            driver.execute(self.bundle, workspace=self.workspace, resume=True, key_reader=key, transport=transport)
        key.assert_not_called()
        transport.assert_not_called()

    def test_empty_qa_rejected(self):
        changed = copy.deepcopy(self.conditions)
        changed["D"] = []
        with self.assertRaises(contract.IntegrityError):
            contract.make_plan(self.data, changed, self.decode)

    def test_missing_required_inventory_rejected_even_with_new_payload_hash(self):
        path = self.bundle / "candidate.freeze.json"
        value = contract.read_json(path)
        value["files"] = value["files"][1:]
        path.write_bytes(contract.json_bytes(contract.seal(value)))
        self.assert_rejected(prepared_only=True)

    def test_scoring_reference_dependency_drift_rejected(self):
        path = self.workspace / "scene_reference.json"
        path.write_text("{}", encoding="utf-8")
        bundle = self.root / "reference_bundle"
        contract.create_bundle(bundle, self.workspace, self.data, self.conditions, self.decode, scope="fixture",
                               reference_files={"scene_reference.json": contract.file_sha(path)})
        path.write_text('{"changed":true}', encoding="utf-8")
        report = verify(bundle, workspace=self.workspace, prepared_only=True)
        self.assertFalse(report["ok"])
        self.assertIn("workspace:scene_reference.json", report["file_freeze"]["changed"])

    def test_inflight_cannot_trigger_automatic_resend(self):
        (self.bundle / "inflight.json").write_text("{}", encoding="utf-8")
        key = Mock()
        transport = Mock()
        with self.assertRaises(contract.IntegrityError):
            driver.execute(self.bundle, workspace=self.workspace, resume=True, key_reader=key, transport=transport)
        key.assert_not_called()
        transport.assert_not_called()

    def test_default_cli_only_prepares_and_does_not_access_credentials(self):
        with patch.object(driver, "prepare", return_value=self.plan) as prepare, patch.object(driver, "resolve_key") as key, \
                patch.object(driver, "send_http") as http, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.main(["--run-dir", str(self.bundle)]), 0)
            prepare.assert_called_once()
            key.assert_not_called()
            http.assert_not_called()

    def test_summary_and_verify_paths_do_not_have_old_cli_attribute_error(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(driver.main(["--verify", "--run-dir", str(self.bundle)]), 2)
            self.assertEqual(driver.main(["--analyse", "--run-dir", str(self.bundle)]), 2)
            self.assertEqual(driver.main(["--resume", "--run-dir", str(self.bundle)]), 2)


class CompletedEvidenceTests(MatrixFixture):
    def test_offline_end_to_end_complete(self):
        report = self.complete()
        self.assertTrue(report["execution_verified"])
        self.assertEqual(report["request_reconstruction"]["bodies_checked"], 16)
        self.assertEqual(len(report["request_reconstruction"]["cells"]), 8)
        self.assertTrue((self.bundle / "execution.freeze.json").is_file())

    def test_empty_formal_predictions_never_pass(self):
        self.complete()
        for protocol in contract.PROTOCOLS:
            for label in contract.CONDITIONS.values():
                for name in ("predictions.jsonl", "attempts.jsonl", "responses.jsonl"):
                    (self.bundle / protocol / label / name).write_text("", encoding="utf-8")
        report = self.assert_rejected()
        self.assertEqual(report["request_reconstruction"]["bodies_checked"], 0)

    def test_one_missing_question_rejected(self):
        self.complete()
        directory = self.prediction_path().parent
        identity = contract.read_rows(self.prediction_path())[0]["job_id"]
        for name in ("predictions.jsonl", "attempts.jsonl", "responses.jsonl"):
            path = directory / name
            self.rewrite(path, [row for row in contract.read_rows(path) if row["job_id"] != identity])
        self.assert_rejected()

    def test_duplicate_prediction_rejected(self):
        self.complete()
        rows = contract.read_rows(self.prediction_path())
        self.rewrite(self.prediction_path(), rows + rows[:1])
        self.assert_rejected()

    def test_unknown_id_rejected(self):
        self.complete()
        rows = contract.read_rows(self.prediction_path())
        rows[0]["id"] = "unknown"
        rows[0]["job_id"] = "prefill|A|unknown"
        self.rewrite(self.prediction_path(), rows)
        self.assert_rejected()

    def test_body_hash_mismatch_rejected(self):
        self.complete()
        rows = contract.read_rows(self.prediction_path())
        rows[0]["body_wire_sha256"] = "0" * 64
        self.rewrite(self.prediction_path(), rows)
        self.assert_rejected()

    def test_repaired_assembly_rejected(self):
        self.complete()
        rows = contract.read_rows(self.prediction_path())
        rows[0]["completed_answer"] = "[1, 2]"
        self.rewrite(self.prediction_path(), rows)
        self.assert_rejected()

    def test_raw_response_and_payload_disagreement_rejected(self):
        self.complete()
        path = self.prediction_path().parent / "responses.jsonl"
        rows = contract.read_rows(path)
        rows[0]["payload"]["choices"][0]["message"]["content"] = "1, 2]"
        self.rewrite(path, rows)
        self.assert_rejected()

    def test_metadata_cannot_be_invented(self):
        self.complete()
        rows = contract.read_rows(self.prediction_path())
        rows[0]["usage"] = {"completion_tokens": 0}
        self.rewrite(self.prediction_path(), rows)
        self.assert_rejected()

    def test_http_failure_with_legal_list_scores_zero(self):
        result = contract.score_response(http_result("2, 1]", status=401), "prefill", 2)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["strict_permutation"])
        self.assertEqual(result["extract_status"], "zero")

    def test_truncated_closed_list_does_not_pass_format_gate(self):
        self.complete()
        self.change_final_response(lambda response: response["payload"]["choices"][0].update(finish_reason="length"))
        report = verify(self.bundle, workspace=self.workspace)
        self.assertTrue(report["ok"], report["errors"])
        cell = report["request_reconstruction"]["cells"]["prefill/A"]
        self.assertFalse(cell["format_gate_passed"])
        self.assertEqual(cell["truncated"], 1)
        self.assertEqual(cell["extractable"], 1)

    def test_prefix_echo_blocks_formal_execution(self):
        def echo(url, wire, key, timeout):
            return http_result("[2, 1]")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(contract.IntegrityError, "compatibility"):
            driver.execute(self.bundle, workspace=self.workspace, transport=echo, sleeper=lambda _: None,
                           key_reader=lambda: "offline-placeholder")
        self.assertFalse((self.bundle / "execution.freeze.json").exists())
        self.assertFalse(self.prediction_path().exists())

    def test_control_format_errors_are_measured_and_not_retried(self):
        calls = []
        def format_control(url, wire, key, timeout):
            calls.append(wire)
            prefix = json.loads(wire)["messages"][-1]["role"] == "assistant"
            return http_result("2, 1]" if prefix else "Reasoning first. [2, 1]")
        report = self.complete(format_control)
        self.assertEqual(len(calls), 24)  # 8 compatibility + 16 formal, all simulated.
        self.assertFalse(report["request_reconstruction"]["cells"]["no_prefill/A"]["format_gate_passed"])
        self.assertTrue(report["request_reconstruction"]["cells"]["prefill/A"]["format_gate_passed"])

    def test_transient_retry_keeps_all_attempts(self):
        calls = []
        def transient(url, wire, key, timeout):
            calls.append(wire)
            return http_result("temporary", status=503) if len(calls) == 1 else mock_http(url, wire, key, timeout)
        self.complete(transient)
        self.assertEqual(len(calls), 25)
        attempts = contract.read_rows(self.bundle / "smoke/no_prefill/A_full_image/attempts.jsonl")
        self.assertEqual([row["http_status"] for row in attempts], [503, 200])

    def test_resume_never_replays_terminal_answers_or_reads_key_when_complete(self):
        self.complete()
        http = Mock()
        key = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            report = driver.execute(self.bundle, workspace=self.workspace, resume=True, transport=http,
                                    sleeper=lambda _: None, key_reader=key)
        self.assertTrue(report["ok"])
        http.assert_not_called()
        key.assert_not_called()

    def test_interruption_leaves_inflight_and_resume_does_not_resend(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            driver.execute(self.bundle, workspace=self.workspace, transport=Mock(side_effect=RuntimeError("interrupted")),
                           sleeper=lambda _: None, key_reader=lambda: "offline-placeholder")
        self.assertTrue((self.bundle / "inflight.json").exists())
        http = Mock()
        key = Mock()
        with self.assertRaises(contract.IntegrityError):
            driver.execute(self.bundle, workspace=self.workspace, resume=True, transport=http, key_reader=key)
        http.assert_not_called()
        key.assert_not_called()


class RealDataOfflineAnalysis(MatrixFixture):
    def test_standard_evaluator_consumes_new_driver_predictions_on_exact_subset(self):
        source = driver.SOURCE_RUN / "inputs"
        a = [row for row in contract.read_rows(source / "dev.jsonl") if row["type"] == "forward_world_modeling_3_steps"][:2]
        ids = {row["id"] for row in a}
        b = [row for row in contract.read_rows(source / "dev_B.jsonl") if row["id"] in ids]
        d = [row for row in contract.read_rows(driver.BASE / "_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl") if row["id"] in ids]
        bundle = self.root / "real_subset"
        contract.create_bundle(bundle, self.workspace, driver.DATA_ROOT, {"A": a, "B": b, "C": a, "D": d}, self.decode, scope="fixture")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.execute(bundle, workspace=self.workspace, transport=mock_http, sleeper=lambda _: None,
                           key_reader=lambda: "offline-placeholder")
            result = driver.analyse(bundle, workspace=self.workspace)
        self.assertEqual(len(result["metrics"]), 8)
        for metric in result["metrics"].values():
            self.assertEqual(metric["N"], 2)
            self.assertEqual(metric["primary"]["count"], 2)


if __name__ == "__main__":
    unittest.main()

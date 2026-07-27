from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import (
    APPROVAL_EVIDENCE_RULE,
    EXECUTOR_IDENTITY_RULE,
    MODEL_NAMING_RULE,
    READINESS_EVIDENCE_RULE,
    build_coding_delegation_payload,
    coding_delegation_record_payload,
)
from omh.executors import (
    CODING_EXECUTOR_HANDOFF_TARGETS,
    CODING_RUNTIME_HANDOFF_TARGETS,
    EXECUTOR_PROFILES,
    PROMPT_ONLY_EXECUTOR_PROFILES,
)
from omh.paths import resolve_paths
from omh.runtime_artifacts import (
    PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX,
    create_prepared_coding_delegation_run,
    validate_runtime,
    write_coding_delegation,
)
from omh.wrapper_sessions import (
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DOC = REPO_ROOT / "docs" / "ARCHITECTURE.md"
MESSAGE = "risky refactor"


def _run_errors(paths, run_id: str) -> str:
    return json.dumps(validate_runtime(paths, run_id))


def _store_delegation_as_prepared_run(paths, executor_target: str) -> str:
    run = create_prepared_coding_delegation_run(paths, {"skill": "ai-slop-cleaner", "harness": "coding-handling"})
    run_dir = paths.runtime_runs_dir / run["run_id"]
    payload = build_coding_delegation_payload(MESSAGE, source="discord", executor_target=executor_target)
    write_coding_delegation(run_dir, coding_delegation_record_payload(payload, MESSAGE))
    return str(run["run_id"])


class PreparedRuntimeRunExecutorMatrixTests(unittest.TestCase):
    def test_executor_profiles_partition_into_exactly_one_handoff_lane(self) -> None:
        lanes = (CODING_EXECUTOR_HANDOFF_TARGETS, PROMPT_ONLY_EXECUTOR_PROFILES, CODING_RUNTIME_HANDOFF_TARGETS)
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile):
                self.assertEqual(sum(profile in lane for lane in lanes), 1)
        self.assertEqual(
            sorted(EXECUTOR_PROFILES),
            sorted([*CODING_EXECUTOR_HANDOFF_TARGETS, *PROMPT_ONLY_EXECUTOR_PROFILES, *CODING_RUNTIME_HANDOFF_TARGETS]),
        )

    def test_matrix_message_names_every_executor_profile(self) -> None:
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile):
                self.assertIn(profile, PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX)
        self.assertIn("external_executor", PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX)

    def test_architecture_doc_states_the_supported_executor_matrix(self) -> None:
        doc = ARCHITECTURE_DOC.read_text(encoding="utf-8")
        self.assertIn("Prepared Runtime Run Executor Matrix", doc)
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile):
                self.assertIn(f"`{profile}`", doc)
        for mode in ("external_executor", "prompt_only_handoff", "runtime_handoff"):
            with self.subTest(mode=mode):
                self.assertIn(f"`{mode}`", doc)

    def test_prepared_run_accepts_every_run_backed_executor_profile(self) -> None:
        for profile in CODING_EXECUTOR_HANDOFF_TARGETS:
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                run_id = _store_delegation_as_prepared_run(paths, profile)

                result = validate_runtime(paths, run_id)

                self.assertTrue(result["ok"], result)
                run = json.loads((paths.runtime_runs_dir / run_id / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(run["observation_status"], "prepared_not_observed")

    def test_prepared_run_rejects_every_non_run_backed_executor_profile(self) -> None:
        rejected = [profile for profile in EXECUTOR_PROFILES if profile not in CODING_EXECUTOR_HANDOFF_TARGETS]
        self.assertTrue(rejected)
        for profile in rejected:
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                run_id = _store_delegation_as_prepared_run(paths, profile)

                result = validate_runtime(paths, run_id)
                errors = "\n".join(result["runs"][0]["errors"])

                self.assertFalse(result["ok"])
                self.assertIn(PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX, errors)
                for supported in CODING_EXECUTOR_HANDOFF_TARGETS:
                    self.assertIn(supported, errors)

    def test_prepared_run_rejects_pending_executor_choice_with_matrix_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _store_delegation_as_prepared_run(paths, "choose")

            result = validate_runtime(paths, run_id)
            errors = "\n".join(result["runs"][0]["errors"])

            self.assertFalse(result["ok"])
            self.assertIn("executor choice must not be stored as a prepared runtime run", errors)
            self.assertIn(
                "prepared runtime run rejected because selected_executor_profile None "
                "has no run-backed executor handoff lifecycle",
                errors,
            )
            self.assertIn(PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX, errors)

    def test_prompt_only_and_runtime_profiles_report_their_own_lane_in_the_rejection(self) -> None:
        expectations = {
            **{
                profile: ("prompt-only handoff must not be stored as a prepared runtime run", "prompt_only_handoff")
                for profile in PROMPT_ONLY_EXECUTOR_PROFILES
            },
            **{
                profile: ("runtime handoff must not be stored as a prepared runtime run", "runtime_handoff")
                for profile in CODING_RUNTIME_HANDOFF_TARGETS
            },
        }
        for profile, (lane_message, mode) in expectations.items():
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                run_id = _store_delegation_as_prepared_run(paths, profile)

                errors = "\n".join(validate_runtime(paths, run_id)["runs"][0]["errors"])

                self.assertIn(lane_message, errors)
                self.assertIn(f"prepared runtime run rejected because work_owner_mode '{mode}' is not external_executor", errors)

    def test_wrapper_session_handoff_creates_a_run_only_for_run_backed_profiles(self) -> None:
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                started = create_or_resume_wrapper_session(paths, MESSAGE, source="discord")
                session_id = str(started["session"]["session_id"])
                record_plan_decision(paths, session_id, "accept")
                select_wrapper_session_executor(paths, session_id, profile)

                prepared = prepare_wrapper_session_handoff(paths, session_id, MESSAGE)

                run_created = bool(prepared["session"]["current_run_id"])
                self.assertEqual(run_created, profile in CODING_EXECUTOR_HANDOFF_TARGETS)
                self.assertTrue(validate_runtime(paths)["ok"], validate_runtime(paths))
                if run_created:
                    run_id = str(prepared["session"]["current_run_id"])
                    run = json.loads((paths.runtime_runs_dir / run_id / "run.json").read_text(encoding="utf-8"))
                    self.assertEqual(run["observation_status"], "prepared_not_observed")
                    self.assertEqual(run["artifact_kind"], "prepared_coding_delegation")

    def test_linked_session_rejects_a_non_run_backed_executor_target(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id, run_id = _prepare_linked_codex_session(paths)
            coding_path = paths.runtime_runs_dir / run_id / "coding_delegation.json"
            coding = json.loads(coding_path.read_text(encoding="utf-8"))
            coding["executor_handoff"]["executor_target"] = "claude-code"
            coding_path.write_text(json.dumps(coding, indent=2, sort_keys=True), encoding="utf-8")

            report = _run_errors(paths, run_id)

            self.assertIn("has no run-backed executor handoff lifecycle", report)
            self.assertIn(PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX, report)
            self.assertIn(session_id, report)

    def test_linked_session_rejects_a_missing_executor_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _, run_id = _prepare_linked_codex_session(paths)
            coding_path = paths.runtime_runs_dir / run_id / "coding_delegation.json"
            coding = json.loads(coding_path.read_text(encoding="utf-8"))
            del coding["executor_handoff"]
            coding_path.write_text(json.dumps(coding, indent=2, sort_keys=True), encoding="utf-8")

            report = _run_errors(paths, run_id)

            self.assertIn("linked run must include an executor_handoff for a run-backed executor profile", report)
            self.assertIn(PREPARED_RUNTIME_RUN_EXECUTOR_MATRIX, report)

    def test_accepted_run_backed_handoff_stays_prepared_not_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _, run_id = _prepare_linked_codex_session(paths)
            run_dir = paths.runtime_runs_dir / run_id

            self.assertTrue(validate_runtime(paths, run_id)["ok"])
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            coding = json.loads((run_dir / "coding_delegation.json").read_text(encoding="utf-8"))
            self.assertEqual(run["observation_status"], "prepared_not_observed")
            self.assertEqual(coding["status"], "prepared_not_observed")
            self.assertEqual(coding["executor_handoff"]["status"], "prepared_not_observed")
            self.assertFalse((run_dir / "delegation.json").exists())
            self.assertFalse((run_dir / "wrapper.json").exists())


class CodingDelegationGuidanceRulesTests(unittest.TestCase):
    """Pin the shared guardrail fields added after one live Slack session went wrong three ways in a
    row, plus a fourth failure caught the same session: a compaction resume was read as approval, status
    copy never named which executor/model ran, a retry suggestion invented a model name from memory, and
    `which codex` plus an auth file on disk were read as "ready" for a run that then failed. The fields
    must live once on the shared payload (not copied per executor-target handoff builder) so every
    executor target carries the identical guardrail text."""

    def test_all_four_rules_are_present_on_every_executor_targets_payload(self) -> None:
        for profile in EXECUTOR_PROFILES:
            with self.subTest(profile=profile):
                payload = build_coding_delegation_payload(MESSAGE, source="discord", executor_target=profile)

                self.assertEqual(payload["approval_evidence_rule"], APPROVAL_EVIDENCE_RULE)
                self.assertEqual(payload["executor_identity_rule"], EXECUTOR_IDENTITY_RULE)
                self.assertEqual(payload["model_naming_rule"], MODEL_NAMING_RULE)
                self.assertEqual(payload["readiness_evidence_rule"], READINESS_EVIDENCE_RULE)

    def test_approval_evidence_rule_names_compaction_as_never_approval(self) -> None:
        self.assertIn("compaction", APPROVAL_EVIDENCE_RULE)
        self.assertIn("is never approval", APPROVAL_EVIDENCE_RULE)

    def test_model_naming_rule_forbids_naming_a_model_from_memory(self) -> None:
        self.assertIn("Never name a concrete model from memory", MODEL_NAMING_RULE)

    def test_readiness_evidence_rule_rejects_path_and_auth_file_as_run_evidence(self) -> None:
        self.assertIn("PATH", READINESS_EVIDENCE_RULE)
        self.assertIn("auth file", READINESS_EVIDENCE_RULE)
        self.assertIn("are not run evidence", READINESS_EVIDENCE_RULE)

    def test_approval_rule_in_session_observation_contracts_names_compaction(self) -> None:
        codex_handoff = build_coding_delegation_payload(MESSAGE, source="discord", executor_target="codex")["executor_handoff"]
        claude_code_handoff = build_coding_delegation_payload(MESSAGE, source="discord", executor_target="claude-code")["prompt_handoff"]

        self.assertIn("compaction", codex_handoff["session_observation_contract"]["approval_rule"])
        self.assertIn("compaction", claude_code_handoff["session_observation_contract"]["approval_rule"])


def _prepare_linked_codex_session(paths) -> tuple[str, str]:
    started = create_or_resume_wrapper_session(paths, MESSAGE, source="discord")
    session_id = str(started["session"]["session_id"])
    record_plan_decision(paths, session_id, "accept")
    select_wrapper_session_executor(paths, session_id, "codex")
    prepared = prepare_wrapper_session_handoff(paths, session_id, MESSAGE)
    return session_id, str(prepared["session"]["current_run_id"])


if __name__ == "__main__":
    unittest.main()

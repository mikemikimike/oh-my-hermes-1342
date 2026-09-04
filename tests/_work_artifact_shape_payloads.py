"""Shared session payloads for the work-artifact shape-surface tests.

Not a test module: it exists so the listing and show-action case modules build
their ``wrapper_session_result/v1`` fixtures from one place, mirroring the
persisted shape a prepared runtime handoff session really produces.
"""

from __future__ import annotations

import copy
import unittest

from _local_package import load_local_package

load_local_package()

from omh.wrapper.briefing import build_coding_briefing


RUNTIME_HANDOFF = {
    "schema_version": "coding_runtime_handoff/v1",
    "work_owner_mode": "runtime_handoff",
    "selected_executor_profile": "claude-code",
    "runtime_profile": {
        "profile": "claude-code",
        "label": "Claude Code",
        "runtime_family": "claude",
        "underlying_agent": "claude",
        "supports_team_swarm": True,
        "supports_tmux_workers": True,
        "supports_worker_protocol": True,
        "supports_worktree_guidance": True,
        "supports_hermes_coding_team_path": False,
        "requires_operator_runtime": True,
    },
    "dispatchable": False,
    "status": "prepared_not_observed",
    "recording_contract": "runtime_prepared_not_started",
    "dispatch_contract": "wrapper_or_user_starts_runtime; omh_does_not_execute_runtime",
    "observation_contract": {
        "record_schema": "runtime_observation/v1",
        "allowed_events": ["runtime_start", "worker_result"],
    },
    "runtime_brief": {
        "runtime_owns": [
            "repository inspection when coding is selected",
            "team or swarm lane creation when the task is safely splittable",
            "tmux-style worker or pane coordination when the chosen runtime supports it",
            "worker ACK/claim/result discipline",
            "worktree isolation when parallel, risky, or multi-file coding starts",
            "verification evidence reporting",
        ],
    },
    "prompt_template": "Implement {message}.",
}

PROMPT_HANDOFF = {
    "schema_version": "coding_prompt_handoff/v1",
    "selected_executor_profile": "claude-code",
    "prompt_template": "Implement the export surface for {message}.",
    "acceptance_criteria": ["Stable ids"],
    "verification": ["unittest tests/test_work_artifact_show_shape_action.py"],
}


class WorkArtifactShapeSessionPayloads(unittest.TestCase):
    """Fixture base: builds status payloads for one prepared wrapper session."""

    SESSION_ID = "wsession-shape"

    def _status_payload(
        self,
        *,
        runtime_handoff: dict | None = None,
        prompt_handoff: dict | None = None,
        briefing: dict | None = None,
    ) -> dict[str, object]:
        session = {
            "session_id": self.SESSION_ID,
            "thread_key": "discord:shape",
            "source": "discord",
            "status": "runtime_handoff_prepared",
            "selected_executor_profile": "claude-code",
            "plan": {"status": "accepted", "recommended_workflow": "ultrawork"},
            "runtime_handoff": runtime_handoff if runtime_handoff is not None else {},
            "prompt_handoff": prompt_handoff if prompt_handoff is not None else {},
        }
        return {
            "schema_version": "wrapper_session_result/v1",
            "session_id": self.SESSION_ID,
            "session_status": "runtime_handoff_prepared",
            "prompt_handoff": prompt_handoff if prompt_handoff is not None else {},
            "runtime_handoff": runtime_handoff if runtime_handoff is not None else {},
            "coding_briefing": briefing
            if briefing is not None
            else build_coding_briefing(session),
        }

    def _runtime_handoff_status(self, **overrides: object) -> dict[str, object]:
        handoff = copy.deepcopy(RUNTIME_HANDOFF)
        handoff.update(overrides)
        return handoff

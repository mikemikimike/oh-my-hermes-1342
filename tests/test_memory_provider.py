"""OMH's memory blocks, dreaming scheduler, eviction plan, and Hermes provider.

The defect these close is that everything OMH knew about memory had to be asked
for. Hermes wrote its own memory after every turn through
``agent/background_review.py`` with no statement of what OMH already held, and
OMH could only notice afterwards that some entry matched no record it kept.

Three boundaries are load-bearing enough to be pinned here rather than described:

- A block value is OMH's own content and is returned in full. A Hermes memory
  entry is not, and never appears outside a count or a hash.
- The provider never runs consolidation. It decides that consolidation is due
  and writes a brief; a model does the rest.
- The provider is not permitted to take a memory-provider slot another product
  holds, because Hermes runs exactly one.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.install.config_adapter import (
    clear_memory_provider,
    memory_provider_selection,
    set_memory_provider,
)
from omh.plugin_bundle.omh import register
from omh.plugin_bundle.omh.memory_blocks import (
    DEFAULT_BLOCK_LIMIT_CHARS,
    MemoryBlockError,
    build_memory_block,
    delete_memory_block,
    read_memory_block,
    read_memory_blocks,
    render_block_index,
    render_memory_blocks,
    write_memory_block,
)
from omh.plugin_bundle.omh.memory_dreaming import (
    DEFAULT_TURN_INTERVAL,
    clear_after_consolidation,
    consolidation_reasons,
    empty_dreaming_state,
    read_dreaming_state,
    read_latest_consolidation,
    record_compaction,
    record_memory_write,
    record_turn,
    write_dreaming_state,
)
from omh.plugin_bundle.omh.memory_eviction import build_eviction_plan, eviction_plan_summary
from omh.plugin_bundle.omh.memory_provider import PROVIDER_NAME, OmhMemoryProvider
from omh.plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from omh.plugin_bundle.omh.tools.memory_tool import MEMORY_ACTIONS, OMH_MEMORY_SCHEMA, omh_memory_handler

HERMES_DELIMITER = "§"


def _write_hermes_memory(hermes_home: Path, *entries: str) -> Path:
    path = hermes_home / "memories" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HERMES_DELIMITER.join(entries), encoding="utf-8")
    return path


class BlockStoreTests(unittest.TestCase):
    def test_a_block_round_trips_through_disk(self) -> None:
        with TemporaryDirectory() as tmp:
            block = build_memory_block("project-facts", "OMH wraps Hermes.", description="Facts.")
            write_memory_block(tmp, block)
            self.assertEqual(read_memory_blocks(tmp), (block,))

    def test_an_over_limit_block_is_rejected_rather_than_truncated(self) -> None:
        # Truncating would make the store disagree with what the caller believes
        # it wrote, and the disagreement only shows up as a missing sentence later.
        with self.assertRaises(MemoryBlockError):
            build_memory_block("facts", "x" * 51, limit=50)

    def test_labels_are_constrained_because_they_name_files(self) -> None:
        for label in ("", "Has Caps", "../escape", "-leading", "a" * 64):
            with self.subTest(label=label), self.assertRaises(MemoryBlockError):
                build_memory_block(label, "value")

    def test_an_unknown_tier_is_rejected(self) -> None:
        with self.assertRaises(MemoryBlockError):
            build_memory_block("facts", "value", tier="archival")

    def test_blocks_are_read_in_label_order_so_a_render_is_reproducible(self) -> None:
        with TemporaryDirectory() as tmp:
            for label in ("zulu", "alpha", "mike"):
                write_memory_block(tmp, build_memory_block(label, "v"))
            self.assertEqual([block.label for block in read_memory_blocks(tmp)], ["alpha", "mike", "zulu"])

    def test_tiers_are_stored_and_listed_separately(self) -> None:
        with TemporaryDirectory() as tmp:
            write_memory_block(tmp, build_memory_block("always", "v", tier="system"))
            write_memory_block(tmp, build_memory_block("sometimes", "v", tier="reference"))
            self.assertEqual([b.label for b in read_memory_blocks(tmp, tier="system")], ["always"])
            self.assertEqual([b.label for b in read_memory_blocks(tmp, tier="reference")], ["sometimes"])
            self.assertEqual(len(read_memory_blocks(tmp)), 2)

    def test_an_unreadable_block_is_absent_rather_than_fatal(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory" / "blocks" / "system" / "broken.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(read_memory_block(path))
            self.assertEqual(read_memory_blocks(tmp), ())

    def test_removing_a_block_reports_whether_it_was_there(self) -> None:
        with TemporaryDirectory() as tmp:
            write_memory_block(tmp, build_memory_block("facts", "v"))
            self.assertTrue(delete_memory_block(tmp, "facts", "system"))
            self.assertFalse(delete_memory_block(tmp, "facts", "system"))


class RenderTests(unittest.TestCase):
    def test_a_render_shows_the_model_how_full_each_block_is(self) -> None:
        block = build_memory_block("facts", "abc", description="What we know.", limit=100)
        rendered = render_memory_blocks([block])
        self.assertIn("<memory_blocks>", rendered)
        self.assertIn("chars_current=3 chars_limit=100", rendered)
        self.assertIn("<value>abc</value>", rendered)

    def test_an_empty_store_renders_nothing_at_all(self) -> None:
        self.assertEqual(render_memory_blocks([]), "")
        self.assertEqual(render_block_index([]), "")

    def test_the_budget_drops_whole_blocks_and_says_which(self) -> None:
        # A clipped block would read as something the store actually holds.
        blocks = [build_memory_block(f"b{index}", "x" * 200) for index in range(5)]
        rendered = render_memory_blocks(blocks, budget_chars=400)
        self.assertIn("render_budget_exhausted", rendered)
        self.assertIn("b4", rendered)
        self.assertNotIn("<b4>", rendered)

    def test_the_index_lists_reference_blocks_without_their_values(self) -> None:
        block = build_memory_block("runbook", "SECRET-VALUE", description="How to deploy.", tier="reference")
        index = render_block_index([block])
        self.assertIn('label="runbook"', index)
        self.assertIn("How to deploy.", index)
        self.assertNotIn("SECRET-VALUE", index)


class DreamingScheduleTests(unittest.TestCase):
    def test_counters_round_trip_and_survive_a_corrupt_file(self) -> None:
        with TemporaryDirectory() as tmp:
            write_dreaming_state(tmp, record_turn(empty_dreaming_state()))
            self.assertEqual(read_dreaming_state(tmp)["turns_since_consolidation"], 1)
            (Path(tmp) / "memory" / "dreaming.json").write_text("{", encoding="utf-8")
            self.assertEqual(read_dreaming_state(tmp), empty_dreaming_state())

    def test_the_turn_interval_is_the_baseline_trigger(self) -> None:
        state = empty_dreaming_state()
        for _ in range(DEFAULT_TURN_INTERVAL - 1):
            state = record_turn(state)
        self.assertEqual(consolidation_reasons(state), [])
        state = record_turn(state)
        self.assertTrue(any(reason.startswith("turn_interval_reached") for reason in consolidation_reasons(state)))

    def test_compaction_triggers_consolidation_on_its_own(self) -> None:
        reasons = consolidation_reasons(record_compaction(empty_dreaming_state()))
        self.assertIn("context_compaction_observed", reasons)

    def test_low_headroom_triggers_before_the_file_is_full(self) -> None:
        reasons = consolidation_reasons(empty_dreaming_state(), headroom_chars=100, headroom_floor_chars=300)
        self.assertTrue(any(reason.startswith("headroom_below_floor") for reason in reasons))

    def test_reasons_are_named_so_a_brief_can_state_its_own_cause(self) -> None:
        reasons = consolidation_reasons(record_compaction(empty_dreaming_state()), duplicate_count=2)
        self.assertIn("context_compaction_observed", reasons)
        self.assertIn("duplicate_records:2", reasons)

    def test_mode_off_silences_every_trigger(self) -> None:
        state = record_compaction(empty_dreaming_state())
        self.assertEqual(consolidation_reasons(state, mode="off", headroom_chars=0), [])

    def test_memory_writes_are_counted_separately_from_turns(self) -> None:
        state = record_memory_write(record_turn(empty_dreaming_state()))
        self.assertEqual(state["turns_since_consolidation"], 1)
        self.assertEqual(state["memory_writes_observed"], 1)


class StandingConditionSuppressionTests(unittest.TestCase):
    """A condition nobody can clear must not be reported on every turn.

    Observed on a live install: 19 consecutive briefs, every one of them reading
    `headroom_below_floor:289<=300`. Turn counts and compaction flags clear
    themselves by firing; headroom clears only when somebody consolidates, and
    OMH cannot -- by design. So the condition re-fired forever and the journal
    filled with one repeated sentence.
    """

    HEADROOM = 289
    FLOOR = 300

    def test_a_standing_condition_is_reported_once_not_every_turn(self) -> None:
        state = empty_dreaming_state()
        fired = 0
        for _ in range(20):
            state = record_turn(state)
            reasons = consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR)
            if reasons:
                fired += 1
                state = clear_after_consolidation(state, at="t", reasons=reasons)
        # Once on the first turn, then only when the interval genuinely comes
        # due. Twenty briefs in twenty turns is what this replaced.
        self.assertEqual(fired, 4)

    def test_the_condition_still_rides_along_on_a_real_trigger(self) -> None:
        # Suppression must not hide it: a brief woken by the interval while
        # memory is nearly full should still say memory is nearly full.
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"headroom_below_floor:{self.HEADROOM}<={self.FLOOR}"]
        )
        for _ in range(DEFAULT_TURN_INTERVAL):
            state = record_turn(state)
        reasons = consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR)
        self.assertTrue(any(r.startswith("turn_interval_reached") for r in reasons))
        self.assertTrue(any(r.startswith("headroom_below_floor") for r in reasons))

    def test_a_changed_condition_fires_immediately(self) -> None:
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"headroom_below_floor:{self.HEADROOM}<={self.FLOOR}"]
        )
        self.assertEqual(consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR), [])
        self.assertTrue(consolidation_reasons(state, headroom_chars=self.HEADROOM - 40, headroom_floor_chars=self.FLOOR))

    def test_duplicate_and_expiry_counts_are_conditions_too(self) -> None:
        for reason, kwargs in (
            ("duplicate_records:2", {"duplicate_count": 2}),
            ("expiring_records:3", {"expiring_count": 3}),
        ):
            with self.subTest(reason=reason):
                state = clear_after_consolidation(empty_dreaming_state(), at="t", reasons=[reason])
                self.assertEqual(consolidation_reasons(state, **kwargs), [])

    def test_every_event_reason_may_fire_again_at_once(self) -> None:
        # These describe a moment, and the moment happened again.
        compaction = clear_after_consolidation(empty_dreaming_state(), at="t", reasons=["context_compaction_observed"])
        self.assertIn("context_compaction_observed", consolidation_reasons(record_compaction(compaction)))

        turns = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"turn_interval_reached:{DEFAULT_TURN_INTERVAL}/{DEFAULT_TURN_INTERVAL}"]
        )
        for _ in range(DEFAULT_TURN_INTERVAL):
            turns = record_turn(turns)
        self.assertTrue(any(r.startswith("turn_interval_reached") for r in consolidation_reasons(turns)))

    def test_a_session_ending_still_reports_its_unconsolidated_turns(self) -> None:
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=["session_ending_with_unconsolidated_turns:3"]
        )
        state = record_turn(record_turn(record_turn(state)))
        reasons = consolidation_reasons(state, session_ending=True)
        self.assertIn("session_ending_with_unconsolidated_turns:3", reasons)

    def test_the_provider_stops_rewriting_the_same_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            journal = root / ".omh" / "memory" / "consolidation.jsonl"

            for turn in range(1, DEFAULT_TURN_INTERVAL):
                provider.on_turn_start(turn, "hi")
            # One brief from `initialize`; the standing condition adds no more
            # until the interval genuinely comes due.
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 1)


class EvictionPlanTests(unittest.TestCase):
    def test_rewordings_of_one_fact_group_into_a_single_cluster(self) -> None:
        entries = (
            "document-harness는 sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템이다",
            "document-harness: sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템",
            "커피 원두는 밀봉 용기에 보관한다",
        )
        plan = build_eviction_plan(entries, cap=2200)
        self.assertEqual(len(plan["duplicate_clusters"]), 1)
        self.assertEqual(plan["duplicate_clusters"][0]["entry_indices"], [0, 1])
        self.assertGreater(plan["reclaimable_chars"], 0)

    def test_distinct_entries_produce_no_cluster(self) -> None:
        plan = build_eviction_plan(("release 스크립트 dry-run", "커피 원두 보관"), cap=2200)
        self.assertEqual(plan["duplicate_clusters"], [])
        self.assertEqual(plan["reclaimable_chars"], 0)

    def test_a_shortfall_counts_the_delimiter_the_write_will_cost(self) -> None:
        plan = build_eviction_plan(("x" * 90,), cap=100, required_chars=10)
        # 90 used, 10 free, and the write needs 10 + 1 for the delimiter.
        self.assertEqual(plan["headroom_chars"], 10)
        self.assertEqual(plan["required_chars"], 11)
        self.assertEqual(plan["shortfall_chars"], 1)

    def test_a_plan_that_cannot_free_enough_says_so(self) -> None:
        plan = build_eviction_plan(("x" * 99,), cap=100, required_chars=500)
        self.assertFalse(plan["sufficient"])
        self.assertIn("provably redundant", eviction_plan_summary(plan))

    def test_an_unexplained_entry_is_never_an_eviction_candidate(self) -> None:
        # Unexplained is a reason to ask, not a reason to delete.
        plan = build_eviction_plan(("a fact nothing in OMH explains",), cap=2200)
        self.assertTrue(plan["unexplained_entries_are_not_candidates"])
        self.assertEqual(plan["duplicate_clusters"], [])

    def test_the_plan_carries_no_entry_text(self) -> None:
        secret = "루트 비밀번호는 hunter2 이다"
        plan = build_eviction_plan((secret, secret + " 확실히"), cap=2200)
        self.assertNotIn("hunter2", json.dumps(plan, ensure_ascii=False))


class ProviderRegistrationTests(unittest.TestCase):
    class _Collector:
        """Mirrors Hermes' `_ProviderCollector`: one real method, the rest no-ops."""

        def __init__(self) -> None:
            self.provider = None
            self.tools: list[str] = []

        def register_memory_provider(self, provider) -> None:
            self.provider = provider

        def register_tool(self, *args, **kwargs) -> None:
            self.tools.append(args[0] if args else "")

        def register_hook(self, *args, **kwargs) -> None:
            pass

    class _PluginCtx:
        """Mirrors the real Hermes plugin context, which has no provider method."""

        def __init__(self) -> None:
            self.tools: list[str] = []
            self.hooks: list[str] = []

        def register_tool(self, name, *args, **kwargs) -> None:
            self.tools.append(name)

        def register_hook(self, name, callback) -> None:
            self.hooks.append(name)

    def test_the_memory_loader_gets_a_provider_and_no_tools(self) -> None:
        collector = self._Collector()
        register(collector)
        self.assertIsInstance(collector.provider, OmhMemoryProvider)
        # Registering ten tools into a collector that discards them is work the
        # provider load should never do.
        self.assertEqual(collector.tools, [])

    def test_the_plugin_loader_still_gets_every_tool_and_hook(self) -> None:
        ctx = self._PluginCtx()
        register(ctx)
        self.assertIn("omh_memory", ctx.tools)
        self.assertEqual(len(ctx.tools), 10)
        self.assertIn("on_session_end", ctx.hooks)

    def test_the_provider_exposes_no_tool_schemas(self) -> None:
        # `agent/memory_provider.py` names tool-schema bloat as the reason only
        # one external provider may run; the block read lives on `omh_memory`.
        self.assertEqual(OmhMemoryProvider().get_tool_schemas(), [])

    def test_the_provider_name_matches_what_config_must_carry(self) -> None:
        self.assertEqual(OmhMemoryProvider().name, MEMORY_PROVIDER_NAME)
        self.assertEqual(PROVIDER_NAME, MEMORY_PROVIDER_NAME)


class ProviderLifecycleTests(unittest.TestCase):
    def _provider(self, root: Path, *, agent_context: str = "primary") -> OmhMemoryProvider:
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("session-1", hermes_home=str(root / ".hermes"), agent_context=agent_context)
        return provider

    def test_availability_is_a_local_check_with_no_network(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(OmhMemoryProvider(root / "absent").is_available())
            (root / ".omh").mkdir()
            self.assertTrue(OmhMemoryProvider(root / ".omh").is_available())

    def test_prefetch_serves_a_pack_rendered_off_the_hot_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(root / ".omh", build_memory_block("facts", "OMH wraps Hermes."))
            provider = self._provider(root)
            self.assertIn("OMH wraps Hermes.", provider.prefetch("anything"))

            # A block written mid-session is not served until the next turn is
            # queued, which is where the base class puts the work.
            write_memory_block(root / ".omh", build_memory_block("later", "added mid-session"))
            self.assertNotIn("added mid-session", provider.prefetch(""))
            provider.queue_prefetch("")
            self.assertIn("added mid-session", provider.prefetch(""))

    def test_reference_blocks_reach_prefetch_as_labels_not_values(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(
                root / ".omh",
                build_memory_block("runbook", "SECRET-VALUE", description="How to deploy.", tier="reference"),
            )
            pack = self._provider(root).prefetch("")
            self.assertIn("runbook", pack)
            self.assertIn("How to deploy.", pack)
            self.assertNotIn("SECRET-VALUE", pack)

    def test_a_memory_write_is_journalled_without_its_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            secret = "루트 비밀번호는 hunter2 이다"
            provider.on_memory_write("add", "memory", secret, {"write_origin": "background_review"})

            journal = (root / ".omh" / "memory" / "write_journal.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("hunter2", journal)
            entry = json.loads(journal.splitlines()[0])
            self.assertEqual(entry["action"], "add")
            self.assertEqual(entry["chars"], len(secret))
            self.assertEqual(entry["write_origin"], "background_review")
            self.assertEqual(entry["redaction_policy"], "metadata_only")

    def test_a_non_primary_context_moves_no_counters(self) -> None:
        # Hermes states that cron and subagent contexts must not write; letting
        # them would move the counters that decide when consolidation is due.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root, agent_context="cron")
            provider.on_turn_start(1, "hello")
            provider.on_memory_write("add", "memory", "text")
            self.assertEqual(read_dreaming_state(root / ".omh"), empty_dreaming_state())

    def test_compaction_hands_back_system_blocks_and_consolidates_at_once(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(root / ".omh", build_memory_block("facts", "must survive compaction"))
            provider = self._provider(root)
            preserved = provider.on_pre_compress([{"role": "user", "content": "hi"}])

            self.assertIn("must survive compaction", preserved)
            # The flag is cleared because the brief was written here rather than
            # deferred; waiting would put it after the material it describes.
            self.assertFalse(read_dreaming_state(root / ".omh")["compaction_pending"])
            self.assertTrue((root / ".omh" / "memory" / "consolidation.json").exists())

    def test_consolidation_writes_a_brief_only_when_it_is_due(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            handoff_path = root / ".omh" / "memory" / "consolidation.json"

            self.assertFalse(provider.consolidation_due()["due"])
            self.assertFalse(handoff_path.exists())

            for turn in range(1, DEFAULT_TURN_INTERVAL + 1):
                provider.on_turn_start(turn, "hello")
            self.assertTrue(handoff_path.exists())
            # The interval fired on the turn itself and reset the counters, so
            # asking again straight after finds nothing further due.
            self.assertEqual(read_dreaming_state(root / ".omh")["turns_since_consolidation"], 0)
            self.assertFalse(provider.consolidation_due()["due"])

    def test_the_brief_never_claims_consolidation_happened(self) -> None:
        with TemporaryDirectory() as tmp:
            provider = self._provider(Path(tmp))
            boundary = str(provider.consolidation_due()["claim_boundary"])
            self.assertIn("not evidence", boundary)

    def test_headroom_pressure_reaches_the_scheduler_from_hermes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            self._provider(root)

            # The pressure is picked up by the evaluation `initialize` already
            # runs, so the brief exists before anything else asks. Asking again
            # finds the same standing condition suppressed rather than restated.
            brief = json.loads((root / ".omh" / "memory" / "consolidation.json").read_text(encoding="utf-8"))
            self.assertTrue(any(str(r).startswith("headroom_below_floor") for r in brief["reasons"]))
            self.assertEqual(brief["eviction_plan"]["cap"], 2200)

    def test_a_read_only_home_costs_a_journal_line_not_the_turn(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            with patch("omh.plugin_bundle.omh.memory_provider._append_line", side_effect=OSError("read-only")):
                provider.on_memory_write("add", "memory", "text")  # must not raise


class LossPreventionTests(unittest.TestCase):
    """The four moments memory can be lost, and that each one leaves a brief.

    The first implementation evaluated only at `on_session_end`. Turns and
    compaction set counters nobody read until then, so a laptop closed
    mid-session wrote nothing at all and a turn interval that came due at turn 5
    waited for whenever the session happened to stop. These pin the fix.
    """

    def _provider(self, root: Path, session: str = "s1") -> OmhMemoryProvider:
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize(session, hermes_home=str(root / ".hermes"), agent_context="primary")
        return provider

    def _briefs(self, root: Path) -> list[dict]:
        path = root / ".omh" / "memory" / "consolidation.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_the_turn_interval_fires_mid_session_not_at_the_end(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(self._briefs(root), [])

            provider.on_turn_start(DEFAULT_TURN_INTERVAL, "hi")
            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "turn")

    def test_the_interval_keeps_firing_on_every_further_cycle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL * 2 + 1):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(len(self._briefs(root)), 2)

    def test_compaction_writes_its_brief_before_the_messages_go(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_pre_compress([{"role": "user", "content": "x"}] * 40)

            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "compaction")
            self.assertEqual(briefs[0]["messages_at_risk"], 40)
            self.assertIn("about to discard", briefs[0]["requested_of_executor"][0])

    def test_shutdown_consolidates_even_below_the_interval(self) -> None:
        # Three turns and a closed lid would otherwise leave nothing behind: the
        # interval assumes a later turn, and a closing session has none.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, 4):
                provider.on_turn_start(turn, "hi")
            provider.shutdown()

            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "shutdown")
            self.assertIn("session_ending_with_unconsolidated_turns:3", briefs[0]["reasons"])

    def test_session_end_consolidates_even_below_the_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_session_end([])
            self.assertEqual(self._briefs(root)[0]["trigger"], "session_end")

    def test_a_session_that_died_is_settled_when_the_next_one_starts(self) -> None:
        # A killed process reaches no hook at all. The counters are on disk, so
        # the next startup is the first moment anything can act on them.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            died = self._provider(root, "dead-session")
            for turn in range(1, 4):
                died.on_turn_start(turn, "hi")
            self.assertEqual(self._briefs(root), [])
            del died

            self._provider(root, "next-session")
            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "session_start_recovery")
            self.assertIn("closed laptop", briefs[0]["requested_of_executor"][0])

    def test_a_clean_start_recovers_nothing_and_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._provider(root)
            self.assertEqual(self._briefs(root), [])

    def test_briefs_accumulate_so_an_earlier_one_is_never_overwritten(self) -> None:
        # The compaction brief describes material that is already gone; losing
        # it to a later shutdown brief would defeat the point.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_pre_compress([{"role": "user"}])
            provider.on_turn_start(2, "hi")
            provider.shutdown()

            triggers = [brief["trigger"] for brief in self._briefs(root)]
            self.assertEqual(triggers, ["compaction", "shutdown"])
            latest = json.loads((root / ".omh" / "memory" / "consolidation.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["trigger"], "shutdown")

    def test_a_fired_trigger_does_not_immediately_refire(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL + 1):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(len(self._briefs(root)), 1)
            provider.on_session_end([])
            self.assertEqual(len(self._briefs(root)), 1)

    def test_a_non_primary_context_never_writes_a_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("cron-1", hermes_home=str(root / ".hermes"), agent_context="cron")
            for turn in range(1, DEFAULT_TURN_INTERVAL + 2):
                provider.on_turn_start(turn, "hi")
            provider.on_pre_compress([{"role": "user"}])
            provider.shutdown()
            self.assertEqual(self._briefs(root), [])


class MemoryToolActionTests(unittest.TestCase):
    def _call(self, root: Path, **args) -> dict:
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(omh_memory_handler(args))

    def test_the_default_action_is_still_the_bridge(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = self._call(Path(tmp).resolve())
            self.assertEqual(payload["action"], "status")
            self.assertEqual(payload["schema_version"], "hermes_memory_bridge/v1")

    def test_every_advertised_action_is_handled(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for action in MEMORY_ACTIONS:
                with self.subTest(action=action):
                    self.assertEqual(self._call(root, action=action)["action"], action)

    def test_the_schema_advertises_exactly_the_handled_actions(self) -> None:
        enum = OMH_MEMORY_SCHEMA["parameters"]["properties"]["action"]["enum"]
        self.assertEqual(tuple(enum), MEMORY_ACTIONS)

    def test_blocks_lists_labels_and_read_returns_the_value(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_memory_block(root / ".omh", build_memory_block("runbook", "deploy steps", tier="reference"))

            listing = self._call(root, action="blocks")
            self.assertEqual(listing["block_count"], 1)
            self.assertNotIn("deploy steps", json.dumps(listing))

            read = self._call(root, action="read", label="runbook")
            self.assertTrue(read["found"])
            self.assertEqual(read["block"]["value"], "deploy steps")

    def test_a_missing_block_is_a_stated_miss_not_an_empty_value(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(self._call(root, action="read", label="absent")["reason"], "unknown_label")
            self.assertEqual(self._call(root, action="read")["reason"], "label_required")

    def test_an_unknown_action_names_what_is_supported(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = self._call(Path(tmp).resolve(), action="delete-everything")
            self.assertEqual(payload["status"], "unavailable")
            self.assertEqual(tuple(payload["supported_actions"]), MEMORY_ACTIONS)

    def test_hermes_entry_text_still_never_reaches_the_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            secret = "루트비밀번호는hunter2이다"
            _write_hermes_memory(root / ".hermes", secret)
            for action in MEMORY_ACTIONS:
                with self.subTest(action=action):
                    self.assertNotIn(secret, json.dumps(self._call(root, action=action), ensure_ascii=False))


class ProviderSlotTests(unittest.TestCase):
    def test_the_slot_is_taken_when_it_is_free(self) -> None:
        change = set_memory_provider("memory:\n  memory_char_limit: 2200\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_a_config_without_a_memory_section_grows_one(self) -> None:
        change = set_memory_provider("plugins:\n  enabled:\n    - omh\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_an_empty_provider_key_is_treated_as_free(self) -> None:
        change = set_memory_provider("memory:\n  provider: ''\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_another_product_holding_the_slot_is_never_overwritten(self) -> None:
        # Hermes runs one external provider, so a silent overwrite would switch
        # off whatever the operator actually chose.
        original = "memory:\n  provider: honcho\n"
        change = set_memory_provider(original, "omh")
        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)
        self.assertIn("honcho", change.message)

    def test_taking_a_slot_omh_already_holds_is_a_no_op(self) -> None:
        self.assertFalse(set_memory_provider("memory:\n  provider: omh\n", "omh").changed)

    def test_only_omh_may_release_the_slot_omh_took(self) -> None:
        self.assertTrue(clear_memory_provider("memory:\n  provider: omh\n", "omh").changed)
        self.assertFalse(clear_memory_provider("memory:\n  provider: honcho\n", "omh").changed)
        self.assertFalse(clear_memory_provider("memory:\n  provider: ''\n", "omh").changed)

    def test_a_provider_key_in_another_section_is_not_mistaken_for_this_one(self) -> None:
        self.assertEqual(memory_provider_selection("image_gen:\n  provider: openai\n"), "")


class MemoryCliTests(unittest.TestCase):
    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    @staticmethod
    def _json(result: tuple[int, str, str]) -> tuple[int, dict, str]:
        status, stdout, stderr = result
        return status, (json.loads(stdout) if stdout.strip() else {}), stderr

    def test_a_block_can_be_written_listed_and_removed_from_the_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            status, payload, stderr = self._json(run_cli(base + ["memory", "block-set", "facts", "--value", "OMH wraps Hermes."]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["written"])

            status, payload, _ = self._json(run_cli(base + ["memory", "blocks"]))
            self.assertEqual(status, 0)
            self.assertEqual(payload["block_count"], 1)
            self.assertEqual(payload["blocks"][0]["label"], "facts")

            status, payload, _ = self._json(run_cli(base + ["memory", "block-remove", "facts"]))
            self.assertEqual(status, 0)
            self.assertTrue(payload["removed"])

    def test_an_over_limit_block_fails_the_command_rather_than_truncating(self) -> None:
        with TemporaryDirectory() as tmp:
            status, _, stderr = run_cli(
                self._base(Path(tmp)) + ["memory", "block-set", "facts", "--value", "x" * 40, "--limit", "10"]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("40 chars", stderr)

    def test_the_listing_can_be_narrowed_to_one_tier(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            self._json(run_cli(base + ["memory", "block-set", "always", "--value", "v", "--tier", "system"]))
            self._json(run_cli(base + ["memory", "block-set", "sometimes", "--value", "v", "--tier", "reference"]))
            _, payload, _ = self._json(run_cli(base + ["memory", "blocks", "--tier", "reference"]))
            self.assertEqual([block["label"] for block in payload["blocks"]], ["sometimes"])

    def test_dream_reports_without_evaluating_unless_asked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "dream"]))
            self.assertEqual(status, 0, stderr)
            self.assertFalse(payload["evaluated"])
            self.assertNotIn("due", payload)
            self.assertFalse((root / ".omh" / "memory" / "consolidation.json").exists())

    def test_dream_evaluate_weighs_the_triggers_and_never_consolidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "dream", "--evaluate"]))
            self.assertEqual(status, 0, stderr)
            self.assertIn("not evidence that memory was consolidated", payload["claim_boundary"])
            # The brief lands on disk whether or not this particular call is the
            # one that weighed the trigger: `initialize` evaluates first, and a
            # standing condition is not restated once it has been reported.
            self.assertTrue((root / ".omh" / "memory" / "consolidation.json").is_file())

            # Asking twice does not write twice, which is the whole point.
            before = (root / ".omh" / "memory" / "consolidation.jsonl").read_text(encoding="utf-8")
            run_cli(self._base(root) + ["memory", "dream", "--evaluate"])
            self.assertEqual((root / ".omh" / "memory" / "consolidation.jsonl").read_text(encoding="utf-8"), before)

    def test_the_provider_slot_can_be_taken_and_handed_back(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            status, payload, stderr = self._json(run_cli(base + ["memory", "provider", "--enable"]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["is_omh"])

            _, payload, _ = self._json(run_cli(base + ["memory", "provider"]))
            self.assertEqual(payload["provider"], MEMORY_PROVIDER_NAME)
            self.assertFalse(payload["changed"])

            _, payload, _ = self._json(run_cli(base + ["memory", "provider", "--disable"]))
            self.assertTrue(payload["changed"])
            self.assertFalse(payload["is_omh"])

    def test_enabling_never_evicts_another_product_from_the_slot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")

            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "provider", "--enable"]))
            self.assertEqual(status, 0, stderr)
            self.assertFalse(payload["changed"])
            self.assertEqual(payload["provider"], "honcho")
            self.assertEqual(config.read_text(encoding="utf-8"), "memory:\n  provider: honcho\n")

    def test_a_dry_run_reports_the_change_without_writing_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "provider", "--enable", "--dry-run"]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["changed"])
            self.assertFalse((root / ".hermes" / "config.yaml").exists())


class DoctorSlotReportTests(unittest.TestCase):
    """A slot held by something else is why OMH's hooks would not be running."""

    def _doctor(self, root: Path) -> dict:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "doctor"]
        )
        self.assertIn(status, (0, 1), stderr)
        return json.loads(stdout)

    def _message(self, payload: dict) -> str:
        return next(
            str(check["message"]) for check in payload["checks"] if check["name"] == "memory_provider"
        )

    def test_an_off_state_points_at_a_command_ordinary_users_know(self) -> None:
        # `omh setup` claims a free slot, so this is what an unset one means --
        # and setup is one of the three commands AGENTS.md says people should
        # need. Naming `omh memory provider --enable` here would send them to
        # the control plane for something setup already does.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: ''\n", encoding="utf-8")
            message = self._message(self._doctor(root))
            self.assertIn("omh setup", message)
            self.assertNotIn("omh memory provider", message)

    def test_a_slot_held_by_another_product_reads_as_working_not_broken(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: honcho\n", encoding="utf-8")
            message = self._message(self._doctor(root))
            self.assertIn("honcho", message)
            self.assertIn("not a fault", message)

    def test_omh_holding_the_slot_reads_as_healthy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: omh\n", encoding="utf-8")
            self.assertIn("OMH memory is on", self._message(self._doctor(root)))


class SetupTurnsMemoryOnTests(unittest.TestCase):
    """A capability that needs a control-plane command is one most people never get.

    AGENTS.md says ordinary users should only need `omh setup`, `omh update`,
    and `omh doctor`. The provider first shipped requiring `omh memory provider
    --enable`, which put it outside that set entirely. Setup claims the slot now
    -- but only when it is free.
    """

    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def test_setup_turns_memory_on_when_the_slot_is_free(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["steps"]["apply"]["memory_provider"]["selected"], MEMORY_PROVIDER_NAME)
            self.assertIn("provider: omh", (root / ".hermes" / "config.yaml").read_text(encoding="utf-8"))

    def test_setup_never_takes_a_slot_another_product_holds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")

            status, stdout, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            provider = json.loads(stdout)["steps"]["apply"]["memory_provider"]
            self.assertFalse(provider["changed"])
            self.assertEqual(provider["selected"], "honcho")
            self.assertIn("provider: honcho", config.read_text(encoding="utf-8"))

    def test_setup_is_idempotent_on_the_slot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            _, stdout, _ = run_cli(self._base(root) + ["setup"])
            provider = json.loads(stdout)["steps"]["apply"]["memory_provider"]
            self.assertFalse(provider["changed"])
            self.assertEqual(provider["selected"], MEMORY_PROVIDER_NAME)

    def test_a_dry_run_setup_writes_no_provider_selection(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(self._base(root) + ["setup", "--dry-run"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse((root / ".hermes" / "config.yaml").exists())

    def test_the_summary_tells_the_user_memory_is_on(self) -> None:
        # The JSON payload is for wrappers; this line is what a person reads.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, stdout, _ = run_cli(self._base(root) + ["setup"], output_json=False)
            self.assertIn("Memory: OMH remembers across sessions", stdout)

    def test_the_summary_explains_an_off_state_rather_than_staying_silent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")
            _, stdout, _ = run_cli(self._base(root) + ["setup"], output_json=False)
            self.assertIn("honcho", stdout)
            self.assertIn("OMH memory stays off", stdout)

    def test_an_operator_can_still_hand_the_slot_back(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            status, stdout, stderr = run_cli(self._base(root) + ["memory", "provider", "--disable"])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(json.loads(stdout)["changed"])
            self.assertFalse(json.loads(stdout)["is_omh"])


class DoctorSurfacesTheBriefTests(unittest.TestCase):
    """The scheduler's decision has to reach a human somewhere.

    A brief was written to `consolidation.json` and nothing read it back, so
    OMH knew memory was nearly full and said so only to itself. Doctor is where
    an operator already looks.

    It is a warning, never a fault: OMH cannot run the consolidation, and it
    cannot tell whether Hermes already did.
    """

    def _checks(self, root: Path) -> dict[str, dict]:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "doctor"]
        )
        self.assertIn(status, (0, 1), stderr)
        return {check["name"]: check for check in json.loads(stdout)["checks"]}

    def _fire_a_brief(self, root: Path) -> None:
        _write_hermes_memory(root / ".hermes", "x" * 2100)
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")

    def test_a_pending_brief_is_reported_with_its_reasons(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fire_a_brief(root)
            check = self._checks(root)["memory_consolidation"]
            self.assertEqual(check["severity"], "warning")
            self.assertIn("headroom_below_floor", check["message"])
            self.assertIn("consolidat", check["message"].lower())

    def test_a_pending_brief_never_fails_the_install(self) -> None:
        # OMH cannot run the consolidation and cannot tell whether Hermes has,
        # so an outstanding brief is a thing to know, not a thing that is broken.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fire_a_brief(root)
            self.assertTrue(self._checks(root)["memory_consolidation"]["ok"])

    def test_no_brief_reads_as_nothing_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            check = self._checks(root)["memory_consolidation"]
            self.assertEqual(check["severity"], "ok")
            self.assertIn("No memory consolidation is pending", check["message"])

    def test_an_unreadable_brief_reads_as_nothing_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".omh" / "memory" / "consolidation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(self._checks(root)["memory_consolidation"]["severity"], "ok")

    def test_a_brief_that_was_not_due_is_not_reported_as_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            # Nothing fired, so no brief was written at all.
            self.assertEqual(self._checks(root)["memory_consolidation"]["severity"], "ok")

    def test_the_reader_is_defensive_about_the_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory" / "consolidation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"schema_version": "something_else/v1"}), encoding="utf-8")
            self.assertIsNone(read_latest_consolidation(tmp))


class BlockBudgetDefaultTests(unittest.TestCase):
    def test_the_default_block_limit_fits_beside_hermes_own_cap(self) -> None:
        # A block that alone exceeded Hermes' 2200-char memory file would make
        # the always-rendered tier the largest thing in the turn.
        self.assertLessEqual(DEFAULT_BLOCK_LIMIT_CHARS, 2200)


if __name__ == "__main__":
    unittest.main()

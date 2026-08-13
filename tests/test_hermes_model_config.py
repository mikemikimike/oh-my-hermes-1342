from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.hermes_model_config import (  # noqa: E402
    AliasCollisionError,
    ConfirmationRequiredError,
    ConfigDigestMismatchError,
    HermesCommandError,
    HermesModelConfigError,
    apply_hermes_model_config,
    inspect_hermes_model_config,
    preview_hermes_model_config,
)


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys
from threading import Event

home = Path(os.environ["HERMES_HOME"])
state_path = home / "config.yaml"
log_path = home / "commands.jsonl"
home.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
state = json.loads(state_path.read_text(encoding="utf-8"))

def get(key):
    current = state
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(key)
        current = current[part]
    return current

args = sys.argv[1:]
if os.environ.get("HERMES_HANG") == " ".join(args):
    Event().wait()
if args == ["config", "path"]:
    print(state_path)
elif args[:2] == ["config", "get"]:
    try:
        value = get(args[2])
    except KeyError:
        raise SystemExit(1)
    print(json.dumps(value))
elif args == ["config", "check"]:
    if os.environ.get("HERMES_CONFIG_CHECK_FAIL"):
        raise SystemExit(1)
    print("Configuration OK")
elif args[:2] == ["auth", "list"]:
    if not os.environ.get("HERMES_AUTH_MISSING"):
        print("alpha (1 credentials):")
        print("SECRET_VALUE_MUST_NOT_ESCAPE")
elif args[:2] == ["auth", "status"]:
    present = args[2] == "alpha" and not os.environ.get("HERMES_AUTH_MISSING")
    raise SystemExit(0 if present else 1)
elif args[:2] == ["config", "set"]:
    failure_marker = home / "mutation-failed"
    if os.environ.get("HERMES_FAIL_MUTATION") == args[2] and not failure_marker.exists():
        failure_marker.touch()
        raise SystemExit(9)
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = args[3]
    if os.environ.get("HERMES_CONCURRENT_ALIAS"):
        state["model"]["aliases"]["foreign"] = "foreign/concurrent"
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
elif args[:2] == ["config", "unset"]:
    failure_marker = home / "mutation-failed"
    if os.environ.get("HERMES_FAIL_MUTATION") == args[2] and not failure_marker.exists():
        failure_marker.touch()
        raise SystemExit(9)
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current[part]
    current.pop(parts[-1], None)
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
else:
    raise SystemExit(f"unexpected command: {args}")
"""


class HermesModelConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-model-config-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "hermes-home"
        self.home.mkdir()
        self.hermes = Path(self.temp.name) / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.config = self.home / "config.yaml"
        self.config.write_text(
            json.dumps(
                {
                    "model_aliases": {"legacy": "alpha/legacy"},
                    "model": {
                        "provider": "alpha",
                        "aliases": {"fast": "alpha/fast", "retire": "beta/old"},
                    },
                    "plugins": {
                        "enabled": ["alpha"],
                        "entries": {"alpha": {"token": "SECRET_VALUE_MUST_NOT_ESCAPE"}},
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.env = {"HERMES_HOME": str(self.home), "PATH": os.environ["PATH"]}

    def state(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_inspect_uses_only_local_secret_free_commands(self) -> None:
        # Given: a config with legacy and nested aliases, auth, and one provider plugin.
        # When: the adapter inspects the Hermes-native surfaces.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # Then: it returns structured presence only and never exposes command output secrets.
        self.assertEqual(dict(inspection.model_aliases), {"legacy": "alpha/legacy"})
        self.assertEqual(
            dict(inspection.model_dot_aliases),
            {"fast": "alpha/fast", "retire": "beta/old"},
        )
        providers = {item.provider_id: item for item in inspection.providers}
        self.assertTrue(providers["alpha"].auth_present)
        self.assertTrue(providers["alpha"].auth_status_ok)
        self.assertTrue(providers["alpha"].plugin_present)
        self.assertFalse(providers["beta"].auth_present)
        self.assertFalse(providers["beta"].auth_status_ok)
        self.assertFalse(providers["beta"].plugin_present)
        self.assertNotIn("SECRET_VALUE_MUST_NOT_ESCAPE", repr(inspection))
        flattened = [part for command in inspection.commands for part in command]
        self.assertNotIn("model", flattened)
        self.assertNotIn("--refresh", flattened)
        self.assertNotIn("env-path", flattened)

    def test_preview_emits_exact_set_and_unset_commands(self) -> None:
        # Given: a current digest and non-colliding alias changes.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # When: a nested-alias update is previewed.
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # Then: the preview contains the exact Hermes-native argv and no mutation occurred.
        self.assertEqual(
            preview.commands,
            (
                (str(self.hermes), "config", "set", "model.aliases.new", "alpha/new"),
                (str(self.hermes), "config", "unset", "model.aliases.retire"),
            ),
        )
        self.assertIn('"retire"', self.config.read_text(encoding="utf-8"))

    def test_preview_refuses_existing_alias_collision_by_default(self) -> None:
        # Given: an existing nested alias.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # When/Then: changing its target without an override is refused.
        with self.assertRaises(AliasCollisionError):
            preview_hermes_model_config(inspection, {"fast": "beta/replacement"})

    def test_inspect_sanitizes_secret_shaped_alias_and_plugin_metadata(self) -> None:
        # Given: Hermes metadata keys and values shaped like issued credentials.
        secret = "sk-" + ("a" * 24)
        state = self.state()
        state["model"]["aliases"][secret] = f"{secret}/model"
        state["plugins"]["enabled"].append(secret)
        state["plugins"]["entries"][secret] = {}
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

        # When: the adapter inspects provider metadata.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # Then: the secret shape reaches neither the payload nor auth subprocess argv.
        self.assertNotIn(secret, repr(inspection))
        commands = [
            json.loads(line)
            for line in (self.home / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertFalse(any(secret in part for command in commands for part in command))

    def test_preview_rejects_secret_shaped_alias_before_building_payload(self) -> None:
        # Given: an inspected config and an alias shaped like an issued credential.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        secret_alias = "sk-" + ("b" * 24)

        # When/Then: preview construction rejects it before producing command payloads.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {secret_alias: "alpha/model"})

    def test_subprocess_timeout_is_bounded_and_reported(self) -> None:
        # Given: the isolated Hermes CLI hangs before returning its config path.
        env = {**self.env, "HERMES_HANG": "config path"}

        # When/Then: the real child process is killed at the bound and reported as unobserved.
        with self.assertRaisesRegex(HermesCommandError, "timed out after 10s"):
            inspect_hermes_model_config(hermes=str(self.hermes), env=env)

    def test_preview_refuses_failed_config_check(self) -> None:
        # Given: Hermes reports the local config is invalid.
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes),
            env={**self.env, "HERMES_CONFIG_CHECK_FAIL": "1"},
        )

        # When/Then: no mutation preview is produced.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {"new": "alpha/new"})

    def test_preview_refuses_target_provider_without_required_auth(self) -> None:
        # Given: the target provider has no observed Hermes auth.
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes),
            env={**self.env, "HERMES_AUTH_MISSING": "1"},
        )

        # When/Then: an alias targeting that provider is refused before apply.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {"new": "alpha/new"})

    def test_apply_requires_confirmation_and_matching_digest(self) -> None:
        # Given: a valid preview.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(inspection, {"new": "alpha/new"})

        # When/Then: both explicit confirmation and the previewed digest are CAS gates.
        with self.assertRaises(ConfirmationRequiredError):
            apply_hermes_model_config(
                preview,
                confirmed=False,
                expected_config_digest=inspection.config_digest,
                env=self.env,
            )
        self.config.write_text(self.config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env=self.env,
            )

    def test_apply_writes_and_verifies_nested_aliases(self) -> None:
        # Given: a confirmed preview whose config digest still matches.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: the adapter applies the exact preview.
        receipt = apply_hermes_model_config(
            preview,
            confirmed=True,
            expected_config_digest=inspection.config_digest,
            env=self.env,
        )

        # Then: post-write inspection verifies both the set and unset.
        self.assertTrue(receipt.verified)
        self.assertNotEqual(receipt.before_digest, receipt.after_digest)
        self.assertEqual(dict(receipt.inspection.model_dot_aliases), {"fast": "alpha/fast", "new": "alpha/new"})
        commands = [
            json.loads(line)
            for line in (self.home / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertFalse(any(command and command[0] == "model" for command in commands))
        self.assertFalse(any("env-path" in command or "--refresh" in command for command in commands))

    def test_apply_rolls_back_attempted_aliases_after_concurrent_drift(self) -> None:
        # Given: a two-alias preview and an external alias mutation during the first write.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: apply observes that concurrent mutation before completing the preview.
        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_CONCURRENT_ALIAS": "1"},
            )

        # Then: this attempt is rolled back while the foreign mutation is preserved.
        aliases = self.state()["model"]["aliases"]
        self.assertNotIn("new", aliases)
        self.assertEqual(aliases["retire"], "beta/old")
        self.assertEqual(aliases["foreign"], "foreign/concurrent")

    def test_apply_rolls_back_all_attempted_aliases_after_partial_failure(self) -> None:
        # Given: a two-alias preview whose second Hermes mutation will fail.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: the second mutation exits unsuccessfully.
        with self.assertRaises(HermesCommandError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_MUTATION": "model.aliases.retire"},
            )

        # Then: both attempted aliases are restored to their inspected pre-apply values.
        aliases = self.state()["model"]["aliases"]
        self.assertNotIn("new", aliases)
        self.assertEqual(aliases["retire"], "beta/old")


if __name__ == "__main__":
    unittest.main()

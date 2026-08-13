from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import random
import shutil
from typing import Any

from common import digest, tree_digest, write_json

DEVELOPMENT_SEEDS = (7919,)
EVALUATION_SEEDS = (104729, 130363, 155921)
TEMPLATES = (
    ("RENAME", "edit"), ("BUGFIX", "edit"),
    ("PRECEDENCE", "read"), ("CALLFLOW", "read"),
    ("REFERENCES", "search"), ("PREDICATE", "search"),
    ("DEFINITION", "lsp"), ("DIAGNOSTICS", "lsp"),
    ("SCALE", "routing"), ("EXPLICIT", "routing"),
)

@dataclass(frozen=True)
class Instance:
    split: str
    template_id: str
    instance_id: str
    task_class: str
    seed: int
    prompt: str
    fixture_digest: str


def all_specs(split: str) -> list[tuple[str, str, int]]:
    seeds = DEVELOPMENT_SEEDS if split == "development" else EVALUATION_SEEDS
    prefix = "D" if split == "development" else "E"
    return [(f"{prefix}-{name}", task_class, seed) for name, task_class in TEMPLATES for seed in seeds]


def _project_files(seed: int) -> dict[str, str]:
    randomizer = random.Random(seed)
    suffix = randomizer.choice(("Amber", "Cobalt", "Juniper", "Quartz")) + str(seed % 97)
    decision = f"RouteDecision{suffix}"
    padding = "\n" * randomizer.randint(0, 3)
    return {
        "pyproject.toml": "[project]\nname='benchapp-synthetic'\nversion='0.0.1'\nrequires-python='>=3.11'\n",
        "src/benchapp/__init__.py": "",
        "src/benchapp/retries.py": "DEFAULT_RETRY_LIMIT = 2\n\ndef retry_budget() -> int:\n    return DEFAULT_RETRY_LIMIT\n",
        "tests/test_retries.py": "from benchapp.retries import DEFAULT_RETRY_LIMIT, retry_budget\n\ndef test_retry_budget():\n    assert DEFAULT_RETRY_LIMIT == retry_budget() == 2\n",
        "src/benchapp/provider_select.py": (
            "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Provider:\n"
            "    name: str\n    region: str\n    enabled: bool\n\nPROVIDERS = [\n"
            "    Provider('archive', 'us', False),\n    Provider('primary', 'us', True),\n"
            "    Provider('europe', 'eu', True),\n]\n\ndef select_provider(region: str | None) -> Provider | None:\n"
            "    # BUG: disabled entries and None are not handled.\n    for provider in PROVIDERS:\n"
            "        if provider.region == region:\n            return provider\n    return PROVIDERS[0]\n"
        ),
        "src/benchapp/config.py": (
            "DEFAULT_TIMEOUT_SECONDS = 15\nDEFAULT_RETRIES = 2\n\ndef load_config(cli, environment, file_config):\n"
            "    if cli is not None:\n        return cli\n    if environment is not None:\n        return environment\n"
            "    if file_config is not None:\n        return file_config\n    return DEFAULT_TIMEOUT_SECONDS\n"
            "\ndef validate(value):\n    if value is None:\n        raise ValueError('missing configuration')\n"
            "    if value < 0:\n        raise ValueError('negative configuration')\n"
        ),
        "src/benchapp/flow.py": (
            "class Request: pass\nclass Result: pass\n\nclass Policy:\n    def apply(self, request):\n"
            "        if request is None:\n            raise ValueError('invalid_request')\n        return Result()\n\n"
            "class Router:\n    def route(self, request):\n        try:\n            return Policy().apply(request)\n"
            "        except ValueError:\n            raise RuntimeError('policy_rejected')\n"
        ),
        "src/benchapp/routes.py": (
            f"from dataclasses import dataclass\n{padding}@dataclass\nclass {decision}:\n    name: str\n\n"
            f"def choose() -> {decision}:\n    return {decision}('safe')\n\n"
            f"def consume(value: {decision}) -> str:\n    return value.name\n"
            f"\n# decoy {decision}\nDECOY = '{decision}'\n"
        ),
        "src/benchapp/fallbacks.py": (
            "def fetch_primary(client):\n    try:\n        return client.fetch()\n    except RuntimeError:\n"
            "        return {'source': 'fallback'}\n\ndef strict_fetch(client):\n    return client.fetch()\n"
            "\ndef fetch_secondary(client):\n    try:\n        return client.fetch_secondary()\n    except ConnectionError:\n"
            "        return {'source': 'fallback'}\n"
        ),
        "src/benchapp/diagnostic.py": "def total(values: list[int]) -> int:\n    return sum(values)\n\nBROKEN_NAME: int = missing_value\n",
        "tools/route_probe.py": (
            "import argparse, json\np=argparse.ArgumentParser()\np.add_argument('--scale')\np.add_argument('--model')\n"
            "p.add_argument('--available', action='store_true')\na=p.parse_args()\n"
            "if a.model and not a.available:\n out={'status':'choice_required','provenance':'explicit_request','selected_model':None,'effort':'none','attempted_stages':['explicit'],'reason_codes':['explicit_model_unavailable']}\n"
            "else:\n out={'status':'selected','provenance':'task_scale','selected_model':a.model or ('deep-model' if a.scale=='large' else 'fast-model'),'effort':'high' if a.scale=='large' else 'low','attempted_stages':['scale']}\n"
            "print(json.dumps(out, sort_keys=True))\n"
        ),
    }


def _prompt(template_id: str, task_class: str, seed: int, decision: str) -> str:
    name = template_id.split("-", 1)[1]
    prompts = {
        "RENAME": "Rename DEFAULT_RETRY_LIMIT to MAX_RETRY_ATTEMPTS in production and tests without changing behavior. Return JSON with changed_paths.",
        "BUGFIX": "Fix select_provider(region) to return the first enabled matching provider and return None for None/no match. Add regression tests. Return JSON with changed_paths.",
        "PRECEDENCE": "Read the configuration implementation. Return JSON facts for precedence, default_timeout_seconds, default_retries, and failure_states, with path/line citations.",
        "CALLFLOW": "Trace Request -> Router -> Policy -> Result and terminal errors. Return JSON containing ordered edges, error_states, and path/line citations.",
        "REFERENCES": f"Find every semantic definition/reference of {decision}, excluding comments and strings. Return exact JSON locations as path, line, kind.",
        "PREDICATE": "Find every function that converts a provider failure to a fallback result. Return exact JSON locations as path, line, kind.",
        "DEFINITION": f"Use LSP definition and references for {decision} at its use in choose(). Return exact JSON locations and tools_used.",
        "DIAGNOSTICS": "Use LSP diagnostics, minimally fix all name/type errors in diagnostic.py, then use diagnostics again. Return JSON diagnostics and tools_used.",
        "SCALE": "For a large coding task invoke tools/route_probe.py with the correct arguments and return its exact route JSON.",
        "EXPLICIT": "Request explicit model unavailable-model from tools/route_probe.py. Preserve it: never substitute. Return its exact route JSON.",
    }
    return prompts[name]


def _golden(template_id: str, files: dict[str, str], decision: str) -> dict[str, Any]:
    name = template_id.split("-", 1)[1]
    routes_lines = files["src/benchapp/routes.py"].splitlines()
    refs = []
    for line_no, line in enumerate(routes_lines, 1):
        if decision in line and not line.lstrip().startswith("#") and "DECOY" not in line:
            kind = "definition" if line.startswith("class ") else "reference"
            refs.append({"path": "src/benchapp/routes.py", "line": line_no, "kind": kind})
    goldens: dict[str, dict[str, Any]] = {
        "PRECEDENCE": {"facts": {"precedence": ["cli", "environment", "file", "default"], "default_timeout_seconds": 15, "default_retries": 2, "failure_states": ["missing configuration", "negative configuration"]}, "citations": [{"path": "src/benchapp/config.py", "line": 1}]},
        "CALLFLOW": {"edges": [["Request", "Router"], ["Router", "Policy"], ["Policy", "Result"]], "error_states": ["invalid_request", "policy_rejected"], "citations": [{"path": "src/benchapp/flow.py", "line": 1}]},
        "REFERENCES": {"locations": refs},
        "PREDICATE": {"locations": [{"path": "src/benchapp/fallbacks.py", "line": 1, "kind": "function"}, {"path": "src/benchapp/fallbacks.py", "line": 10, "kind": "function"}]},
        "DEFINITION": {"locations": refs, "required_tools": ["lsp_goto_definition", "lsp_find_references"]},
        "DIAGNOSTICS": {"diagnostics": [], "required_tools": ["lsp_diagnostics"], "allowed_paths": ["src/benchapp/diagnostic.py"]},
        "SCALE": {"route": {"status": "selected", "provenance": "task_scale", "selected_model": "deep-model", "effort": "high", "attempted_stages": ["scale"]}},
        "EXPLICIT": {"route": {"status": "choice_required", "provenance": "explicit_request", "selected_model": None, "effort": "none", "attempted_stages": ["explicit"], "reason_codes": ["explicit_model_unavailable"]}},
    }
    return goldens.get(name, {"allowed_paths": ["src/benchapp/retries.py", "tests/test_retries.py"] if name == "RENAME" else ["src/benchapp/provider_select.py", "tests/test_provider_select.py"]})


def materialize(split: str, template_id: str, task_class: str, seed: int, workspace: Path, private_root: Path) -> tuple[Instance, Path]:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    files = _project_files(seed)
    decision = next(line.split()[1].rstrip(":") for line in files["src/benchapp/routes.py"].splitlines() if line.startswith("class "))
    for relative, content in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    prompt = _prompt(template_id, task_class, seed, decision)
    (workspace / "TASK.md").write_text(prompt + "\n", encoding="utf-8")
    golden_path = private_root / f"{template_id}-{seed}.json"
    write_json(golden_path, _golden(template_id, files, decision))
    instance = Instance(split, template_id, f"{template_id}-{seed}", task_class, seed, prompt, tree_digest(workspace))
    return instance, golden_path


def generate_public(root: Path, output: Path, verify: bool = True) -> dict[str, Any]:
    records: dict[str, list[dict[str, Any]]] = {}
    private = output.parent / ".controller-goldens"
    if private.exists():
        shutil.rmtree(private)
    private.mkdir(mode=0o700, parents=True)
    try:
        for split in ("development", "evaluation"):
            rows = []
            for template_id, task_class, seed in all_specs(split):
                workspace = output / "fixtures" / split / f"{template_id}-{seed}"
                instance, golden = materialize(split, template_id, task_class, seed, workspace, private)
                rows.append({"template_id": template_id, "instance_id": instance.instance_id, "class": task_class, "seed": seed, "prompt": instance.prompt, "fixture_digest": instance.fixture_digest})
                if verify:
                    ast.parse((workspace / "src/benchapp/routes.py").read_text(encoding="utf-8"))
                    if not golden.is_file():
                        raise AssertionError("controller golden missing")
            payload = {"schema_version": "omh_live_model_tool_corpus/v1", "split": split, "instances": rows}
            write_json(output / f"{split}.json", payload)
            records[split] = rows
    finally:
        shutil.rmtree(private)
    return {"schema_version": "omh_live_model_tool_corpus_receipt/v1", "counts": {key: len(value) for key, value in records.items()}, "corpus_digest": digest(records), "hidden_goldens_removed": not private.exists(), "verified": verify}

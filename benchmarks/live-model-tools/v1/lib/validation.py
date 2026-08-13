from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path
from typing import Any

from common import load_object


def changed_paths(workspace: Path, initial: dict[str, bytes]) -> list[str]:
    current = {}
    canonical_workspace = workspace.resolve(strict=True)
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace)
        if (
            path.is_symlink()
            or path.resolve(strict=True) != canonical_workspace / relative
        ):
            raise ValueError(f"workspace symlink is forbidden: {path.relative_to(workspace)}")
        if path.is_file() and ".git" not in path.parts:
            current[path.relative_to(workspace).as_posix()] = path.read_bytes()
    ignored = {"TASK.md", ".omh-benchmark-answer.json"}
    return sorted(
        key
        for key in set(initial) | set(current)
        if initial.get(key) != current.get(key) and key not in ignored
    )


def _ratio(found: set[tuple[Any, ...]], gold: set[tuple[Any, ...]]) -> tuple[float, float]:
    correct = found & gold
    recall = len(correct) / len(gold) if gold else float(not found)
    precision = len(correct) / len(found) if found else float(not gold)
    return recall, precision


def _locations(value: Any) -> set[tuple[str, int, str]]:
    if not isinstance(value, list):
        return set()
    result = set()
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and type(item.get("line")) is int and isinstance(item.get("kind"), str):
            result.add((item["path"], item["line"], item["kind"]))
    return result


def _load_answer(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        answer = load_object(path)
        if not answer:
            return {}, ["invalid_final_json"]
        return answer, []
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, ["invalid_final_json"]


def validate(template_id: str, task_class: str, workspace: Path, golden_path: Path, answer_path: Path, events: list[dict[str, Any]], initial: dict[str, bytes]) -> dict[str, Any]:
    golden = load_object(golden_path)
    answer, failures = _load_answer(answer_path)
    name = template_id.split("-", 1)[1]
    paths = changed_paths(workspace, initial)
    metrics: dict[str, Any] = {
        "pass": False, "first_attempt_pass": None, "retry_count": None,
        "fact_recall": None, "fact_precision": None, "citation_accuracy": None,
        "location_recall": None, "location_precision": None, "selector_first_hit": None,
        "lsp_adoption": None, "routing_field_accuracy": None, "failure_codes": failures,
    }
    if task_class == "edit":
        allowed = set(golden["allowed_paths"])
        if not set(paths).issubset(allowed) or not paths:
            failures.append("mutation_outside_scope")
        try:
            if name == "RENAME":
                production = (workspace / "src/benchapp/retries.py").read_text(encoding="utf-8")
                tests = (workspace / "tests/test_retries.py").read_text(encoding="utf-8")
                ast.parse(production); ast.parse(tests)
                semantic = "DEFAULT_RETRY_LIMIT" not in production + tests and production.count("MAX_RETRY_ATTEMPTS") == 2 and "MAX_RETRY_ATTEMPTS" in tests
            else:
                module = runpy.run_path(str(workspace / "src/benchapp/provider_select.py"))
                select_provider = module["select_provider"]
                semantic = select_provider(None) is None and select_provider("missing") is None and select_provider("us").name == "primary" and select_provider("eu").name == "europe"
        except Exception:
            semantic = False
        if not semantic:
            failures.append("semantic_validator_failed")
        mutations = [event for event in events if event.get("mutating")]
        first = bool(mutations and mutations[0].get("checkpoint_pass"))
        metrics["first_attempt_pass"] = first
        first_passing = next((index for index, event in enumerate(mutations, 1) if event.get("checkpoint_pass")), None)
        metrics["retry_count"] = (first_passing - 1) if first_passing is not None else len(mutations)
        if mutations and not first:
            failures.append("first_attempt_failed")
    elif task_class == "read":
        expected = golden.get("facts", {key: value for key, value in golden.items() if key not in {"citations"}})
        submitted = answer.get("facts", {key: answer.get(key) for key in expected if key in answer})
        if not isinstance(submitted, dict): submitted = {}
        correct = sum(submitted.get(key) == value for key, value in expected.items())
        metrics["fact_recall"] = correct / len(expected)
        metrics["fact_precision"] = correct / len(submitted) if submitted else 0.0
        citations = answer.get("citations", [])
        required_citations = golden.get("citations", [])
        valid = 0
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict) and isinstance(citation.get("path"), str) and type(citation.get("line")) is int:
                    source = workspace / citation["path"]
                    supported = source.is_file() and 1 <= citation["line"] <= len(source.read_text(encoding="utf-8").splitlines())
                    if required_citations:
                        supported = supported and citation in required_citations
                    if supported: valid += 1
        metrics["citation_accuracy"] = valid / len(citations) if isinstance(citations, list) and citations else 0.0
        if metrics["fact_recall"] < 1: failures.append("missing_fact")
        if metrics["fact_precision"] < 1: failures.append("unsupported_fact")
        if metrics["citation_accuracy"] < 1: failures.append("invalid_citation")
    elif task_class in {"search", "lsp"}:
        gold = _locations(golden.get("locations", []))
        found = _locations(answer.get("locations", []))
        recall, precision = _ratio(found, gold)
        metrics["location_recall"], metrics["location_precision"] = recall, precision
        if recall < 1: failures.append("search_false_negative" if task_class == "search" else "lsp_wrong_location")
        if precision < 1: failures.append("search_false_positive" if task_class == "search" else "lsp_wrong_location")
        first_search = next((event for event in events if event.get("name") in {"search", "lsp_goto_definition", "lsp_find_references"}), None)
        metrics["selector_first_hit"] = bool(first_search and first_search.get("gold_hit"))
        if task_class == "lsp":
            required = set(golden.get("required_tools", []))
            observed = {str(event.get("name")) for event in events}
            metrics["lsp_adoption"] = required.issubset(observed)
            if not metrics["lsp_adoption"]: failures.append("lsp_not_used")
            if name == "DIAGNOSTICS":
                if paths != golden["allowed_paths"] or answer.get("diagnostics") != []:
                    failures.append("diagnostics_not_clean")
                else:
                    failures = [item for item in failures if item != "lsp_wrong_location"]
    else:
        expected = golden["route"]
        route = answer.get("route", answer)
        correct = sum(route.get(key) == value for key, value in expected.items()) if isinstance(route, dict) else 0
        metrics["routing_field_accuracy"] = correct / len(expected)
        if metrics["routing_field_accuracy"] < 1: failures.append("routing_wrong_field")
        if name == "EXPLICIT" and isinstance(route, dict) and route.get("selected_model") is not None:
            failures.append("silent_explicit_substitution")
    metrics["failure_codes"] = sorted(set(failures))
    metrics["pass"] = not metrics["failure_codes"]
    return metrics

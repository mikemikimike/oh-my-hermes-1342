from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ..core.errors import OmhError
from ..converter import convert_from_dir
from ..local_store import atomic_write_text, read_json_object_result
from ..manifest import local_modifications, new_manifest, read_manifest, skill_records, write_manifest
from ..paths import OmhPaths
from ..profiles.team import TEAM_PROFILE_SCHEMA_VERSION
from ..skills.catalog import omh_skill_display_name
from ..skill_pack import (
    CORE_PROFILE_SKILLS,
    SkillReferenceTemplate,
    SkillTemplate,
    builtin_skill_reference_templates,
    builtin_skill_templates,
)

SKILL_PROFILES = ("core", "full")
DEFAULT_SKILL_PROFILE = "core"
CONTEXT_COST_WARNING_SCHEMA_VERSION = "omh_skill_profile_context_cost_warning/v1"
SKILL_PROFILE_STATE_SCHEMA_VERSION = "omh_skill_profile_state/v1"
SKILL_PROFILE_RECONCILE_SCHEMA_VERSION = "omh_skill_profile_reconcile/v1"
SKILL_PROFILE_RECONCILE_COMMAND = "omh skill-profile reconcile --to core"
SKILL_PROFILE_STATUS_COMMAND = "omh skill-profile status"
NON_DESTRUCTIVE_DEFAULT_NOTE = (
    "omh setup, install, and update never delete installed skills, so a full install keeps its "
    f"skills after the recorded profile changes; run `{SKILL_PROFILE_RECONCILE_COMMAND}` explicitly "
    "to shrink an existing full install."
)
RECONCILE_CONTEXT_COST_NOTE = (
    "Every installed skill adds per-turn context weight to every Hermes request, so an install that "
    "still carries full-only skills costs full-profile context even when the recorded profile is core."
)


def skill_directory_name(canonical: str) -> str:
    """Directory a skill is installed under.

    The directory now matches the label a host shows, because they were visibly
    disagreeing: Hermes printed `Loading skill: ulw-process` and then
    `[Skill directory: .../.omh/skills/ultraprocess]`. The canonical name still
    owns routing keys, triggers, and CLI arguments - only where the files sit
    changes, so `visual-qa` keeps working as something a user types.
    """
    return omh_skill_display_name(canonical)


def _write_skill(skills_dir: Path, template: SkillTemplate, force: bool = False, managed: bool = False) -> None:
    target_dir = skills_dir / skill_directory_name(template.name)
    target_file = target_dir / "SKILL.md"
    if target_file.exists() and not force and not managed:
        existing = target_file.read_text(encoding="utf-8")
        if existing != template.content:
            raise OmhError(f"local skill differs, refusing to overwrite without --force: {target_file}")
    atomic_write_text(target_file, template.content)


def _write_skill_reference(
    skills_dir: Path,
    template: SkillReferenceTemplate,
    force: bool = False,
    managed: bool = False,
) -> None:
    target_file = skills_dir / skill_directory_name(template.skill_name) / template.relative_path
    if target_file.exists() and not force and not managed:
        existing = target_file.read_text(encoding="utf-8")
        if existing != template.content:
            raise OmhError(f"local skill reference differs, refusing to overwrite without --force: {target_file}")
    atomic_write_text(target_file, template.content)


def install_skill_pack(
    paths: OmhPaths,
    *,
    source: str = "builtin",
    source_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    profile: str = DEFAULT_SKILL_PROFILE,
) -> dict:
    if profile not in SKILL_PROFILES:
        raise OmhError(f"unknown skill profile {profile!r}; choose one of {', '.join(SKILL_PROFILES)}")
    all_templates = convert_from_dir(source_dir) if source_dir else builtin_skill_templates()
    reference_templates = [] if source_dir else builtin_skill_reference_templates()
    # Profile filtering only applies to the packaged builtin catalog: an explicit
    # `source_dir` is a caller-scoped skill set, not the curated core/full catalog,
    # so every skill it names is installed regardless of `profile`.
    if source_dir or profile == "full":
        templates = all_templates
    else:
        # The profile decides what gets ADDED, never what gets REFRESHED. A skill
        # already on disk is refreshed whichever profile is recorded, because
        # `omh update` promising "updated" while leaving installed skills on an
        # older render is the same as lying: that is how an install ended up
        # serving `name: ultrawork` long after the catalog had moved to
        # `ulw-ultrawork`. Shedding full-only skills stays an explicit act -
        # `omh skill-profile reconcile --to core`.
        installed = _installed_skill_names(paths.skills_dir)
        refreshable = {
            template.name
            for template in all_templates
            if template.name in CORE_PROFILE_SKILLS
            or skill_directory_name(template.name) in installed
            # A pre-relabel install has the CANONICAL directory on disk and the
            # labelled one absent, so matching only the label dropped the skill
            # from refresh entirely: the labelled replacement was never
            # written, the relabel pruner then kept the old directory ("no
            # replacement yet"), and the host kept serving the stale pre-label
            # SKILL.md forever. The canonical name keeps it refreshable so one
            # update writes the labelled directory and prunes the old one.
            or template.name in installed
        }
        templates = [template for template in all_templates if template.name in refreshable]
        reference_templates = [
            template for template in reference_templates if template.skill_name in refreshable
        ]
    manifest = read_manifest(paths.manifest_path)
    modified = local_modifications(manifest, paths.skills_dir)
    if modified and not force:
        raise OmhError("local modifications detected; rerun with --force or resolve: " + ", ".join(modified))
    context_cost_warning = (
        _context_cost_warning(core_count=len(CORE_PROFILE_SKILLS), full_count=len(builtin_skill_templates()))
        if profile == "full"
        else None
    )
    if dry_run:
        result = {
            "dry_run": True,
            "skills_dir": str(paths.skills_dir),
            "skills": [template.name for template in templates],
            "source": source,
            "skill_profile": profile,
        }
        if context_cost_warning is not None:
            result["context_cost_warning"] = context_cost_warning
        return result
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    managed = manifest is not None
    for template in templates:
        _write_skill(paths.skills_dir, template, force=force, managed=managed)
    for template in reference_templates:
        _write_skill_reference(paths.skills_dir, template, force=force, managed=managed)
    pruned_skills = _prune_orphaned_skills(
        paths.skills_dir,
        manifest,
        {template.name for template in all_templates},
        force=force,
    )
    relabelled = _prune_relabelled_skill_directories(
        paths.skills_dir,
        manifest,
        {template.name for template in all_templates},
        force=force,
    )
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    manifest_data["skill_profile"] = profile
    if context_cost_warning is not None:
        manifest_data["context_cost_warning"] = context_cost_warning
    manifest_data["pruned_skills"] = pruned_skills
    manifest_data["relabelled_skills_removed"] = relabelled["removed"]
    manifest_data["relabelled_skills_retained"] = relabelled["retained"]
    manifest_data["skill_profile_state"] = skill_profile_state(paths.skills_dir, manifest_data)
    write_manifest(paths.manifest_path, manifest_data)
    return manifest_data


def _prune_relabelled_skill_directories(
    skills_dir: Path,
    manifest: dict | None,
    catalog_names: set[str],
    *,
    force: bool,
) -> dict[str, list[str]]:
    """Drop the pre-relabel directory once its labelled replacement is in place.

    Skills moved from `skills/<canonical>/` to `skills/<label>/`. Installs are
    non-destructive, so the first install after that change wrote the new
    directories and left the old ones beside them: an observed machine went from
    92 skills to 184, doubling the per-turn context weight of the pack, and the
    manifest then reported every vanished old path as a local modification.

    The safety rules match `_prune_orphaned_skills`: remove only a directory that
    is (a) named after a catalog skill whose label differs, (b) recorded in the
    prior manifest, (c) already replaced by a labelled directory holding a
    SKILL.md, and (d) byte-identical to what the manifest recorded. Anything a
    user edited is kept and reported instead, unless ``force``.
    """
    if not manifest:
        return {"removed": [], "retained": []}
    modified = set(local_modifications(manifest, skills_dir))
    recorded = {str(record.get("name")) for record in manifest.get("skills", []) if record.get("name")}
    recorded_paths = {
        str(record.get("name")): str(record.get("path", "")) for record in manifest.get("skills", [])
    }
    removed: list[str] = []
    retained: list[str] = []
    for name in sorted(catalog_names):
        label = skill_directory_name(name)
        if label == name or name not in recorded:
            continue
        old_dir = skills_dir / name
        if not old_dir.is_dir() or old_dir.is_symlink():
            continue
        if not (skills_dir / label / "SKILL.md").is_file():
            # Nothing to fall back on yet; never leave the skill uninstalled.
            retained.append(name)
            continue
        if recorded_paths.get(name, "") in modified and not force:
            retained.append(name)
            continue
        shutil.rmtree(old_dir)
        removed.append(name)
    return {"removed": removed, "retained": retained}


def _installed_skill_names(skills_dir: Path) -> set[str]:
    """Skill directories already present, whatever profile put them there.

    Read from disk rather than the manifest on purpose: a core-profile manifest
    records only the core skills, so the full-only directories beside them are
    exactly the ones the manifest cannot see and the ones that were going stale.
    """
    if not skills_dir.is_dir():
        return set()
    return {entry.name for entry in skills_dir.iterdir() if entry.is_dir() and not entry.is_symlink()}



def _prune_orphaned_skills(
    skills_dir: Path,
    manifest: dict | None,
    catalog_names: set[str],
    *,
    force: bool,
) -> list[str]:
    """Remove managed skill dirs recorded in the prior manifest that the full catalog no longer ships.

    ``catalog_names`` must be the FULL ``builtin_skill_templates()`` catalog, never the
    profile-filtered install set, so a full->core reinstall does not shed full-only skills.
    A dir is pruned only when it is (a) recorded in the prior manifest, (b) absent from the
    full catalog, and (c) sha-unmodified vs. the manifest; user-modified dirs are kept unless
    ``force``. Removed directory names are returned so the caller can surface them.
    """
    if not manifest:
        return []
    modified = set(local_modifications(manifest, skills_dir))
    removed: list[str] = []
    for record in manifest.get("skills", []):
        name = record.get("name")
        rel = record.get("path")
        if not name or not rel or name in catalog_names:
            continue
        if str(rel) in modified and not force:
            continue
        target_dir = skills_dir / name  # manifest-recorded path; already the installed directory
        if not target_dir.is_dir() or target_dir.is_symlink():
            continue
        shutil.rmtree(target_dir)
        removed.append(name)
    return removed


def _context_cost_warning(*, core_count: int, full_count: int) -> dict:
    extra_count = max(full_count - core_count, 0)
    return {
        "schema_version": CONTEXT_COST_WARNING_SCHEMA_VERSION,
        "profile": "full",
        "installed_skill_count": full_count,
        "core_profile_skill_count": core_count,
        "extra_skill_count": extra_count,
        "message": (
            f"full profile installs all {full_count} packaged skills, {extra_count} more than the "
            f"{core_count}-skill core default; every installed skill adds per-turn context weight to "
            "every Hermes request, so prefer core unless this workspace genuinely needs the complete catalog."
        ),
    }


def _all_catalog_skill_names() -> list[str]:
    return [template.name for template in builtin_skill_templates()]


def installed_skill_names(skills_dir: Path) -> list[str]:
    """Names of skill directories that currently hold a SKILL.md under ``skills_dir``."""
    if not skills_dir.is_dir():
        return []
    # Directories carry display labels; every caller reasons in canonical names
    # (CORE_PROFILE_SKILLS, manifests, capability ids), so translate back here
    # rather than leaving each caller to guess which namespace it is holding.
    canonical_by_directory = {
        skill_directory_name(name): name for name in _all_catalog_skill_names()
    }
    names = [
        canonical_by_directory.get(entry.name, entry.name)
        for entry in skills_dir.iterdir()
        if entry.is_dir() and not entry.is_symlink() and (entry / "SKILL.md").is_file()
    ]
    return sorted(names)


def skill_profile_state(skills_dir: Path, manifest: dict | None) -> dict:
    """Describe requested vs. effective profile so status output cannot claim a footprint it does not have.

    ``requested_profile`` is the profile the last install recorded; ``effective_profile`` is derived
    from the skill directories that actually exist on disk. They diverge whenever a full install is
    reinstalled as core, because installs are non-destructive by design.
    """
    catalog_names = {template.name for template in builtin_skill_templates()}
    core_names = set(CORE_PROFILE_SKILLS)
    installed = installed_skill_names(skills_dir)
    installed_catalog = [name for name in installed if name in catalog_names]
    full_only_installed = sorted(name for name in installed_catalog if name not in core_names)
    requested = str((manifest or {}).get("skill_profile") or "")
    if not installed_catalog:
        effective = "none"
    elif catalog_names.issubset(installed_catalog):
        effective = "full"
    elif not full_only_installed:
        effective = "core"
    else:
        effective = "mixed"
    retained_exception = bool(requested == "core" and full_only_installed)
    return {
        "schema_version": SKILL_PROFILE_STATE_SCHEMA_VERSION,
        "requested_profile": requested,
        "effective_profile": effective,
        "matches_requested_profile": bool(requested) and effective == requested,
        "core_profile_skill_count": len(core_names),
        "full_profile_skill_count": len(catalog_names),
        "installed_skill_count": len(installed),
        "installed_catalog_skill_count": len(installed_catalog),
        "unmanaged_skill_count": len(installed) - len(installed_catalog),
        "full_only_installed_skills": full_only_installed,
        "retained_exception": retained_exception,
        "context_cost_note": RECONCILE_CONTEXT_COST_NOTE,
        "non_destructive_default": NON_DESTRUCTIVE_DEFAULT_NOTE,
        "next_action": SKILL_PROFILE_RECONCILE_COMMAND if retained_exception else "",
    }


def _catalog_skill_files() -> dict[str, dict[str, str]]:
    """Rendered catalog content per skill: name -> {posix relative path: file content}."""
    files: dict[str, dict[str, str]] = {}
    for template in builtin_skill_templates():
        files.setdefault(template.name, {})["SKILL.md"] = template.content
    for template in builtin_skill_reference_templates():
        rel = Path(template.relative_path).as_posix()
        files.setdefault(template.skill_name, {})[rel] = template.content
    return files


def _installed_skill_files(skill_dir: Path) -> dict[str, str] | None:
    """Read every regular file under a skill dir; return None when anything is not plainly readable."""
    files: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink():
            return None
        if path.is_dir():
            continue
        if not path.is_file():
            return None
        try:
            files[path.relative_to(skill_dir).as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return files


def _reconcile_plan(skills_dir: Path, manifest: dict) -> dict:
    """Split installed full-only skills into safely removable and retained-with-reason sets.

    A skill is removable only when it is OMH-managed (recorded in the install manifest) AND
    unmodified (every file under its directory is byte-identical to the rendered catalog
    templates, with no extra or missing files). Anything else is retained and reported.
    """
    catalog_files = _catalog_skill_files()
    core_names = set(CORE_PROFILE_SKILLS)
    managed_names = {
        str(record.get("name"))
        for record in manifest.get("skills", [])
        if isinstance(record, dict) and record.get("name")
    }
    removable: list[str] = []
    retained: list[dict[str, str]] = []
    for name in installed_skill_names(skills_dir):
        if name in core_names:
            continue
        expected = catalog_files.get(name)
        if expected is None:
            retained.append({"name": name, "reason": "not an OMH catalog skill"})
            continue
        if name not in managed_names:
            retained.append({"name": name, "reason": "no OMH install-manifest record; not OMH-managed"})
            continue
        actual = _installed_skill_files(skills_dir / skill_directory_name(name))
        if actual is None:
            retained.append({"name": name, "reason": "skill directory is not plainly readable managed content"})
            continue
        if actual != expected:
            retained.append({"name": name, "reason": "locally modified vs. the rendered catalog templates"})
            continue
        removable.append(name)
    return {"removable_skills": removable, "retained_skills": retained}


def skill_profile_report(paths: OmhPaths) -> dict:
    """Read-only requested/effective profile report plus the reconcile plan; mutates nothing."""
    manifest = read_manifest(paths.manifest_path)
    state = skill_profile_state(paths.skills_dir, manifest)
    plan = _reconcile_plan(paths.skills_dir, manifest or {})
    return {
        "schema_version": SKILL_PROFILE_STATE_SCHEMA_VERSION,
        "skills_dir": str(paths.skills_dir),
        "manifest_path": str(paths.manifest_path),
        "installed": manifest is not None,
        "profile_state": state,
        "reconcilable_skills": plan["removable_skills"],
        "retained_skills": plan["retained_skills"],
    }


def reconcile_skill_profile(
    paths: OmhPaths,
    *,
    target_profile: str = DEFAULT_SKILL_PROFILE,
    dry_run: bool = False,
) -> dict:
    """Explicitly shrink an existing install down to the core profile.

    This is the only OMH path that deletes managed skill directories, and it never runs as part of
    setup/install/update. It removes only unmodified managed full-only skills; locally modified and
    non-managed directories stay on disk and are reported as retained exceptions.
    """
    if target_profile != DEFAULT_SKILL_PROFILE:
        raise OmhError(
            f"skill profile reconcile only shrinks to {DEFAULT_SKILL_PROFILE!r}; "
            "install the wider catalog with `omh install --full` instead"
        )
    manifest = read_manifest(paths.manifest_path)
    if manifest is None:
        raise OmhError(f"no OMH skill manifest at {paths.manifest_path}; run `omh setup` first")
    plan = _reconcile_plan(paths.skills_dir, manifest)
    result = {
        "schema_version": SKILL_PROFILE_RECONCILE_SCHEMA_VERSION,
        "target_profile": target_profile,
        "dry_run": dry_run,
        "skills_dir": str(paths.skills_dir),
        "profile_state_before": skill_profile_state(paths.skills_dir, manifest),
        "retained_skills": plan["retained_skills"],
        "context_cost_note": RECONCILE_CONTEXT_COST_NOTE,
        "non_destructive_default": NON_DESTRUCTIVE_DEFAULT_NOTE,
    }
    if dry_run:
        result["would_remove_skills"] = plan["removable_skills"]
        result["removed_skills"] = []
        return result

    removed: list[str] = []
    for name in plan["removable_skills"]:
        target_dir = paths.skills_dir / skill_directory_name(name)
        if not target_dir.is_dir() or target_dir.is_symlink():
            continue
        shutil.rmtree(target_dir)
        removed.append(name)
    source = str(manifest.get("source") or "builtin")
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    manifest_data["skill_profile"] = target_profile
    manifest_data["reconciled_skills"] = removed
    manifest_data["skill_profile_state"] = skill_profile_state(paths.skills_dir, manifest_data)
    write_manifest(paths.manifest_path, manifest_data)
    result["removed_skills"] = removed
    result["profile_state_after"] = manifest_data["skill_profile_state"]
    return result


def uninstall_skill_pack(
    paths: OmhPaths,
    *,
    remove_files: bool = False,
    remove_all: bool = False,
    dry_run: bool = False,
    force: bool = False,
    remove_command_package: bool = False,
) -> dict:
    """Remove OMH-managed local files without deleting unrelated Hermes state."""
    removed: list[str] = []
    would_remove: list[str] = []
    kept: list[dict[str, str]] = []

    if remove_all:
        _collect_removal(
            paths.hermes_plugin_dir,
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
            force=force,
            managed_plugin=True,
        )
        for team_file in _managed_team_profile_files(paths):
            _collect_removal(
                team_file,
                removed=removed,
                would_remove=would_remove,
                kept=kept,
                dry_run=dry_run,
                force=force,
            )

    if remove_files or remove_all:
        _collect_removal(paths.omh_home, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)

    command_removed_at = len(removed)
    command_would_remove_at = len(would_remove)
    command_kept_at = len(kept)
    if remove_command_package:
        _collect_command_package_removal(
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
        )
    command_removed = removed[command_removed_at:]
    command_would_remove = would_remove[command_would_remove_at:]
    command_kept = kept[command_kept_at:]

    return {
        "schema_version": "omh_uninstall/v1",
        "removed_files": bool(removed),
        "remove_files": remove_files or remove_all,
        "remove_all": remove_all,
        "dry_run": dry_run,
        "omh_home": str(paths.omh_home),
        "plugin_dir": str(paths.hermes_plugin_dir),
        "team_agents_dir": str(paths.hermes_agents_dir),
        "removed_paths": removed,
        "would_remove": would_remove,
        "kept_paths": kept,
        "command_package_remove_requested": remove_command_package,
        "command_package_removed": bool(command_removed),
        "command_package_removed_paths": command_removed,
        "command_package_would_remove": command_would_remove,
        "command_package_kept": command_kept,
    }


def _collect_removal(
    path: Path,
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
    force: bool,
    managed_plugin: bool = False,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if managed_plugin and not force and not _looks_like_managed_plugin(path):
        kept.append({"path": str(path), "reason": "plugin dir is not an OMH-managed bundle; rerun with --force to remove it"})
        return
    if dry_run:
        would_remove.append(str(path))
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(str(path))


def _looks_like_managed_plugin(path: Path) -> bool:
    return (path / ".omh-plugin-manifest.json").exists()


def _collect_command_package_removal(
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
) -> None:
    venv_dir = _managed_command_venv_dir()
    if venv_dir is None:
        kept.append({"path": "omh", "reason": "HOME is not available, so the install.sh-managed command venv cannot be located"})
        return
    executable = Path(sys.executable).expanduser()
    if not _is_relative_to_without_resolving_symlinks(executable, venv_dir):
        kept.append(
            {
                "path": str(executable.resolve()),
                "reason": "current omh command is not running from the install.sh-managed OMH venv",
            }
        )
        return

    for link in _managed_command_links(venv_dir):
        _collect_removal(link, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    _collect_removal(venv_dir, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)


def _managed_command_venv_dir() -> Path | None:
    explicit = os.environ.get("OMH_VENV_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "omh" / "venv").resolve()
    home = os.environ.get("HOME")
    if home:
        return (Path(home).expanduser() / ".local" / "share" / "omh" / "venv").resolve()
    return None


def _managed_command_links(venv_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    explicit_bin = os.environ.get("OMH_BIN_DIR")
    home = os.environ.get("HOME")
    if explicit_bin:
        candidates.append(Path(explicit_bin).expanduser() / "omh")
    elif home:
        candidates.append(Path(home).expanduser() / ".local" / "bin" / "omh")
    which = shutil.which("omh")
    if which:
        candidates.append(Path(which))
    if sys.argv and sys.argv[0]:
        candidates.append(Path(sys.argv[0]))

    links: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_symlink() or not _is_relative_to(resolved, venv_dir):
            continue
        seen.add(path)
        links.append(path)
    return links


def _managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    manifest_files = _manifest_team_profile_files(paths)
    if manifest_files:
        return manifest_files
    return _legacy_managed_team_profile_files(paths)


def _manifest_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.team_profile_manifest_dir.exists():
        return []
    files: list[Path] = []
    seen: set[Path] = set()
    for manifest_path in sorted(paths.team_profile_manifest_dir.glob("*.json")):
        manifest, _error = read_json_object_result(manifest_path)
        if manifest is None or manifest.get("schema_version") != TEAM_PROFILE_SCHEMA_VERSION:
            continue
        for raw_path in manifest.get("files", []):
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path).expanduser().resolve()
            if path in seen or not _is_relative_to(path, paths.hermes_agents_dir):
                continue
            seen.add(path)
            files.append(path)
    return files


def _legacy_managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.hermes_agents_dir.exists():
        return []
    files: list[Path] = []
    for path in sorted(paths.hermes_agents_dir.glob("omh-*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "schema_version: omh_team_profile_pack/v1" in text:
            files.append(path)
    return files


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_relative_to_without_resolving_symlinks(path: Path, parent: Path) -> bool:
    try:
        _normalize_without_final_symlink(path).relative_to(_normalize_without_final_symlink(parent))
    except ValueError:
        return False
    return True


def _normalize_without_final_symlink(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.parent.resolve() / expanded.name

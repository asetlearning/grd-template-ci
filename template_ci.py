"""Offline checks for a Gradarius Template Repository, and its INDEX.md generator (mathserver-mcp ADR-0003)."""
# Created by: Alex Myasnikov
# Date: November 11, 2026

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).parent / "schemas"
SNAPSHOT = "learning_objectives.json"
INDEX = "INDEX.md"
TEMPLATES = "templates"
FILES = ("script.ini", "template.yaml", "report.md", "report.json")


class SourceKind(StrEnum):
    """Only NEW is special here; the schema lists every kind."""
    NEW = "new"


class Status(StrEnum):
    APPROVED = "approved"
    ON_HOLD = "on_hold"


def script_hash(script: bytes) -> str:
    """Matches the Math API's script_hash: sha256 of the raw bytes, no normalization."""
    return sha256(script).hexdigest()


def snapshot_hash(objectives: list[dict]) -> str:
    """The Learning Objective list's hash. The math-api plugin computes the same one from list_learning_objectives."""
    rows = sorted(({"id": o["id"], "label": o["label"], "parent_id": o.get("parent_id")} for o in objectives),
                  key=lambda o: o["id"])
    return sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def schema_errors(name: str, data) -> list[str]:
    validator = Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text()))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}" for e in validator.iter_errors(data)]


@dataclass
class Template:
    uuid: str
    meta: dict | None = None
    report: dict | None = None
    errors: list[str] = field(default_factory=list)


def load_template(folder: Path, objective_ids: set[str]) -> Template:
    t = Template(folder.name)
    if missing := [f for f in FILES if not (folder / f).is_file()]:
        t.errors.append(f"missing {', '.join(missing)}")
    if (folder / "template.yaml").is_file():
        try:
            t.meta = yaml.safe_load((folder / "template.yaml").read_text())
        except yaml.YAMLError as e:
            t.errors.append(f"template.yaml isn't valid YAML: {e}")
        else:
            if errors := schema_errors("template", t.meta):
                t.errors += [f"template.yaml {e}" for e in errors]
                t.meta = None
    if (folder / "report.json").is_file():
        try:
            t.report = json.loads((folder / "report.json").read_text())
        except ValueError as e:
            t.errors.append(f"report.json isn't valid JSON: {e}")
        else:
            if errors := schema_errors("report", t.report):
                t.errors += [f"report.json {e}" for e in errors]
                t.report = None
    if t.meta:
        if t.meta["uuid"] != folder.name:
            t.errors.append(f"uuid {t.meta['uuid']} differs from the folder name")
        objectives = t.meta["learning_objectives"]
        if unknown := [o for o in [objectives["main"], *objectives["secondary"]] if o not in objective_ids]:
            t.errors.append(f"Learning Objectives not in {SNAPSHOT}: {', '.join(unknown)}")
    return t


def load_snapshot(repo: Path) -> tuple[list[dict], list[str]]:
    path = repo / SNAPSHOT
    if not path.is_file():
        return [], [f"{SNAPSHOT} is missing"]
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        return [], [f"{SNAPSHOT} isn't valid JSON: {e}"]
    if errors := schema_errors("learning_objectives", data):
        return [], [f"{SNAPSHOT} {e}" for e in errors]
    if data["hash"] != snapshot_hash(data["learning_objectives"]):
        return data["learning_objectives"], [f"{SNAPSHOT}: hash doesn't match its list"]
    return data["learning_objectives"], []


def load_repo(repo: Path) -> tuple[list[dict], list[Template], list[str]]:
    """The snapshot, every Template, and the snapshot's errors."""
    objectives, errors = load_snapshot(repo)
    ids = {o["id"] for o in objectives}
    root = repo / TEMPLATES
    folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return objectives, [load_template(folder, ids) for folder in folders], errors


def build_index(templates: list[Template], objectives: list[dict]) -> str:
    """Templates grouped by the Learning Objective tree of their main objective. Deterministic, so CI can compare."""
    by_id = {o["id"]: o for o in objectives}
    tree: dict = {}
    for t in templates:
        if not t.meta:
            continue
        path, node_id, seen = [], t.meta["learning_objectives"]["main"], set()
        while node_id in by_id and node_id not in seen:
            seen.add(node_id)
            path.insert(0, node_id)
            node_id = by_id[node_id]["parent_id"]
        node = tree
        for objective in path or ["(not in the snapshot)"]:
            node = node.setdefault(objective, {})
        node.setdefault("", []).append(t)

    def label(objective: str) -> str:
        return f"**{by_id[objective]['label']}** (`{objective}`)" if objective in by_id else objective

    def render(node: dict, depth: int) -> list[str]:
        lines = []
        for t in sorted(node.get("", []), key=lambda t: (t.meta["name"], t.uuid)):
            hold = " · on hold" if t.meta["status"] == Status.ON_HOLD else ""
            lines.append(f"{'  ' * depth}- [{t.meta['name']}]({TEMPLATES}/{t.uuid}/){hold}")
        for objective in sorted((k for k in node if k), key=lambda k: (by_id.get(k, {}).get("label", k), k)):
            lines.append(f"{'  ' * depth}- {label(objective)}")
            lines += render(node[objective], depth + 1)
        return lines

    body = render(tree, 0) or ["No Templates yet."]
    header = ["<!-- Generated by grd-template-ci from templates/ and learning_objectives.json. Don't edit by hand. -->",
              "", "# Templates", ""]
    return "\n".join(header + body) + "\n"


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    stale: bool = False
    summary: list[str] = field(default_factory=list)


def changed_template(changed: list[str]) -> tuple[str | None, list[str]]:
    """The one Template folder a pull request changes, if any, and errors. Snapshot-only pull requests change none."""
    uuids, errors = set(), []
    for path in changed:
        parts = Path(path).parts
        if not parts or parts[0] != TEMPLATES:
            continue
        if len(parts) < 3:
            errors.append(f"{path}: files under {TEMPLATES}/ must be in a Template folder")
        else:
            uuids.add(parts[1])
    if len(uuids) > 1:
        errors.append(f"a pull request changes one Template, this one changes {len(uuids)}: " + ", ".join(sorted(uuids)))
    return (next(iter(uuids)) if len(uuids) == 1 else None), errors


def base_source(read_base: Callable[[str], str | None], uuid: str) -> dict | None:
    """The Template's source before the pull request, or None if it's new or wasn't readable."""
    try:
        return (yaml.safe_load(read_base(f"{TEMPLATES}/{uuid}/template.yaml") or "") or {}).get("source")
    except (yaml.YAMLError, AttributeError):
        return None


def check(repo: Path, changed: list[str], pr_author: str,
          read_base: Callable[[str], str | None] = lambda path: None) -> Result:
    """read_base gives a file's text before the pull request, or None if it didn't exist."""
    result = Result()
    objectives, templates, result.errors = load_repo(repo)
    for t in templates:
        result.errors += [f"{TEMPLATES}/{t.uuid}: {e}" for e in t.errors]

    uuid, errors = changed_template(changed)
    result.errors += errors
    current = next((t for t in templates if t.uuid == uuid), None)  # None when the pull request deletes it
    if current and current.meta:
        source = current.meta["source"]
        # Only whoever adds or changes a copied source must have approved it, not everyone who edits the Template later.
        if (source["kind"] != SourceKind.NEW and source != base_source(read_base, uuid)
                and source["approved_by"] != pr_author):
            result.errors.append(f"{TEMPLATES}/{uuid}: source.approved_by is {source['approved_by']}, but the pull "
                                 f"request is by {pr_author}. Copied scripts need the author's approval.")
        result.summary.append(f"**Template:** {current.meta['name']} (`{uuid}`), source: {source['kind']}")
    script = repo / TEMPLATES / str(uuid) / "script.ini"
    if current and current.report and script.is_file():
        report = current.report
        result.stale = report["script_hash"] != script_hash(script.read_bytes())
        g = report["generate"]
        result.summary += [
            f"**Outcome:** {report['outcome']}",
            f"**Math Expert:** {'stale: script.ini changed since the review' if result.stale else 'matches script.ini'}",
            f"**generate_problems:** {g['ok']} ok, {g['failed']} failed, {g['not_run']} not run, "
            f"{g['distinct']} distinct, {len(g['findings'])} findings (Mathserver {report['mathserver_version']})",
            *(f"- Round {r['round']}: {r['verdict']}, {r['math_errors']} math errors, seeds "
              f"{', '.join(map(str, r['seeds']))}" for r in report["math_expert_rounds"]),
        ]

    index = build_index(templates, objectives)
    if not (repo / INDEX).is_file() or (repo / INDEX).read_text() != index:
        result.errors.append(f"{INDEX} is out of date: run `python template_ci.py index`")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="check a pull request")
    check_parser.add_argument("--repo", type=Path, default=Path("."))
    check_parser.add_argument("--changed", type=Path, required=True, help="file listing the changed paths, one per line")
    check_parser.add_argument("--pr-author", required=True)
    check_parser.add_argument("--base", help="the pull request's base commit, to read files as they were")
    index = sub.add_parser("index", help=f"rewrite {INDEX}")
    index.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    if args.command == "index":
        objectives, templates, _ = load_repo(args.repo)
        (args.repo / INDEX).write_text(build_index(templates, objectives))
        return 0

    def read_base(path: str) -> str | None:
        if not args.base:
            return None
        shown = subprocess.run(["git", "-C", str(args.repo), "show", f"{args.base}:{path}"], capture_output=True, text=True)
        return shown.stdout if shown.returncode == 0 else None

    result = check(args.repo, args.changed.read_text().splitlines(), args.pr_author, read_base)
    report = ["## Template checks", "", *result.summary, ""]
    report += [f"- ❌ {e}" for e in result.errors] or ["✅ All checks passed."]
    print("\n".join(report))
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"stale={str(result.stale).lower()}\n")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""Offline Template checks and the INDEX.md generator. The scripts are synthetic, never real Templates."""
# Created by: Alex Myasnikov
# Date: November 11, 2026

import json

import pytest
import yaml

import template_ci as ci

UUID = "3f2c1a9b-0000-4000-8000-000000000001"
OTHER = "3f2c1a9b-0000-4000-8000-000000000002"
OBJECTIVES = [
    {"id": "limits", "label": "Limits", "parent_id": None},
    {"id": "limits_rational", "label": "Limits of rational functions", "parent_id": "limits"},
    {"id": "algebra", "label": "Algebra", "parent_id": None},
]
SCRIPT = b"statement = test\n"


def meta(uuid=UUID, **overrides):
    return {"uuid": uuid, "name": "Test template", "description": None,
            "learning_objectives": {"main": "limits_rational", "secondary": []},
            "source": {"kind": "new", "ref": None, "approved_by": None},
            "origin": "agent", "status": "approved", **overrides}


def report(script=SCRIPT, **overrides):
    return {"script_hash": ci.script_hash(script), "mathserver_version": "2.54.0",
            "generate": {"ok": 20, "failed": 0, "not_run": 0, "distinct": 20, "findings": []},
            "math_expert_rounds": [{"round": 1, "seeds": [101, 108], "verdict": "pass", "math_errors": 0}],
            "outcome": "passed", **overrides}


def write_template(repo, uuid=UUID, template=None, rep=None, script=SCRIPT):
    folder = repo / "templates" / uuid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "script.ini").write_bytes(script)
    (folder / "template.yaml").write_text(yaml.safe_dump(template or meta(uuid)))
    (folder / "report.json").write_text(json.dumps(rep or report()))
    (folder / "report.md").write_text("# Report\n")


@pytest.fixture
def repo(tmp_path):
    snapshot = {"mathserver_version": "2.54.0", "hash": ci.snapshot_hash(OBJECTIVES), "learning_objectives": OBJECTIVES}
    (tmp_path / ci.SNAPSHOT).write_text(json.dumps(snapshot))
    write_template(tmp_path)
    ci.main(["index", "--repo", str(tmp_path)])
    return tmp_path


def run(repo, changed=(f"templates/{UUID}/script.ini",), author="alex"):
    return ci.check(repo, list(changed), author)


def reindex(repo):
    ci.main(["index", "--repo", str(repo)])


def test_a_valid_template_passes(repo):
    result = run(repo)

    assert result.errors == [] and not result.stale
    assert "**Outcome:** passed" in result.summary


def test_snapshot_only_pull_request_passes(repo):
    assert run(repo, changed=[ci.SNAPSHOT]).errors == []


def test_more_than_one_template_fails(repo):
    write_template(repo, OTHER)
    reindex(repo)

    [error] = run(repo, changed=[f"templates/{UUID}/script.ini", f"templates/{OTHER}/report.md"]).errors
    assert "changes 2" in error


def test_uuid_must_match_the_folder(repo):
    write_template(repo, template=meta(uuid=OTHER))

    assert any("differs from the folder name" in e for e in run(repo).errors)


@pytest.mark.parametrize("change", [
    {"status": "published"},
    {"origin": "robot"},
    {"uuid": "not-a-uuid"},
    {"learning_objectives": {"main": "limits"}},
    {"extra": 1},
])
def test_schema_violations_fail(repo, change):
    write_template(repo, template=meta(**change))

    assert any("template.yaml" in e for e in run(repo).errors)


def test_missing_files_fail(repo):
    (repo / "templates" / UUID / "report.md").unlink()

    assert any("missing report.md" in e for e in run(repo).errors)


def test_unknown_learning_objective_fails(repo):
    write_template(repo, template=meta(learning_objectives={"main": "limits", "secondary": ["calculus"]}))
    reindex(repo)

    assert run(repo).errors == [f"templates/{UUID}: Learning Objectives not in learning_objectives.json: calculus"]


def test_tampered_snapshot_fails(repo):
    data = json.loads((repo / ci.SNAPSHOT).read_text())
    data["learning_objectives"].append({"id": "x", "label": "X", "parent_id": None})
    (repo / ci.SNAPSHOT).write_text(json.dumps(data))

    assert any("hash doesn't match" in e for e in run(repo).errors)


def test_changed_script_marks_the_review_stale_without_failing(repo):
    (repo / "templates" / UUID / "script.ini").write_bytes(SCRIPT + b"# edited\n")

    result = run(repo)

    assert result.stale and result.errors == []
    assert any("stale" in line for line in result.summary)


def test_stale_index_fails(repo):
    write_template(repo, template=meta(name="Renamed"))

    assert run(repo).errors == ["INDEX.md is out of date: run `python template_ci.py index`"]


@pytest.mark.parametrize("kind", ["existing", "outside"])
def test_copied_script_needs_the_pull_request_authors_approval(repo, kind):
    ref = OTHER if kind == "existing" else "Stewart, Calculus, 5.3 #12"
    write_template(repo, template=meta(source={"kind": kind, "ref": ref, "approved_by": "alex"}))

    assert run(repo, author="alex").errors == []
    assert any("Copied scripts need the author's approval" in e for e in run(repo, author="someone").errors)


@pytest.mark.parametrize("source", [
    {"kind": "existing", "ref": None, "approved_by": "alex"},  # no ref
    {"kind": "outside", "ref": "a book", "approved_by": None},  # no approval
    {"kind": "existing", "ref": "a book", "approved_by": "alex"},  # existing needs a Gradarius uuid
    {"kind": "new", "ref": OTHER, "approved_by": None},  # new has no source
])
def test_source_must_be_complete(repo, source):
    write_template(repo, template=meta(source=source))

    assert any("template.yaml source" in e for e in run(repo).errors)


def test_files_loose_in_templates_fail(repo):
    assert any("must be in a Template folder" in e for e in run(repo, changed=["templates/x.ini"]).errors)


def test_deleting_a_template_passes(repo):
    import shutil
    shutil.rmtree(repo / "templates" / UUID)
    reindex(repo)

    assert run(repo).errors == []


def test_index_groups_by_the_objective_tree(repo):
    write_template(repo, OTHER, template=meta(OTHER, name="Another", status="on_hold",
                                             learning_objectives={"main": "algebra", "secondary": []}))
    reindex(repo)

    body = (repo / ci.INDEX).read_text().split("# Templates\n\n")[1]
    assert body == (
        "- **Algebra** (`algebra`)\n"
        f"  - [Another](templates/{OTHER}/) · on hold\n"
        "- **Limits** (`limits`)\n"
        "  - **Limits of rational functions** (`limits_rational`)\n"
        f"    - [Test template](templates/{UUID}/)\n"
    )


def test_snapshot_hash_ignores_order_and_extra_fields():
    shuffled = [dict(o, extra=1) for o in reversed(OBJECTIVES)]

    assert ci.snapshot_hash(shuffled) == ci.snapshot_hash(OBJECTIVES)


def test_cli_prints_the_summary_and_fails_on_errors(repo, tmp_path_factory, capsys, monkeypatch):
    changed = tmp_path_factory.mktemp("ci") / "changed.txt"
    changed.write_text(f"templates/{UUID}/script.ini\n")
    output = changed.parent / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    (repo / "templates" / UUID / "script.ini").write_bytes(b"changed\n")

    assert ci.main(["check", "--repo", str(repo), "--changed", str(changed), "--pr-author", "alex"]) == 0
    assert "stale" in capsys.readouterr().out
    assert output.read_text() == "stale=true\n"

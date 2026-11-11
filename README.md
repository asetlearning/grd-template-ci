<!--
Created by: Alex Myasnikov
Date: November 11, 2026
-->

# grd-template-ci

Shared CI for Gradarius Template Repositories. It holds the schemas, the offline checks, the `INDEX.md` generator and a reusable workflow. Every team repository calls the workflow, in this organization or any other.

It holds code only. Each team repository keeps its own Learning Objective snapshot.

## Use it in a team repository

Add `.github/workflows/check.yml`, pinned to a release:

```yaml
name: Template checks
on: pull_request
jobs:
  check:
    uses: asetlearning/grd-template-ci/.github/workflows/check.yml@v1
    permissions:
      contents: read
      pull-requests: write
      issues: write
```

The team repository keeps its Learning Objective snapshot in `learning_objectives.json` at its root.

## What a pull request is checked for

It fails when:
- `learning_objectives.json` doesn't match its schema, or its `hash` doesn't match its list
- a Template folder misses one of `script.ini`, `template.yaml`, `report.md` and `report.json`
- `template.yaml` or `report.json` doesn't match its schema (`schemas/`), or `uuid` differs from the folder name
- a Learning Objective isn't in the snapshot
- it changes more than one Template, or puts files directly in `templates/`. A pull request that changes no Template, such as a snapshot update, is fine.
- the pull request adds a copied script (`source.kind` is `existing` or `outside`) or changes its `source`, and `source.approved_by` isn't the pull request's author. Later edits by others don't need a new approval.
- `INDEX.md` is out of date

When `script_hash` in `report.json` doesn't match `script.ini`, it labels the pull request "Math Expert: stale" but doesn't fail. The results, with the report's outcome and rounds, go in a pull request comment that each run updates.

Pull requests from forks get a read-only token, so the comment and label steps fail there. Authors push branches to the team repository instead.

Without branch protection, a failed check reports but doesn't block a merge.

## Template source

`source.kind` in `template.yaml`:
- `new`: the script was written for this Template. Templates given to the author only as examples don't make it a copy.
- `existing`: copied from a Gradarius template, edited or not. `ref` is its uuid.
- `outside`: copied from anywhere else. `ref` is a citation or URL.

A copied script needs `approved_by`: the GitHub login of the author who approved using it.

## Shared definitions

The math-api plugin writes these files, so it must compute the same values as `template_ci.py`:
- `script_hash(script)`: sha256 of the raw bytes of `script.ini`, as the Math API computes it
- `snapshot_hash(objectives)`: sha256 of the list as compact JSON, each entry reduced to `id`, `label` and `parent_id`, sorted by `id`, with sorted keys

## Run locally

```bash
pip install -r requirements.txt
python template_ci.py index --repo <team-repo>     # rewrite INDEX.md
python -m pytest                                   # tests (needs pytest)
```

## Releases

Team repositories pin a tag such as `v1`. Compatible changes move `v1`; a breaking change gets `v2`. When releasing a new major, also change the `ci-ref` default in `check.yml`.

The design is in mathserver-mcp ADR-0003. The work is tracked in mathserver-mcp #15.

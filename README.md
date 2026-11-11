<!--
Created by: Alex Myasnikov
Date: November 11, 2026
-->

# grd-template-ci

Shared CI for Gradarius Template Repositories. It holds the schemas, the offline checks, the `INDEX.md` generator and a reusable workflow. Every team repository calls the workflow, in this organization or any other.

It holds code only. Each team repository keeps its own Learning Objective snapshot.

Pin a release in the team repository:

```yaml
jobs:
  check:
    uses: asetlearning/grd-template-ci/.github/workflows/check.yml@v1
```

The design is in mathserver-mcp ADR-0003. The work is tracked in mathserver-mcp #15.

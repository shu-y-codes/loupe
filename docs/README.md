# Loupe documentation

These guides explain the running application for reviewers, developers, and
contributors.

They are explanatory, not normative. Product behavior and calculation truth
live in [`specs/`](../specs/). If a guide disagrees with a specification, the
specification wins. Execution status and remaining work live in
[`plans/`](../plans/).

## Guides

- **[How Loupe works](how-loupe-works.md)** — architecture, data flow, API
  calls, package boundaries, and extension points.
- **[What the Loupe pages mean](metrics-primer.md)** — how to read Overview,
  Review, quality families, charts, and metrics.
- **[CLG26 data journey](clg26-data-journey.md)** — a reproducible example
  from real source rows through DuckDB and FastAPI to the React charts.
- **[How Loupe tests work](how-tests-work.md)** — test layers, fixtures,
  integration boundaries, and how to run the suite.

## Suggested reading

For a product review, start with the page guide and then follow the CLG26
example. For implementation work, start with the architecture guide and use
the testing guide alongside the relevant specification.

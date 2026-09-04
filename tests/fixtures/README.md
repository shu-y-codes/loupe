# Fixtures

Tiny, hand-built, committed CSVs, each carrying exactly one planted defect, so a failing test
names the rule it broke. The real corpus is unsuitable as a unit-test fixture: it is 15.5 MB,
it cannot be committed, and it is far too clean to exercise the rule catalogue
(`specs/sample-corpus.md` §8).

CSV rather than Parquet on purpose — readable in a diff, editable without tooling, and a
fixture change reviews like any other code change.

Slice 1 owns the ingest fixtures below. The rule fixtures arrive with slice 2.

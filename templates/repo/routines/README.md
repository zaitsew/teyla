# Routines

A routine is one repeatable unit of work with one artifact. If it produces two
different deliverables, it is two routines — a routine with two outputs can
never be scheduled or evaluated cleanly, because "did it work" has two
different answers.

Copy `example.yml`, don't edit it — it's the reference schema, and other
routines will diff against it.

Every routine writes into `runs/<date>/` — gitignored, regenerable. What a
routine must not throw away goes into a committed doc instead (`NOTES.md`,
`docs/DECISIONS.md`), not into `runs/`.

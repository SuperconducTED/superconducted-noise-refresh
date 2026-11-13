# <YYYY-MM-DD>: <slug>

> Copy this template to `docs/implementations/YYYY-MM-DD-<slug>.md` for every meaningful
> change. A commit message can summarise; the durable record lives here.

## Problem / Motivation

What gap or risk did this change address? Name the roadmap stage, protocol section or known
gap that triggered the work. One paragraph.

## What changed

| File | One-sentence description |
| --- | --- |
| `path/to/file.py` | What it does after this change. |

## Implementation approach

The "how." Describe the pattern, algorithm or strategy, and state the contract of every new
public function: inputs, outputs, side effects and the invariants it relies on.

## Mathematical / Statistical details

Required if the change involves any formula, statistical test or numeric algorithm. Describe
it in plain English with notation a future reader can audit without reading the code.

Skip this section only for purely structural changes, and then write "N/A, purely structural"
so the omission is visibly deliberate.

## Design decisions

What alternatives were considered and why was this approach chosen over them? Say which
choices are still open and whose they are.

## Verification

Concrete, runnable steps, and what each printed when it was last run. Label every number as
exploratory or confirmatory (see `PROTOCOL.md` section 3).

## Related docs

- `PROTOCOL.md`, `ROADMAP.md` sections
- Result folders under `results/`
- Other implementation documents

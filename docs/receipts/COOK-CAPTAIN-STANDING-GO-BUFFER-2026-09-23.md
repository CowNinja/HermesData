# COOK-CAPTAIN-STANDING-GO-BUFFER-2026-09-23

Captain standing order via Firstmate: keep cooking Content factory / POSSE.
Standing GO for Buffer Share-now. The autopost lock stays shut.

Date: 2026-09-23
Repo: HermesData (this GitHub checkout)
Status: receipt only. ENGINE is not in this tree. No second pipeline was added.

## Did

Searched this checkout for the content-engine / POSSE / Buffer Free ENGINE.
It is not here. Wrote this design receipt and stopped.

## Paths checked

- Filename and content search for `content-engine`, `content_engine`, `POSSE`, `LIVE_UNLOCKED`, `CAPTAIN_GO`, `Share-now`, `Content factory`, `Buffer Free`.
- `state/` contains only `discord_audit_14day.json`, `discord_audit_14day_report.md`, and `prompts/qwythos_system_primer.md`. No `state/content-engine`.
- No `docs/` tree existed before this receipt.
- `git log --all` has no commits matching those terms.
- Unrelated hits ignored: FIFO buffers in `scripts/inference_queue.py`, Windows copy buffering, ctypes buffers. Those are not the Buffer scheduler.

## Guessed

The standing order pointed at a DELL mirror under `state/content-engine` (or a nearby note on DELLWinn11). That tree is not in this checkout. The path was not opened from here, so it is a hint, not a verified location.

## Skipped

- No engine module, gate, client, or scheduler.
- No Buffer Share-now call.
- No permalinks (none invented).
- No LIVE lock file created or rewritten.
- No second content pipeline.

## Design (for the real ENGINE, when that tree is the one being cooked)

This is the standing-GO exception. It is not an implementation in HermesData.

### Lock

`LIVE_UNLOCKED` is the default autopost lock. Its legal steady value is false.
A standing GO does not flip that lock. This cook must not assign the lock to true.
Door opens stay captain door-by-door. One Buffer exception does not open other networks, later packs, or autopost.

### Stamp required on the pack

Share-now may be considered only when the pack carries an explicit captain stamp. Either:

1. `mark=APPROVED` and `approved=True` (both required), or
2. a `CAPTAIN_GO` file on the pack.

A draft, a comment, or one of those fields alone is not a stamp.

### Gate

| LIVE lock | Pack stamp | Result |
|-----------|------------|--------|
| false | absent | Refuse Share-now. |
| false | `mark=APPROVED` and `approved=True`, or a `CAPTAIN_GO` file | Allow the Share-now gate path. |
| false | stamp present, but the ENGINE Share-now path is not wired | Dry-run only. Record that the gate would pass. Do not post. Do not invent a permalink. |

Standing GO is the per-pack exception above. It is not a LIVE unlock.

### Self-test the real ENGINE must run (not run here)

1. LIVE false and no APPROVED stamp -> refuse.
2. LIVE false and APPROVED stamp (both fields, or a `CAPTAIN_GO` file) -> allow the Share-now gate path, or dry-run if that path is still unwired.
3. After those checks, the LIVE lock file bytes are still false.

There is no LIVE lock file in this checkout, so those three checks were not executed against an engine. Running them here would mean inventing the pipeline this receipt refuses to create.

## Measure

This file is the only change. Re-search after the write:

- No content-engine implementation in the tree.
- No LIVE lock file.
- The lock is not assigned true anywhere in this commit.

STOP.

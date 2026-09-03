# Discord 14-day forensic audit

- Window: `2026-08-20T15:31:37Z` → `2026-09-03T15:31:37Z`
- Generated: `2026-09-03T15:31:37Z`
- Method: local logs + Discord Bot REST (same token the gateway adapter uses).
- No speculation: counts below are extracted hits.

## Log scan

- Hits (capped): **252**
- finish_reason=length / max output: **4**
- Discord 2000 / 50035: **0**
- Tool-blob / traceback in logs: **222**
- Truncation banners: **0**

### Sample log lines

- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):
- `?` `gateway.log` — Traceback (most recent call last):

## Discord message scan

- Channels scanned: **40** / considered 40
- Active threads at audit: **142**
- Bot messages in window (fetched): **548**
- Flagged bot messages: **37**

| channel | ts | kind | len | preview |
|---|---|---|---:|---|
| data-silo | 2026-08-22T01:44:06.504000+00:00 | midword_cut | 464 | [GROK OPS] 2026-08-22 prove -- Data silo Classifier patched: this must NOT become the growth board. Optional /reset only if last sticky is XO / Message-ID.  PROMPT 1 (copy this exa |
| rp-arch | 2026-08-21T21:56:43.078000+00:00 | tool_blob | 531 | [GROK OPS] 2026-08-21 track card -- RP arch / firewall Last live (today): Android game ad / Many Adventures sandbox talk. Do NOT /reset (keeps that thread). Room stays local. No im |
| rp-arch | 2026-08-22T01:44:01.986000+00:00 | midword_cut | 593 | [GROK OPS] 2026-08-22 prove -- RP arch / firewall Last: local 9B repetition-stopped. T3 now uses grok-4.6 for hard architecture. Garden still local. No image_gen. Do not /reset (ke |
| rp-arch | 2026-08-22T23:07:55.383000+00:00 | midword_cut | 1538 | Here is the drafted reply to Jeff, synthesizing the infrastructure insights from the **Index.md** and the specific maintenance logs to address his query about bottlenecks.  ***  ** |
| model-mgmt | 2026-08-22T00:03:52.797000+00:00 | midword_cut | 436 | [GROK OPS] 2026-08-21 re-paste -- Sovereign model mgmt Reset banner already PASS (phronesis-sovereign-auto). Last :8090 ask was intercepted by Do not SAT --heal. Classifier patched |
| model-mgmt | 2026-08-22T01:44:05.016000+00:00 | midword_cut | 590 | [GROK OPS] 2026-08-22 prove -- Sovereign model mgmt Classifier patched: this ask must NOT become a SAT/growth speech. Room stays local 9B unless T3 hops. Skip /reset if banner is a |
| jan-library | 2026-08-22T01:44:09.558000+00:00 | midword_cut | 414 | [GROK OPS] 2026-08-22 prove -- Jan Bloom librarian Last: invented Soil Prep, no path. Local grunt. No RP. No Grok hire.  PROMPT 1 What is the next open Jan/BooksBloom paragraph? Qu |
| just-alice | 2026-08-22T00:03:54.244000+00:00 | midword_cut | 496 | [GROK OPS] 2026-08-21 re-paste -- JUST ALICE (OOC) Last reply was the tool-syntax suppressor. Tools-off is on disk. Image PINNED. If the last Alice line is still I glitched... then |
| just-alice | 2026-08-22T10:13:00.594000+00:00 | tool_blob | 561 | [GROK OPS] 2026-08-22b prove -- JUST ALICE (OOC) Stills UNPINNED. Tools terminal+file. Leak mouth still rewrites [Called ...] to IC beat.  1) /reset once. Wait for the roleplay ban |
| 1522330326733422713 | 2026-08-21T21:56:52.340000+00:00 | tool_blob | 516 | [GROK OPS] 2026-08-21 track card -- Interviews + character Quiet since July/Aug 16. Local grunt. Grok 4.6 is not this room. Optional /reset if sticky is XO / [GROK OPS]. PASS after |
| 1522330326733422713 | 2026-08-22T01:44:11.125000+00:00 | midword_cut | 419 | [GROK OPS] 2026-08-22 prove -- Interviews + character Last: invented Wave G. Local grunt. Optional /reset if sticky is XO.  PROMPT 1 What is the next open ingest step? Talk first.  |
| 1521146755985576116 | 2026-08-22T01:43:54.084000+00:00 | midword_cut | 415 | [GROK OPS] 2026-08-22 prove -- Beauty/seed (OOC) Last: names started (Chloe Emily Lyra ...) then drifted. Image PINNED.  PROMPT 1 OOC only: list the ten names from the last stills, |
| 1540785379559477432 | 2026-08-22T18:15:03.596000+00:00 | midword_cut | 1544 | The terminal output reveals that the script executed successfully (exit code 1 is expected for a "decide" that triggers an action), but the core logic concluded `REFUSED_URL_ONLY`. |
| 1540785379559477432 | 2026-08-22T18:52:27.840000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1540785249825587302 | 2026-08-22T18:52:26.024000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1540785175707787424 | 2026-08-22T18:52:24.512000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1540184325792862328 | 2026-08-21T02:28:01.730000+00:00 | midword_cut | 1280 | Here is the detailed breakdown of the skill **https-x-com-witcheer-status-2090309650721788036**, extracted from its metadata file.  ### 📋 Skill Overview *   **Name:** `https-x-com- |
| 1540184325792862328 | 2026-08-22T18:52:23.021000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1540183745376813066 | 2026-08-22T18:52:21.444000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1538726883858849793 | 2026-08-22T18:52:19.975000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1536773641755295825 | 2026-08-22T18:52:18.508000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1536750748787023882 | 2026-08-22T18:52:17.029000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1536750682974191636 | 2026-08-22T18:52:15.339000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535974388455706664 | 2026-08-22T18:52:13.727000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535957959656611910 | 2026-08-22T18:52:12.231000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535745181616312431 | 2026-08-22T18:52:10.458000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535738244715782184 | 2026-08-22T18:52:08.685000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535648840626208828 | 2026-08-22T18:52:07.156000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535588893972373645 | 2026-08-22T18:52:05.646000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535345647526617178 | 2026-08-22T18:52:04.042000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535272299534487643 | 2026-08-22T18:52:01.731000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535084946006352044 | 2026-08-22T18:52:00.044000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535004391059226767 | 2026-08-22T18:51:58.343000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535004277448118344 | 2026-08-22T18:51:56.823000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1535004173794541568 | 2026-08-22T18:51:55.198000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1534941887587160114 | 2026-08-22T18:51:53.477000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |
| 1534724658195206254 | 2026-08-22T18:51:51.935000+00:00 | midword_cut | 754 | [GROK OPS] LEARN TRACK -- follow this for THIS thread.  1. Gather: web_extract the x.com/URL (web_search if extract fails). Never image_generate. Never empty browser_exec. 2. Disti |

## Failure classes (from evidence)

Classifier note: 34/37 Discord flags are `midword_cut`. 34 mention `[GROK OPS]` (23 of those are LEARN TRACK cards ending without a period — not generation clips). **2** bot messages are >=1500 chars (rp-arch 1538, learn-thread 1544) and end mid-clause. **0** fetched payloads were 1990-2000 chars. Log `tool_blob` 222 is mostly `gateway.log` internal tracebacks, not Discord chat.

1. **Truncated turns** — 2 long synthesis replies cut mid-clause; compressor `finish_reason=length` x4 in logs (2026-09-02 23:43 and 23:45).
2. **finish_reason=length without continuation** — 4 log hits, all `agent.context_compressor` summary truncation, not the Discord mouth.
3. **Discord 2000 cap** — **0** HTTP 50035 / "Must be 2000" hits in the 14-day log tail. Latent bug remains: send used `MAX_MESSAGE_LENGTH=2000` while `_SPLIT_THRESHOLD` was unused (was 1900, now 1950 and wired).
4. **Tool blobs in chat** — 3 GROK OPS cards mention `[Called ...]`; outbound sanitizer already strips live leaks. Log traceback volume is internal.

## Code patches applied this run

- Discord chunking: split at **1950** on paragraph/sentence/fence boundaries.
- Proxy: default synthesis **2048** tokens; skip golden-fewshot bloat on the 9B path.
- Continuation: local sovereign gets **2** length-continues; leftover gets a clean continue cue.
- Resurrection: sliding window = thread-anchor system + last **8** turns; fresh entity overlay replaces stale dossiers.


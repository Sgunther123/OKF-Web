# CLAUDE.md — working agreement for this repository

OKF-Web is an open toolchain that builds, verifies, publishes, and evaluates an
Open Knowledge Format (OKF v0.2) bundle for an ecommerce site: LLM-populated,
human-verified, consumed by AI engines (Generative Engine Optimization).
Python 3.10+, stdlib-first, `src/` layout.

**First action in any session: read `.claude/MEMORY.md`.** This file holds the
durable rules; MEMORY holds the mutable state (current versions, metrics,
commit histories, environment quirks, and the user's operating rhythm).

## Git rules (non-negotiable)

- Develop on `claude/geo-ecommerce-evaluation-system-qzv3qn`. Push with
  `git push -u origin <branch>`; on network failure retry up to 4 times with
  2/4/8/16s backoff.
- `main` is protected by the ruleset "Branch Protection": required check
  `test-and-lint` with "up to date", linear history, no force push, no
  deletion, empty bypass list (CONTRIBUTING.md states the rule and how to
  verify it: the GitHub `list_branches` tool's `protected` field, and a
  plain read of `/repos/<owner>/<repo>/rules/branches/main`). The
  fast-forward push needs the branch head's CI green first: wait for the
  check, then push; a refused push means the check has not passed.
  Nothing on `main` is ever amended or rewritten; a mistake gets a new
  commit. The ruleset is the maintainer's to apply or change, in the
  repository settings; the session cannot.
- **Never push to any other branch unprompted.** `main` moves only when
  the maintainer explicitly asks, and only as a fast-forward:
  `git push origin <sha>:refs/heads/main`. The push is its own record:
  no MEMORY commit before or after it; MEMORY's positions section states
  the rule, and the next content commit refreshes the sha.
- Never create a pull request unless explicitly asked.
- Commit style: imperative subject, body explains why. End every commit
  message with the trailer lines the harness supplies for the current
  session (`Co-Authored-By:` + `Claude-Session:`). They are
  session-specific: take them from the current session's instructions,
  never copy them from history.
- No model identifiers in any pushed artifact (code, docs, comments); the
  harness-mandated commit trailers are the sole exception. The rule bars
  the **authoring session's identity**, not product configuration:
  functional model references, such as OKF provenance actors
  (`generated.by`, SPEC §7 `<producer>/<version>`) and the CLI's default
  LLM model id, are data the product needs, and stay.
- GitHub operations go through the GitHub MCP tools; there is no `gh` CLI in
  this environment.

## Two repositories, one history

- This repository is **strictly open source** (Apache-2.0). A hosted
  edition of the toolchain, run as a service, is developed in its own
  private repository; its plans, pricing, operations and records live
  there and never here. `tests/test_public_surface.py` is the executable
  form of that rule: it fails on the terms that would carry such material
  in.
- Features land here first; the hosted edition cherry-picks them from its
  own side, on the maintainer's request, with its own procedure and its
  own records. Nothing of its positions, picks or state is recorded here:
  this repository's MEMORY is authoritative for this repository alone.

## Verification loop (before every commit)

1. `rm -f bundle-example/.embeddings.json bundle-example/.concepts-cache.json`
   — live runs (and the test suite) leave working-state caches behind
   (gitignored, but never let them near a commit).
2. `python -m pytest -q` **twice** — guards ordering/seed nondeterminism,
   which has produced a real CI failure before (MEMORY, "incidents").
3. `python -m okf_web.cli lint bundle-example --strict` → exactly **0 errors,
   0 warnings** (a test asserts both).
4. `python -m okf_web.cli evaluate bundle-example --dry-run` → hit rate 1.0 at
   the reference numbers recorded in MEMORY.
5. Never hand-edit measured numbers. If behavior changes them, re-measure and
   update `bundle-example/evaluations/geo-scorecard.md` plus every doc echoing
   them (DESIGN, EVALUATION, EXPANSION, MEASUREMENT) from actual output —
   the scorecard proves the lift before the docs claim it. The numbers
   this loop measures are the dry run's; the example scorecard's judged
   figures were written with the example (its body says so) and are
   never quoted as measurements.

## Invariants (do not break)

- **Live values are never static claims**: prices, stock, delivery estimates,
  open-right-now, shelf quantities, quoted wholesale/contract prices. They
  ship as Attested Computation capabilities; feed ingestion drops them
  (`feed.DROPPED_FIELDS`) from both concept text and the row hash. The rule
  survives every derived surface: `jsonld/` Product markup carries no
  offers/price/availability, and `llms.txt` states none.
- **The derived tier restates only named-human-vouched concepts**
  (`structured.py`: JSON-LD gate on `TRUST_HUMAN` or `TRUST_HUMAN_BATCH`;
  every object carries `subjectOf` back to its bundle concept). Links
  (llms.txt) may cover the whole published set — navigation is not
  restatement. Types with no faithful schema.org mapping emit nothing.
- **Attestation tiers never blur** (R3): `human:` = per-item review;
  `human-batch:` = wholesale sign-off → `human-attested`. Only `human:`
  satisfies E010. batch-approve must keep stamping `human-batch:` — its
  speed is a feature, its label is the honesty. `review._actor_for`
  derives the prefix from the command and strips any prefix typed into
  `--by` (GAPS item 5); a root index's `x_geo.reviewers`, when present,
  is enforced by `review` and lint W042.
- **Mutating flows are never capabilities** (registration, claim filing, RFQ
  submission, order placement). Only read-only, token-scoped status lookups.
  The MCP bridge is GET-only, never splices undeclared arguments into URLs,
  and refuses an executor template with a placeholder in its scheme or
  host (lint E023 says the same); its stdio loop answers an invalid
  request with `-32600` and an unexpected exception with `-32603`, and
  no input line ends the session.
- **Effective risk**: gate on `Concept.is_high_risk` (declared risk `a` OR
  type in `model._HIGH_RISK_TYPES` — Product Passport, Trade Program), never
  on the raw `risk` field alone.
- **Single write gate**: every pipeline write of a concept file goes through
  `surveyor.place_draft` (path stability; collision handling, where an
  occupant owned by a different URL or by none is a collision; protection
  of human-approved and `stable` content; producer paths confined to
  content directories — `surveyor.PRODUCER_DENIED_DIRS`; `resource` pinned
  to the surveyed URL). Never write concept files ad hoc in pipeline code.
  Path stability is **per concept**: a page keeps every concept it
  yields. A draft is written in place, takes over a concept of its own
  type that the producer renamed, or is a further concept of the same
  page; a producer that yields several drafts for one URL declares
  their paths in one `claimed` set, as `survey_page` does.
- **Derived and rendered text is inert** (EDGE-CASES E3): JSON-LD is
  serialized with `structured.dumps_script_safe`; only `http(s)` resources
  are ever linked (viewer, linkmap, JSON-LD `url`; lint E020/W038); the
  evaluation context neutralizes `<concept` delimiters in bodies
  (`evaluator.render_context`); the parse cache is keyed by content hash
  and any malformed entry is a miss, never an exception.
- Human-approved content is never machine-overwritten — changes become drift
  proposals under `_review/proposed/`.
- **A dist is never the bundle** (EDGE-CASES E1): `publisher.check_dist`
  refuses the bundle itself, anything inside it, anything containing it,
  the home and the working directory, and a non-empty directory without
  the `.okf-dist` marker of a previous publish (only `--force` overrides
  the last; a `manifest.json` alone is any web app's). The remote mirror
  (`remote.check_mirror_dir`) holds the same line for `--cache-dir`:
  never the home or working directory, never a non-empty directory
  without its own `.okf-remote.json`, and it prunes only files its
  own previous manifest listed. Every dist carries the hidden `.okf-dist` marker;
  the loader and the publisher skip marked directories and symlinks, so a
  stray copy never becomes knowledge. `load_bundle` on a missing directory
  raises `BundleNotFound` (CLI exit 2), never an empty bundle.
- **Every outbound fetch goes through `net.safe_fetch`** (EDGE-CASES E2):
  `http`/`https` only; loopback, private, link-local, reserved, multicast
  and unspecified hosts refused in every spelling and on every resolved
  address at connection time; redirects re-checked; bodies capped under a
  deadline. `--allow-private-hosts` is the only opt-out and never the
  default. Never call `urllib.request.urlopen` (or any raw socket) from
  pipeline code; a request with a body is `safe_fetch(method="POST",
  data=...)`, the same door (GET and POST are the only methods). The
  door asks for identity encoding and decodes a gzip or deflate answer
  under the cap, so a body is always the document; never decompress or
  parse around it. The
  subscription LLM client runs the agent CLI with tools
  disabled (`--tools ""`), no MCP servers from the operator's settings
  (`--strict-mcp-config`, required), the rules on `--system-prompt`, in
  an empty working directory, and refuses a CLI without those flags or
  whose `--help` probe failed for any reason but a missing binary.
  Behind a proxy the target is still resolved and a private answer
  refused (`net._vet_proxied_target`); the deadline covers every
  redirect hop and a socket timeout is a `FetchTimeout`.
- **One error family, one exit table** (U4, `errors.py`): every error
  the toolchain raises on purpose inherits `OkfWebError` and either
  `Refusal` (exit 2: the command refused to act) or `Failure` (exit 1:
  it acted and the outcome failed); `cli.main` has one `except` and
  `errors.exit_code` is the table — never map a class in a command. A
  class that is both (`UnsafeDist`, a refused `PublishError`) is a
  refusal. New exception classes inherit a marker, and a parametrized
  test drives every class through `main`. **The library surface is
  declared**: `docs/API.md` lists the names that stay put, every module
  carries `__all__`, and a test checks both; shared primitives have one
  home each (`model.utc_instant`, `model.slug`, `model.file_digest`,
  `net.origin`, `FetchPolicy.derive`, `Bundle.site`) and the tunables
  live in `config` (`WELL_KNOWN_PATH`, `DEFAULT_MODEL`, `user_agent`) —
  a static test refuses a second spelling of any of them. The
  underscore aliases `cli._add_llm_args`, `cli._llm`,
  `cli._question_packs`, `model._as_date`/`_as_instant`/`_linked` and
  the report and structured ones stay only until the hosted edition's
  adapter lands (its H4).
- **Every pipeline write is atomic and every clock is UTC** (EDGE-CASES
  A5/A6): files are written through `model.write_atomic` (temporary
  sibling + `os.replace`), never a bare `write_text`; the default
  clocks are `model.utc_now()` / `model.utc_today()`, never
  `date.today()` or a naive `datetime.now()`; writing commands hold
  `<bundle>/.okf-lock` (`model.bundle_lock`, wired once in `cli.main`
  through `_lock_for`), and only `survey` and `init` may create the
  bundle directory.
- **No concept is immortal** (GAPS item 3): `surveyor.place_draft`
  stamps the type's freshness SLA (`model.FRESHNESS_SLA_DAYS`) when a
  producer left `stale_after` empty, and lint W041 flags a stable
  concept of an SLA type without one. Publish builds into a hidden
  sibling and swaps it in whole (`publisher._staging`, item 4);
  `manifest.json` carries `stale_after`/`verified_at` per concept and
  JSON-LD `subjectOf` carries `expires`/`dateModified` (item 7). A
  Promotion is valid *through* `ends_at`: the surveyor stamps
  `stale_after` at the following midnight UTC and W027 accepts nothing
  later (U3) — the last day of a sale is never withheld as stale.
  `drift` leaves feed-derived concepts (`generated.by ==
  feed.FEED_ACTOR`) to the next ingest; `report` holds the bundle lock.
- **The report and the viewer show only measured facts** (`report.py`,
  `viewer.py`; the viewer's `REVENUE_MOMENTS` sentences are editorial
  vocabulary naming the stakes, never numbers): every number
  is read from the recorded scorecard or recomputed deterministically
  at render time (the detail tier's retrieval rows — no LLM,
  byte-identical double render). Per-question judged verdicts come
  solely from what the scorecard records (its results table's
  `answered` column, located by header, and its gap-bullet ids, and
  only when that table carries a yes/no cell at all);
  nothing is ever inferred or invented, found ≠ answered stays
  labeled, and the page ships zero scripts. The scorecard is read
  only at `evaluations/geo-scorecard.md` (lint E022 for a `GEO
  Scorecard` elsewhere or in draft); its counts render as whole
  numbers or as escaped text (`report.count_cell`); a dry run records
  `found`, never `answered`, and renders as not judged; the footer
  states the view from `x_geo.evaluated`; a localized view's scorecard
  lives at `evaluations/geo-scorecard.<lang>.md`. Judge verdicts are
  JSON booleans or yes/true (`evaluator._verdict_flag`); nothing else
  counts as answered.
- **A comparison is measured or absent** (EVALUATION §3; the audit of
  2026-11-10): `x_geo.baseline` reaches a scorecard only through
  `write_scorecard`, from a `baseline.measure` of the same run
  (`evaluate --baseline`): the store's own pages, read as text
  through the one fetch door, searched and graded by
  `evaluator.evaluate` unchanged. No readable page is
  `BaselineError` (exit 2), never a zero; a dry run records the
  retrieval half only; the report states the reading comparison as
  it came out, either way. Never type a baseline into a scorecard,
  and never quote the example's judged figures as measurements: its
  store is fictional, it carries no baseline, and its scorecard says
  what its figures are.
- **A live check is asked or absent** (EVALUATION §3): `x_geo.live`
  reaches a scorecard only through `write_scorecard`, from an
  `engines.probe` of the same run (`evaluate --probe`): each question
  in one shopper's message with no system prompt, the provider's web
  search on, graded by the run's judge against the concepts the
  bundle retrieves for it. An assistant that cannot be reached, or a
  bundle with no `x_geo.site`, is `ProbeError` (exit 2), never a row
  of zeros; a failed or declined ask is counted apart; an answer the
  bundle cannot check counts neither for nor against; a dry run and a
  subscription CLI are refused. The assistant's answer was written
  from pages anyone can publish: the judge receives it in one
  `<answer>` block with `<answer` and `<concept` delimiters
  neutralized (`engines._inert_answer`), after the verified concepts,
  never before. The report states it only from the
  record (`report.live_sentences`), and the scorecard's live table
  never carries an `answered` header, which is how the report finds
  the bundle's own verdicts. Tests patch `cli._engine` to stand in
  for the assistant; no test and no CI run asks a live one.
- **A question set measures the store it was written from** (EVALUATION
  §1, profile 1.13): generation grounds every question in the outline,
  is told which archetypes the bundle's types support
  (`evaluator.ARCHETYPE_EVIDENCE`) and which the root index declares
  not applicable (`x_geo.not_applicable`), marks deliberate negative
  probes, and refuses an outline that describes no store; `okf-web
  questions` refuses a generated set whose ungrounded questions
  outnumber its grounded ones (`check_grounding`; `--allow-ungrounded`
  is the only opt-out); every set the toolchain writes carries its
  provenance (`meta`, written by `dump_questions`/`stamp_pack`) and the
  report states it; a declared archetype is set aside, recorded under
  `metrics.not_applicable`, never counted as a gap (lint W044 checks
  the declaration). The generation prompt carries no vertical examples
  a model could echo (a static test refuses them).
- Deterministic hashing only (`zlib.crc32`, `hashlib`), never builtin
  `hash()` — PYTHONHASHSEED salts it per process. Any change that alters
  rankings or cached vectors must bump the embedder model id so caches
  self-invalidate. Working-state caches (`.embeddings.json`,
  `.concepts-cache.json`) are JSON, **never pickle** — a cloned bundle
  must not execute code — and always hidden dotfiles so the publisher
  skips them.
- Profile changes are additive; consumers tolerate unknown keys. Every bump
  gets a version-history row in docs/GEO-PROFILE.md §10.
- Entity references (`fits`/`works_with`/`covers`/`passport_for`) must resolve
  to some concept's `entity` (W032). l10n content is excluded from retrieval
  and entity indexing **by key** (`split_l10n(rel)`), not by content.
  The view's language — the root index's `x_geo.language` (1.12) or the
  `l10n/<lang>/` tag — chooses the stop-word list, the language generated
  questions are written in, and the derived tier's tags; an undeclared
  bundle keeps the English defaults, so rankings never move on their own.
- **Spec fidelity is audited, not assumed**: docs/FIDELITY.md is the standing
  comparison against the published OKF spec (audited reference commit in
  MEMORY). Staleness is `>=` (SPEC §5.5), attesters are code artifacts rather
  than endpoints (W036), credibility signals are validated when present
  (W035), and base-spec deviations stay declared (GEO-PROFILE §7,
  `lint --strict-okf`). Re-run the FIDELITY §2 audit when the spec revs.

## Playbooks

### Profile bump (X → Y)

1. `grep -rl 'ecommerce-geo/X'` and update every carrier: `okf_web.__init__.
   PROFILE`, bundle-example frontmatter, docs, tests. Add the GEO-PROFILE §10
   history row by hand (sed will not write it).
2. The bump changes concept content hashes, so the pinned translation goes
   stale: set `l10n_source_hash` in `bundle-example/l10n/es/faq/general.md` to
   `concept_content_hash(load_bundle("bundle-example").concepts["faq/general.md"])`,
   or W031 fires (correctly).
3. Run the verification loop; lint must return to 0/0.

### New concept type (the EXPANSION A–E pattern; imitate any of those commits)

model accessors (+ `_HIGH_RISK_TYPES` if always risk-`a`) → a
`linter.TYPE_CONTRACTS` row (the type's E-code, its required fields and
its risk floor; W032/W033 follow from the row — never a new block in
`lint_concept`) → both prompt contracts (`prompts/surveyor_extract.md`,
`prompts/evaluator_questions.md`, incl. directory convention) → evaluator
archetype (append at the end of `ARCHETYPES`) → example concept(s) + 3 new
questions in `evaluations/questions.yaml` → +3 questions in **all 10 packs**
(en + es; full-archetype coverage is asserted) → docs (GEO-PROFILE type/x_geo/
lint tables + §10, DESIGN, EVALUATION, USER-GUIDE) → tests: bump the
question-count asserts (test_evaluator_and_surveyor, test_promotions_and_
retrieval, test_mcp_bridge, test_phase2_ops, test_phase4) and the
`len(ARCHETYPES)` asserts (test_fit_compatibility, test_ownership,
test_passport, test_locations) → re-measure the scorecard → verification loop.

## Gotchas

- `cli.cmd_publish` auto-resolves `--site` from the index's `x_geo.site`; the
  library `publisher.publish()` does not — pass `site=` explicitly.
- The commands are thin (U5): `init.run_init` is the one first-run
  pipeline (`cmd_init` validates arguments and prints what it says),
  `review.queue_summary` the one queue summary, `SurveyResult.extend` the
  one merge; the viewer renders from a `_ViewModel` one section at a
  time, `publish` is four stages, and `build_parser` is one
  `_add_<command>_parser` per verb. Tests patch `cli._llm` to inject a
  client into a command — that name is the CLI's test seam and stays.
- Linter tests pin `TODAY = 2026-08-05`; example freshness/promotion dates are
  chosen against that date. Do not "fix" dates casually. A rolling canary
  (`test_example_bundle_stays_fresh_for_sixty_days`) also lints the example at
  `today + 60d`: when it fails, shift the example's freshness stamps forward
  deliberately (re-pin the es translation's `l10n_source_hash`, re-check the
  date-pinned tests) — never weaken the linter or the canary.
- `bundle-example/policies/warranty.md` must remain a pending risk-`a` draft —
  review-queue tests assert `pending: 1 (a: 1, b: 0, c: 0)`.
- Exit codes are contractual (EDGE-CASES E4): `drift` 0 clean / 1 changed /
  3 unreachable only; `evaluate --min-hit-rate` exits 1 below the threshold
  and 2 for an invalid pack; `publish --fail-on-warnings` exits 1; refusals
  (`UnsafeDist`, a missing input file, a dry run over a judged scorecard, a
  risk-`a` batch approval, a mistyped concept path) exit 2 with one line on
  stderr, mapped in `cli.main`. CI gates the example on
  `evaluate --dry-run --min-hit-rate 1.0`.
- The version lives in two places: `pyproject.toml` and
  `okf_web.__init__.__version__`; the release workflow refuses a tag that
  disagrees with either, and a test asserts the two agree.
- CI is two jobs: `tests` (the suite on 3.10 to 3.13) and
  `test-and-lint` (needs `tests`; strict lint, dry-run gate, publish
  smoke, and the wheel built and installed into a fresh venv that lints
  the example and counts the packs — the package data proven from the
  wheel, U6). The release workflow runs the suite first and refuses a
  tag that is not on `main`. The ruleset's required check is `test-and-lint`, so a matrix
  change never touches the rule — never rename that job. Pushes to
  `main` trigger no run (`branches-ignore`): the check is earned on the
  branch and the fast-forward carries it. Both workflows carry a
  top-level `permissions: contents: read` and pin every action to a
  commit SHA with the version in a comment (GAPS item 8; a test refuses
  a floating tag) — bump a pin deliberately, never back to a tag.
- Signature error messages are contractual: a missing primary signature says
  "unsigned"; a missing countersignature says "countersignature" (tests match
  those substrings).
- `net._PinnedHTTPSConnection` lists the pinned base **before**
  `HTTPSConnection` and forwards through `super()`; the other order made
  every live `https://` fetch fail from E2 to 2026-09-23 while 42 tests
  passed, because no test ever opened a TLS socket and the callers report
  a failed page as unreachable. `tests/test_net_tls.py` keeps a loopback
  TLS round trip in the suite: a boundary that speaks TLS is verified over
  TLS, never only over plain HTTP.
- `signing.sign_file` is the one door that runs sigstore to sign (a
  static test refuses a second spelling of the sign command). At a
  terminal the child shares it, its standard output sent to standard
  error, and without an X or Wayland display `SIGSTORE_OAUTH_FORCE_OOB`
  makes sigstore print its login link and read the code back; with no
  terminal its output is captured and its input closed. Until
  2026-11-05 every sign captured the output, so on a machine without a
  browser the link and the prompt never showed and signing timed out
  after ten minutes while every test passed: no test ever signed at a
  terminal. `tests/test_signing.py` drives `okf-web sign` through a
  pseudo-terminal: a boundary that is a terminal is verified over one.
- PyPI registration and pushing a release tag are **user-only** actions. Never
  trigger a release. The release path — TestPyPI rehearsal proving the wheel's
  packaged data, then the real tag — is docs/DISTRIBUTION.md §6.
- `docs/HOSTING.md` is a tested document: `tests/test_hosting.py` serves
  a published dist over real HTTP with exactly its §0 header rules, checks
  every recipe's fenced block for them, and requires DESIGN §8's nginx
  block to equal HOSTING §2.1's. Change the serving rules in all three
  places together; when a recipe changes, re-run the live checks it
  records in §8 (Caddy, wrangler, netlify-cli; tooling notes in MEMORY).
- A survey under a limit reads `surveyor.rank_pages(listed)`, never
  the first pages a sitemap lists, and a generated question set is
  read through `evaluator._question_payload`, which falls back to
  reading the reply line by line when it is not YAML. The first real
  capped survey (2026-11-11: a 218-page dealer's site, six pages) read
  the home page twice, an HTML site map and a links page, then lost
  its whole question set to one single-quoted sentence holding an
  apostrophe, and reported that the model had produced nothing. A
  limit is applied to the ranked list; a reply is called empty only
  after both readings.
- A stand-in that yields one of a thing proves nothing about two.
  From 2026-08-12 to 2026-11-12 the write gate sent every draft of a
  URL to the first concept that URL owned, so each surveyed page kept
  only the last concept it yielded, under the first one's path, while
  every test passed: no test page had yielded more than one concept.
  The first real surveys did (six pages, nineteen drafts written, six
  concepts left). `tests/test_page_concepts.py` surveys pages that
  yield several; a stand-in for a model emits what a model emits.
- Keep `.claude/MEMORY.md` truthful: any commit that changes something it
  records (profile, counts, metrics, histories, rhythm) updates it in the same
  commit — and edit it only from a fresh Read of the exact region: recalled
  wording drifts, and exact-match edits then miss (this has bitten
  repeatedly).

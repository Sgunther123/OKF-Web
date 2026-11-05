# The library surface — what stays put

`okf-web` is a CLI first, but the hosted edition and other integrators
import it as a library. This page names the surface that is **stable
within the 0.x line**: a name listed here keeps its module, its name
and the meaning of its arguments until a note in EDGE-CASES §7 says
otherwise. Everything else — a name that begins with an underscore,
and any public name a module does not list in its `__all__` or here —
is an implementation detail that may move without notice.

`tests/test_api_surface.py` imports every name in these tables and
checks every module's `__all__`, so the page cannot drift from the
code. Review 2026-10-21, phase U4.

## The rules behind the surface

- **One error family.** Every error the toolchain raises on purpose
  inherits `okf_web.errors.OkfWebError` and one of two verdicts:
  `Refusal` (the command refused to act: exit 2) or `Failure` (it
  acted and the outcome failed: exit 1). `errors.exit_code(exc)` is
  the one exit table; `okf-web`'s `main` has one `except`. The stdlib
  bases stay, so a `BundleNotFound` is still a `FileNotFoundError`.
- **One home per primitive.** The spec's timestamp form is
  `model.utc_instant`; the slug rule is `model.slug`; a file's digest
  is `model.file_digest`; a URL's origin is `net.origin`; a fetch
  policy is derived with `FetchPolicy.derive`; the store's declared
  site is `Bundle.site`. A static test refuses a second spelling.
- **One configuration.** `config.WELL_KNOWN_PATH`, `config.DEFAULT_MODEL`
  and `config.user_agent(component)` are read everywhere they apply;
  no module carries its own copy of a version number.

## The tables

### `okf_web`

| Name | Kind | Meaning |
| --- | --- | --- |
| `__version__` | str | the package version (also in `pyproject.toml`; a test keeps them equal) |
| `OKF_VERSION` | str | the OKF spec version the toolchain writes (`0.2`) |
| `PROFILE` | str | the GEO profile identifier (`ecommerce-geo/1.12`) |

### `okf_web.config`

| Name | Kind | Meaning |
| --- | --- | --- |
| `WELL_KNOWN_PATH` | str | `/.well-known/okf`, where a bundle lives under its site |
| `DEFAULT_MODEL` | str | the model the CLI asks for when none is named |
| `REPOSITORY_URL` | str | named in every user agent |
| `user_agent` | function | `user_agent(component="")` → `okf-web-<component>/<version> (+repository)` |

### `okf_web.errors`

| Name | Kind | Meaning |
| --- | --- | --- |
| `OkfWebError` | class | base of every error raised on purpose |
| `Refusal` | class | the command refused to act (exit 2) |
| `Failure` | class | the command acted and the outcome failed (exit 1) |
| `EXIT_REFUSAL` | int | 2 |
| `EXIT_FAILURE` | int | 1 |
| `exit_code` | function | the exit code for an `OkfWebError` |

### `okf_web.model`

| Name | Kind | Meaning |
| --- | --- | --- |
| `Bundle` | class | a loaded bundle: `concepts`, `indexes`, `logs`, `language`, `site`; `lexical_index` is the retriever's per-instance slot |
| `Concept` | class | one document: frontmatter, body, accessors (`is_stale`, `is_high_risk`, `verified_entries`, …) |
| `load_bundle` | function | read a bundle directory (`BundleNotFound` when missing) |
| `parse_document` | function | frontmatter + body from text |
| `render_document` | function | text from frontmatter + body |
| `write_atomic` | function | temporary sibling + `os.replace`, text or bytes |
| `file_digest` | function | `(sha256 hex, size)` of a file, chunked |
| `concept_content_hash` | function | the content hash a translation pins (`l10n_source_hash`) |
| `sha256_text` | function | `sha256:` digest of a text |
| `slug` | function | the one slug rule (callers strip and truncate) |
| `as_date` | function | a value as a calendar date, or None |
| `as_instant` | function | a value as a tz-aware instant, or None |
| `utc_now` | function | the clock every default uses |
| `utc_today` | function | its date |
| `utc_instant` | function | now (or a moment) as the spec's timestamp form |
| `default_stale_after` | function | the type's freshness SLA from now |
| `FRESHNESS_SLA_DAYS` | dict | the SLA per content class |
| `bundle_lock` | context manager | hold `<bundle>/.okf-lock` |
| `BundleLocked` | class | the lock is held (refusal) |
| `BundleNotFound` | class | no such bundle (refusal) |
| `FrontmatterError` | class | unparseable frontmatter (refusal) |
| `split_l10n` | function | `(lang, rel)` for an `l10n/` path, else None |
| `localized_view` | function | the bundle a language's shopper reads |
| `language_tag` | function | a normalized BCP-47 tag, or `""` |
| `language_primary` | function | the primary subtag |
| `trust_mix` | function | the trust-tier counts of a bundle |
| `marked_dists` | function | the `.okf-dist` directories under a root |
| `is_linked` | function | a path that is, or sits under, a symlink |
| `TRUST_UNVERIFIED` | str | trust tier |
| `TRUST_MACHINE` | str | trust tier |
| `TRUST_HUMAN_BATCH` | str | trust tier |
| `TRUST_HUMAN` | str | trust tier |
| `RISK_HIGH` | str | risk tier `a` |
| `RISK_MEDIUM` | str | risk tier `b` |
| `RISK_LOW` | str | risk tier `c` |
| `DIST_MARKER` | str | `.okf-dist` |
| `INTERNAL_DIRS` | tuple | directories a bundle keeps to itself |

### `okf_web.net`

| Name | Kind | Meaning |
| --- | --- | --- |
| `FetchPolicy` | class | caps, timeouts, host rules, user agent; `derive(**changes)` |
| `FetchResult` | class | status, headers, body, text |
| `safe_fetch` | function | the one door for every outbound request |
| `fetch_text` | function | a page's text through the door |
| `check_url` | function | the policy's verdict on a URL before fetching |
| `is_private_host` | function | a host the door refuses by default |
| `origin` | function | a URL's origin, the way browsers compare them |
| `FetchError` | class | a fetch that did not complete (refusal) |
| `UnsafeURL` | class | a URL the door will not touch |
| `FetchTimeout` | class | the deadline passed |
| `FetchTooLarge` | class | the cap was reached |
| `TooManyRedirects` | class | more hops than the policy allows |
| `PAGE_POLICY` | FetchPolicy | pages |
| `ROBOTS_POLICY` | FetchPolicy | robots.txt |
| `CAPABILITY_POLICY` | FetchPolicy | capability endpoints |
| `DEFAULT_USER_AGENT` | str | `config.user_agent()` |

### `okf_web.llm`

| Name | Kind | Meaning |
| --- | --- | --- |
| `LLMClient` | protocol | `complete(system, user, max_tokens)` and a `model` |
| `AnthropicClient` | class | the API client |
| `SubscriptionCLIClient` | class | a local agent CLI under the subscription |
| `StaticClient` | class | canned answers, for tests |
| `claude_code_client` | function | the subscription client, probed and refused when unfit |
| `client_from_args` | function | the client the parsed CLI arguments ask for (`model=` overrides) |
| `add_llm_args` | function | `--model` and `--llm` on a parser |
| `probe_cli_help` | function | the agent CLI's `--help`, or None for a missing binary |
| `estimate_tokens` | function | the token estimate the budget uses |
| `LLMUnavailable` | class | no usable client (refusal) |
| `DEFAULT_MODEL` | str | `config.DEFAULT_MODEL` |

### `okf_web.packs`

| Name | Kind | Meaning |
| --- | --- | --- |
| `available` | function | the shipped starter packs: name → YAML text |

### `okf_web.surveyor`

| Name | Kind | Meaning |
| --- | --- | --- |
| `survey` | function | pages → drafts through the write gate |
| `survey_page` | function | one page |
| `place_draft` | function | the single write gate for concept files |
| `rebuild_index` | function | the root index from what is stable |
| `discover_sitemap` | function | a site's sitemap URLs |
| `fetch` | function | a page under the page policy |
| `html_to_text` | function | the text a page carries |
| `stable_page_hash` | function | the hash drift compares |
| `page_policy` | function | the page policy with a timeout and host opt-in |
| `SurveyResult` | class | written, proposed, skipped, quarantined, errors; `extend` folds another result in |
| `SitemapError` | class | an unusable sitemap (refusal) |
| `PRODUCER_DENIED_DIRS` | tuple | where a producer may never write |
| `USER_AGENT` | str | `config.user_agent("surveyor")` |

### `okf_web.feed`

| Name | Kind | Meaning |
| --- | --- | --- |
| `ingest_feed` | function | a product feed → drafts through the write gate |
| `parse_feed` | function | CSV or XML rows |
| `FeedError` | class | an unusable feed (refusal) |
| `FEED_ACTOR` | str | the provenance actor feed drafts carry |
| `DROPPED_FIELDS` | tuple | the live values a feed never turns into claims |

### `okf_web.linter`

| Name | Kind | Meaning |
| --- | --- | --- |
| `lint_bundle` | function | `(bundle, findings)` for a directory |
| `lint_concept` | function | the findings for one concept |
| `has_errors` | function | whether findings carry an error |
| `TypeContract` | class | what a type must carry to go stable and its risk floor |
| `TYPE_CONTRACTS` | dict | the contract types, one row each (a new contract type is a row) |
| `Finding` | class | severity, code, path, message |
| `ERROR` | str | severity |
| `WARNING` | str | severity |

### `okf_web.review`

| Name | Kind | Meaning |
| --- | --- | --- |
| `pending` | function | the review queue |
| `approve` | function | a named person's per-item approval |
| `batch_candidates` | function | what a batch approval would take |
| `batch_approve` | function | the wholesale sign-off (`human-batch:`) |
| `reject` | function | keep as draft, with a reason |
| `approval_state` | function | why approving again would change nothing |
| `resolve_path` | function | a typed path to a concept, or `ReviewError` with a suggestion |
| `ReviewItem` | class | a queued concept and its reasons |
| `ReviewError` | class | a review the tool refuses (refusal) |
| `queue_summary` | function | the pending items, the drift proposals and the counts by risk |
| `QueueSummary` | class | that summary, with the `line` CI reads |

### `okf_web.evaluator`

| Name | Kind | Meaning |
| --- | --- | --- |
| `evaluate` | function | questions against a bundle: dry run or judged |
| `load_questions` | function | a question set from YAML |
| `validate_questions` | function | what makes a set unfit to gate on |
| `generate_questions` | function | a set derived from the bundle by an LLM |
| `write_scorecard` | function | the GEO Scorecard into the bundle |
| `render_context` | function | the retrieved concepts as the context block |
| `retrieve` | function | the lexical retriever |
| `Question` | class | id, archetype, question, paraphrase |
| `QuestionResult` | class | one question's retrieval and verdict |
| `Report` | class | the evaluation's results and metrics |
| `ARCHETYPES` | tuple | the question archetypes |
| `META_TYPES` | frozenset | types retrieval never returns |
| `SCORECARD_PATH` | str | `evaluations/geo-scorecard.md` |
| `QuestionSetError` | class | an unfit question set (refusal) |
| `ScorecardGuard` | class | a dry run would replace a judged scorecard (refusal) |

### `okf_web.views`

| Name | Kind | Meaning |
| --- | --- | --- |
| `select_publishable` | function | `(publishable, withheld)` under a freshness rule |
| `withhold_reason` | function | why a concept is held back, in the operator's words |
| `published_view` | function | the bundle as consumers see it |

### `okf_web.publisher`

| Name | Kind | Meaning |
| --- | --- | --- |
| `publish` | function | bundle → dist (manifest, structured tier, markers) |
| `check_dist` | function | the dist guard |
| `evaluate_robots` | function | which AI agents a robots.txt blocks |
| `check_robots` | function | the live robots check |
| `PublishResult` | class | published, withheld, warnings, structured, assets |
| `PublishError` | class | a publish that could not complete (failure) |
| `UnsafeDist` | class | a destination the guard refuses (refusal) |

### `okf_web.agents`

| Name | Kind | Meaning |
| --- | --- | --- |
| `AI_USER_AGENTS` | list | the crawlers and agents a bundle exists to serve |

### `okf_web.structured`

| Name | Kind | Meaning |
| --- | --- | --- |
| `write_structured` | function | the JSON-LD tier into a dist |
| `write_llms_txt` | function | llms.txt into a dist |
| `jsonld_for` | function | the JSON-LD object for one concept |
| `dumps_script_safe` | function | JSON that is inert inside a `<script>` |
| `LLMS_SECTIONS` | tuple | llms.txt's sections and the types each lists |

### `okf_web.signing`

| Name | Kind | Meaning |
| --- | --- | --- |
| `sign_file` | function | sigstore-sign one file; the login reaches a terminal, or fails at once without one |
| `sign_manifest` | function | sign a dist's manifest (or countersign under a label) |
| `verify_signature` | function | verify against an identity and issuer |
| `verify_integrity` | function | every manifest hash against the files |
| `signature_path` | function | the signature's path for a label |
| `SigningError` | class | signing or verification did not succeed (failure) |
| `LabelError` | class | a label the tool will not accept (refusal) |
| `SIGNATURE_NAME` | str | `manifest.json.sigstore.json` |

### `okf_web.drift`

| Name | Kind | Meaning |
| --- | --- | --- |
| `check_bundle` | function | every surveyed source page against its hash |
| `DriftReport` | class | unchanged, drifted, unreachable, skipped, feed_derived |

### `okf_web.discover`

| Name | Kind | Meaning |
| --- | --- | --- |
| `discover` | function | find a store's bundle and judge its binding |
| `DiscoveryReport` | class | what was found and how it binds |

### `okf_web.remote`

| Name | Kind | Meaning |
| --- | --- | --- |
| `RemoteSource` | class | a mirrored remote bundle for the bridge |
| `check_mirror_dir` | function | the mirror guard |
| `cache_dir_for` | function | the mirror's directory for a base URL |
| `default_policy` | function | the mirror's fetch policy |
| `RemoteError` | class | a remote bundle that cannot be mirrored safely (refusal) |
| `META_NAME` | str | `.okf-remote.json` |

### `okf_web.mcp_bridge`

| Name | Kind | Meaning |
| --- | --- | --- |
| `build_state` | function | the bridge's state for a bundle or a URL |
| `handle_message` | function | one JSON-RPC message (or batch) → answer |
| `serve_stdio` | function | the stdio loop |
| `bundle_signature` | function | the change signature a republish keys on |
| `BridgeState` | class | the bridge's state |
| `BundleSource` | protocol | where a bridge's bundle comes from: `signature()` and `load()` |
| `TOOLS` | list | the tools the bridge advertises |

### `okf_web.report`

| Name | Kind | Meaning |
| --- | --- | --- |
| `build_report` | function | the merchant report from the recorded scorecard |
| `write_report` | function | the report into the bundle |
| `scorecard_gaps` | function | the gap ids a scorecard records |
| `judged_verdicts` | function | the per-question verdicts a scorecard records |
| `question_blocks` | function | the detail tier's question blocks |
| `count_cell` | function | a recorded count as a whole number, or None |
| `ARCHETYPE_LABELS` | dict | the archetypes' display labels |
| `ReportError` | class | a report the tool refuses (refusal) |

### `okf_web.viewer`

| Name | Kind | Meaning |
| --- | --- | --- |
| `build_viewer` | function | the viewer page from measured facts |
| `write_viewer` | function | the page outside the bundle |
| `ViewerError` | class | a viewer the tool refuses (refusal) |

### `okf_web.logscan`

| Name | Kind | Meaning |
| --- | --- | --- |
| `scan_lines` | function | access-log lines → who fetched the bundle |
| `match_agent` | function | the AI agent a user-agent string declares |
| `LogScanReport` | class | the counts |
| `MAX_LINE_LENGTH` | int | lines longer than this are skipped |

### `okf_web.init`

| Name | Kind | What it is |
| --- | --- | --- |
| `run_init` | function | the guided first run as a library: feed → lint → attest → questions → scorecard → publish → report |
| `InitResult` | class | every step's outcome, the lines the command prints, `exit_code` |

### `okf_web.cli`

| Name | Kind | Meaning |
| --- | --- | --- |
| `main` | function | the entry point: one `except` maps every `OkfWebError` to its exit code |
| `build_parser` | function | the argument parser |

## Names kept for the hosted edition

`cli._add_llm_args`, `cli._llm` and `cli._question_packs` are aliases of
`llm.add_llm_args`, `llm.client_from_args` and `packs.available`;
`model._as_date`, `model._as_instant` and `model._linked` of their
public names; `report._count`, `_gaps`, `_judged_verdicts` and
`_question_blocks`, and `structured._LLMS_SECTIONS`, of theirs. They
exist so a pick into the hosted edition lands before its adapter
module does, and go when it has.

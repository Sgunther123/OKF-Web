# Project memory — state snapshot

Companion to `/CLAUDE.md` (durable rules live there; this file is the mutable
state). **Any commit that changes something recorded here updates this file in
the same commit.**

Last updated: 2026-11-12 — **the live check asks for direct
searches** (on the maintainer's first runs against a real store,
that day). Five questions about a dealer's site, the tool left at
its default: searches_mean 2.8, answered 0.8, names_store 1.0,
checked 4, contradicted 0, and **cites_store 0.0**. One question
then asked both ways and each reply taken apart: by default the
searches ran inside the provider's code execution (ten
`server_tool_use` blocks: seven `code_execution`, three
`web_search` with a `caller`), 27 result pages (four on the store's
address), 59,538 tokens in, 2,248 out, and **no citation on any
text block**; asked with `allowed_callers: ["direct"]`, two
searches, 19 result pages (none on the store's address), 22,117
tokens in, 997 out, and four citations. So the zero was the shape
of the reply, not the assistant's choice. The reader's count of
searches equalled the service's own (`usage.server_tool_use.
web_search_requests`) both times: 3 and 2. `engines.AnthropicSearch`
now declares `allowed_callers` (`_SEARCH_CALLERS`, direct), reads
the pages the searches returned (`EngineAnswer.found`; None from an
assistant that does not say), and joins what was said before a
search and after it as two paragraphs (a cited sentence's pieces
still join as they stand). The record gains `finds_store` (the
share of replies whose searches returned a page on the store's
address; absent when no answer reported its results), the rows
`found`, the scorecard's live table a `store in results` column
when a record carries the figure, and `report.live_sentences` one
more sentence. Not changed: the shopper's wording (the generated
questions say "you" to the store, and the assistant opens by saying
it is not the store; seen, left). Two tests added in
`tests/test_engines.py` (26 there), three changed; 21 mutations,
all caught. Suite **630** without `build`, 631 with it. Positions:
`main` == `bfbb0b7` (fetched); the branch seven ahead (`9431f79`,
`4001250`, `2240087`, `c7d9b3d`, `9342408`, `a8ec7b2`, this commit;
run 10 green for `a8ec7b2`), which move to `main` on the user's
word.

Earlier on 2026-11-12, **a page keeps every concept it yields**
(`a8ec7b2`; found in the same real runs as the entry below). Both capped
surveys of the dealer's site ended with exactly one concept a page:
six pages, six concepts, nineteen drafts written the first time.
`surveyor.place_draft`'s path stability took "a URL that already has
a concept keeps its path" literally: the first concept a URL owned
received every later draft of that URL, the same page's second and
third blocks included, so a page kept only the last concept it
yielded, under the first one's path (reproduced: three blocks,
`written: ['store.md', 'store.md', 'store.md']`, one file, a Product
Collection in `store.md`). In the code since `13ff741` (2026-08-12);
unseen because every stand-in model in the tests emits one block a
page and the example bundle has one concept a URL. Now per concept:
a draft whose path its URL owns is written in place; a draft with a
new path takes over a concept of its own type that the URL owns and
no other draft of the page claims (a rename), or, where the producer
declared the page's paths, the URL's only concept (renamed and
retyped); anything else is a further concept, written where
proposed. `place_draft(..., claimed=None)`: one set a page, the
paths its drafts propose plus where each landed; `survey_page`
checks every block first, numbers a second block under one path
(`-2`, `-3`), declares the paths and hands the gate one loaded
bundle (one load a page, not one a block). A page is unchanged when
any concept it owns carries the text's hash (`_existing_by_resource`
is gone). Not changed: `linkmap.json` maps a URL to one path (the
last in path order when a page has several), and a concept a page
stops yielding stays as it was. `tests/test_page_concepts.py` (12)
and 12 mutations, all caught. Suite **628** without `build`, 629
with it.

On 2026-11-11, **a capped survey of a real store** (`9342408`; on
the first real runs of that day's work, made by the maintainer). Two
findings, both fixed here. (1) A survey under a limit read the first
pages the sitemap listed: on a 218-page dealer's site with a limit of
six, the home page twice (`/` and `/index.shtml`), the about page, an
HTML site map, the contact page and a links page; no product, no
policy. `surveyor.rank_pages(urls)` now orders a sitemap's pages for
a capped survey (the home page once; then policy and help pages,
catalog pages and the contact and about pages in turn, section pages
before the pages under them, contact before about; then blogs and
picture pages; last, site maps, carts, second home spellings and
addresses that are not pages), judging an address by its words alone;
`okf-web survey --sitemap --limit` uses it, a survey with no limit
reads what it always read, and a hand-written `--urls` list keeps its
order. (2) The question set generated from those six pages was lost:
the model's reply was not valid YAML (the store's name holds an
apostrophe; the suspected line is a single-quoted sentence holding
it), `_extract_yaml` returned nothing and the run reported that the
model had produced no set. `evaluator._question_payload` now reads
such a reply line by line (each `- key: value` starts a question,
the wrapping quotes are the model's), and `reason: not-a-store`
survives the same way. The raw reply was not kept, so the exact line
is inferred, not seen. **The live check's first real run** the same
day: `evaluate --probe` was accepted by the service (the default
model with `web_search_20260209`), the judge returned verdicts, the
record and the scorecard's section were written; the store asked
about sits on a reserved `.example` address, the assistant said so
and ran no search (the service's own count agrees: no
`server_tool_use` in `usage`), about 6,000 tokens in and 500 out for
one question before any search. A reply with searches and citations
is still unverified against the real service. `tests/
test_capped_survey.py` (37) and 20 mutations, all caught. Suite
**616** without `build`, 617 with it.

Earlier on 2026-11-11, **a live check is asked or absent**
(`c7d9b3d`; on the user's "Implement as recommended" of that day,
continuing the work below). `okf-web evaluate --probe` puts the bundle's questions
to a live assistant with web search on, worded as a shopper would
(one message naming the store and its host, no system prompt), and
the run's judge compares each answer with the concepts the bundle
retrieves for that question. New module `okf_web.engines` (`probe`,
`Probe`, `Engine`, `EngineAnswer`, `AnthropicSearch`, `store_of`,
`shopper_prompt`, `judge_prompt`, `ProbeError`; the one adapter is
Claude through the Messages API with the web search tool
`web_search_20260209`), new prompt `prompts/probe_judge.md` (five
packaged prompts now), `Report.live`/`live_rows`, `x_geo.live` on the
scorecard with a per-question table (header `substantive`, never
`answered`), `report.live_sentences`, the flags `--probe`,
`--probe-model`, `--probe-repeats`, `--probe-searches` and the test
seam `cli._engine`. The record: `answered` (the share of replies
that were a substantive answer about this store), `checked` and
`contradicted` (against the store's verified knowledge; an answer it
cannot check counts neither way), `names_store` and `cites_store`
(read without a model). Refusals (exit 2): no `x_geo.site`, an
assistant that cannot be reached (three failures from the first
ask), `--dry-run`, a subscription CLI. The assistant's answer reaches
the judge inert, in one `<answer>` block after the verified
concepts. No profile bump: a scorecard-only key written by the
evaluator, like `x_geo.evaluated` (GEO-PROFILE §10 says so).
No test and no CI run asks a live assistant, and this container
holds no API key: at this commit the adapter was verified against a
scripted client only (its first real run is the entry above).
`tests/test_engines.py` (24) and 37 mutations, all caught. Suite then
**579** without `build`, 580 with it. Positions then: `main` ==
`bfbb0b7` (fetched); the branch four ahead (`9431f79`, `4001250`,
`2240087`, `c7d9b3d`).

Earlier on 2026-11-11, **the guide's own typed comparison**
(`2240087`; on the same request). USER-GUIDE's answer to "Why can't AI assistants just
read my website?" still said that answering from the fact folder
"used about 22 times less AI reading effort ... measured on the
example store": the last quotation of a comparison nothing had
measured, missed by `9431f79` because the sweep searched for the
figures it knew (17, 0.615, 41,780) and this one was a different
number in words. The answer now says how a store's own figure is
measured (`--baseline`), and `test_baseline.py` gains a static test
(16 now) that refuses a stated multiple ("N times less", "N×
cheaper") in README and the documents. Suite then **554** without
`build`, 555 with it. Positions then: `main` == `bfbb0b7` (fetched);
the branch three ahead (`9431f79`, `4001250`, `2240087`).

On 2026-11-10, **a comparison is measured or absent** (`9431f79`; on
the user's request to make the proof real, after an audit of the
reference numbers the same day). The audit: across the seven versions
of the example scorecard (`57c59af` to `6c43803`) its raw-page
comparison read 41,780 tokens every time while its page count rose
from 12 to 18, its judged coverage was always all but two questions
(19 of 21 to 37 of 39), and its `generated.at` stamps postdate the
commits that carry them. No command ever computed the comparison and
the store is fictional: the judged figures and the comparison were
written with the example and extended by hand, and only the dry
run's figures were ever measured. Both were being quoted as
measurements (DESIGN, EVALUATION, the example's report). Put right
here: `okf_web.baseline` and `evaluate --baseline` (`--baseline-urls
FILE`, `--baseline-limit N`, `--allow-private-hosts`) put the same
questions to the store's own pages: the pages the bundle's concepts
cite as `resource`, those behind the bundle's own retrieved concepts
first, 50 by default, fetched through the page policy and read as
text (`html_to_text`, cut at 40,000 characters a page), with
`evaluator.evaluate` run unchanged over a view whose concepts are the
pages (`pages_view`: the same retriever arithmetic, `top_k`, answer
prompt and judge; the bundle's indexes carried, so its language and
`not_applicable` hold on both sides). `Baseline.attach` puts the
record on the report and `write_scorecard` stores it under
`x_geo.baseline`, the pages read listed in the body as inert code
spans; a dry run records the retrieval half only; no readable page is
`BaselineError` (a refusal, exit 2), never a zero; the command
measures the pages before the bundle's own run, so a refusal costs no
call. The report shows a before and after only when one was measured
and states the reading comparison as it came out
(`report.reading_tile`: one decimal, "more" when the bundle reads
more). The example scorecard loses its comparison and opens by
saying its judged figures were written with the example and are not
the record of a run (its description says the same); DESIGN and
EVALUATION §3 describe the measurement instead of quoting the
figures; EXPANSION and READINESS carry dated corrections. Tests:
`test_baseline.py` (15: the pages and their order, the limit, named
pages, the dry check equal to the evaluator's own over the view, a
raised relevance floor holding for the pages too,
unreadable pages and both refusals, the cut, a judged run graded by
the evaluator's prompts with both identities recorded, language and
declarations carried, a scorecard with a comparison only when
measured and its inert lines, the example without one, the report's
before and after, the reading comparison either way, the command
over a real loopback HTTP server, the attached copy); the error
table gains `BaselineError`. Suite **553** without `build`, 554 with it
(this container's 3.11 has it now, its 3.10 venv does not) and in CI. Lint 0/0; dry-run unchanged (39 questions, 1.0, 2,406
tokens, 0.897). Open, the maintainer's choice: a real judged run of
the example (it needs a model), or its scorecard stays labeled as it
now is. That commit is `9431f79`. It recorded `main` one push behind
(`25b33c5`, "two ahead"): the positions section had been trusted
without a fetch. Corrected by the MEMORY-only commit after it:
`main` == `bfbb0b7` since 2026-11-06; the branch two ahead
(`9431f79` and that correction), which move to `main` on the user's
word.

On 2026-11-06, **a question set measures the store it was
written from** (`bfbb0b7`; on the user's "Implement as recommended", after the
review of the audit rehearsal's report: a two-page site that is not
a store had been measured against 39 generated questions that were
the generation prompt's own examples, tents and jackets copied almost
word for word, and the report had called them realistic shopper
questions). Four guards, profile **1.13**: the prompt is
vertical-neutral, is told which archetypes the outline supports
(`ARCHETYPE_EVIDENCE`: a Trade Program for `procurement`, a Store
Location for `local_availability`, and so on) and which the root
index declares not applicable, writes at most one deliberate
`probe: negative` for an unsupported archetype, never reuses its own
wording, and answers `reason: not-a-store` for an outline with no
commerce in it (`NotAStore`, a refusal); `check_grounding` is the
deterministic check (a question is grounded when one informative
word of it occurs in the outline's titles, descriptions, entities and
tags; probes exempt, one per archetype) and `okf-web questions`
refuses to write a generated set whose ungrounded questions outnumber
its grounded ones (`UngroundedSet`; `--allow-ungrounded` writes it);
every set written carries `meta` provenance (`dump_questions`,
`stamp_pack`: source, generated by/at/from_concepts, grounding
counts, `curated_by`) and the report states it beside the headline;
`x_geo.not_applicable` on the root index sets declared archetypes
aside in generation, evaluation (`metrics.not_applicable`) and the
report (a row, never a gap), lint W044 checking the declaration. The
example's set gains its `meta` (generated 2026-08-04 by the recorded
generator from 19 concepts, curated by the merch lead) and
`probe: negative` on its out-of-catalog question; the profile bump
re-pins the translation hash. Tests: `test_question_fit.py` (15: the
prompt's rules and absent nouns, evidence and support, generation's
inputs and the dropped declared archetype, the not-a-store refusal
through the CLI, the rehearsal's echoed set refused then written on
the flag with its meta, the example set fit with its one probe, the
probe allowance, the declared archetype set aside through
evaluation, scorecard and report, W044 twice, pack stamping, the
example's provenance sentence, a set without meta, the dump/load
round trip, the probe validation); the error table gains two
classes. Suite **537** locally, 538 where `build` is installed. Lint
0/0; dry-run unchanged (nothing is declared in the example, so its
numbers do not move). Docs: EVALUATION §1 ("Fit"), GEO-PROFILE (§2
key, §9 W044, §10 1.13), USER-GUIDE Step 5 and two troubleshooting
entries, API.md, DESIGN, CLAUDE.md invariant. The hosted edition's
intake classification and holds build on this after the pick.

On 2026-11-06, **public** (`25b33c5`, MEMORY-only; on
the user's "Implement Phase 5 of the publication plan"). The user
made the repository public (verified at 21:27 UTC), the last act of the
publication plan kept in the hosted edition's repository; Phases 1
to 4 (the trimmed documents and the guard test, the hosted edition's
record, the history rewritten into this repository, the settings)
were done the same day. Before the flip every sweep printed nothing:
the tree, every blob of the history, every commit message, the secret
patterns. After it: the repository answers without credentials, the
site's link to it resolves, secret scanning and push protection are on (read back from the API after the user enabled them; GitHub had not turned them on by itself), and fork pull request workflows from all external contributors need approval (the user's screenshot). The open question of the
previous entry is answered: a new repository's workflows must be
enabled from its Actions tab, not only allowed in its settings; once
the user did that, their branch created from the UI ran (run 1) and
the session's push ran (run 2), both green, so no workaround is
needed. The ruleset "Branch Protection" was re-created by the user
after run 1 and verified (the four rules, an empty bypass list,
`main` only); `main` moved to `2814339` on the user's "Push the
commit directly to main" under it; the temporary `ci-start` branch
and its diagnostic run are deleted. Suite, lint and dry-run
unchanged. Positions then: `main` == `2814339`; the branch one ahead
with `25b33c5`, moved to `main` on the user's word the same day.

On 2026-11-06, **the repository founded twice, and its first CI run**
(`2814339`, MEMORY-only). The rewritten history was
pushed into a new `Sgunther123/OKF-Web` twice: the first instance,
created public at 18:14 UTC and set private within the hour,
produced no workflow run for any push from the session (the
founding push, a MEMORY-only commit, a temporary branch), so the
user deleted it and created the repository again, private, at 19:03
UTC; the founding push was repeated there at `3188302`, both
branches. The session's push produced no run there either; a branch
the user created from the GitHub UI at the same commit (`ci-start`)
did: run 1, green at 19:18 UTC, so the check the ruleset requires
exists on `3188302`, and the user re-creates the ruleset "Branch
Protection" (CONTRIBUTING.md). Why pushes from the session start no
workflow run in this repository, while the same pushes do in the
archive and in the hosted edition's repository, is not yet known;
this commit's push is the next test, and until it is answered a
check on a new branch head needs a branch created from the UI at
that commit. Suite, lint and dry-run unchanged. Positions then:
`main` == `3188302`; the branch one ahead with `2814339`, moved to
`main` on the user's word the same day under the re-created ruleset.

On 2026-11-06, **the history rewritten for publication** (`3188302`;
on the user's "Implement Phase 3 of the publication plan with option
C", a plan kept in the hosted edition's repository). This repository
is a new one under the old name. The previous `Sgunther123/OKF-Web`
was renamed to a private archive, and its history was copied here
with `git filter-repo`: `CLAUDE.md` and `.claude/MEMORY.md` dropped
from every commit, so no earlier version of the two continuity files
is reachable; the twenty commits that changed only those files gone
with them; the link to the hosted edition's private repository in
earlier versions of the README, USER-GUIDE, EXPANSION, ROADMAP and
`pyproject.toml` replaced by the website's, as Phase 1 did at the
tip; one commit message with one phrase neutralized; every other
commit keeping its tree and message under a new sha. This commit
re-adds the two files as Phase 1 left them, with every sha in this
file translated to this history (a sha marked "(archive)" names a
commit that exists only in the archive) and EDGE-CASES' one reference
likewise. The sweep over every blob reachable from any ref (path
aware: the example bundle, DESIGN's example price and the guard test's
own list allowed) and over every commit message prints nothing; the
plan's `git log -p` sweep agrees once the guard test's own pattern
lines are filtered. Suite **520** locally, 521 where `build` is
installed; lint 0/0; dry-run unchanged. Positions then: `main` ==
the branch == `3188302`, the first push into this repository. The
flip to public remains the user's own act, after Phase 4.

On 2026-11-06, **the repository made fit for publication** (`82e3cc6`;
on the user's "Implement Phase 1 of the publication plan", a plan
kept in the hosted edition's repository). Before this repository goes
public, what it carried about the hosted edition leaves: this file's
record of that edition's build-out and economics, its procedure
section, its open items and its pick notes; CLAUDE.md's git rules and
two-repositories section, rewritten for a public reader; the README's,
USER-GUIDE's and `pyproject.toml`'s links to that edition's private
repository, now one sentence linking its website; EXPANSION's hosted
rows and levers, ROADMAP's hosted feature list, GAPS' hosted findings
and READINESS's billing mention, gone; EDGE-CASES, DISTRIBUTION's
boundary line, two test docstrings and two artifact pointers,
neutralized. Nothing was copied anywhere:
the hosted edition's repository held every affected document already.
`tests/test_public_surface.py` (+1) scans every tracked text file for
the terms that would carry such material back in and fails on any hit
outside the example bundle and one example question in DESIGN;
`SECURITY.md` says where to report a vulnerability. Suite **520**
locally, 521 where `build` is installed. Lint 0/0; dry-run unchanged.
Positions then: `main` == `d473f65`; the branch three ahead (`aefcf78`,
`d0f6a5e`, `82e3cc6`), moved to `main` on the user's word the same
day (in the archive, where that commit is `ad81950`). The flip to
public is the user's own act, not part of that commit.

On 2026-11-06, **the signer and the store, named** (`d0f6a5e`; on
the user's "Fix the three audit email and report gaps", found by the
hosted edition's first rehearsed audit, delivered 2026-11-06). A
signature's consumers need the identity and issuer it was made under,
and nothing read them: `signing.signer(bundle)` walks the certificate a
sigstore bundle carries (a v0.3 leaf, or the first of an older chain)
with the standard library and returns its subject alternative name (an
email, or a workflow URI) and Fulcio's issuer extension (`.1.8`, else
the older `.1.1`); read, not verified, and None, never an exception,
for anything it cannot read. `okf-web sign` prints the complete verify
command from it, a placeholder only for a bundle that names nobody.
`report.build_report` names a store without a Store Identity concept
by the host of the site its index declares, before the folder the
bundle sits in (often `bundle`: every hosted store's is). Tests:
`test_signing.py` +4 (a real Fulcio leaf, public in Rekor, the
rehearsal's countersignature; a built certificate with a workflow URI
and the raw-bytes issuer; every unreadable shape and every truncation
of the real leaf; the printed command), `test_rendered_truth.py` +1;
suite **519** locally, 520 where `build` is installed. Lint 0/0;
dry-run unchanged. Docs: API.md, DESIGN §8, USER-GUIDE. Positions
then: `main` == `d473f65`; the branch two ahead (`aefcf78`, `d0f6a5e`).

On 2026-11-05, **signing without a browser** (`aefcf78`; on the
user's "Fix the headless signing upstream", found while planning the
hosted edition's first rehearsed audit on its server). `_run` started
`sigstore sign` with its output captured, so on a machine without a
display sigstore's out-of-band login (a link on standard error, then
"Enter verification code:") never reached the operator and signing
timed out after ten minutes; desktops (a browser opens) and CI (an
ambient identity) never showed it. `signing.sign_file` is now the one
place that runs sigstore to sign, `sign_manifest` built on it and the
name declared in API.md: with standard input at a terminal the child
shares it (its standard output sent to standard error, so a caller's
output stays clean); without an X or Wayland display
`SIGSTORE_OAUTH_FORCE_OOB=1` is set for it unless the operator chose a
value (sigstore 3.0 and later read it); with nobody at a terminal the
output is captured, standard input closed, and a login that needs a
person fails at once with a hint. Verification is unchanged. Tests:
`test_signing.py` +6, among them a pseudo-terminal round trip through
`okf-web sign` (the old code fails it at its 20-second prompt deadline)
and a static guard on a second spelling of the sign command; suite
**514** locally, 515 where `build` is installed. Lint 0/0; dry-run
unchanged. Docs: EDGE-CASES §8 (new, "Found in deployment"), DESIGN
§8, API.md, a CLAUDE.md gotcha. Positions then: `main` == `d473f65`
(the user's fast-forward of 2026-10-26 over U6 and U5, after run 116
was green); the branch one ahead (`aefcf78`).

On 2026-10-24, **U5, the decomposition: the review's
fifth upstream phase** (`d473f65`; on the user's "Implement Cycle 4"; after U6 so
it landed under the hardened suite). Behaviour-preserving by
measurement: the viewer page, the report, the example's lint findings,
the publish result and every subcommand's help text were snapshotted
first and each step compared byte for byte (only the manifest's
`published_at` clock differs). `init.run_init` is the one first-run
pipeline, returning an `InitResult` with every step, the printed lines
and an `exit_code`, with `emit`/`warn` sinks so `cmd_init` prints as it
goes; `SurveyResult.extend` and `review.queue_summary` replace the
hand-merged lists and the hand-counted queue (A-U3). `linter.TYPE_CONTRACTS`
is one table for the five contract types (E015–E019, their required
fields, their risk floors) read by `lint_concept`, with Attested
Computation and Promotion as two bespoke functions; the viewer computes
a `_ViewModel` and renders eight sections one function each; `publish`
is four stages; `build_parser` is sixteen `_add_<command>_parser`
builders (A-U4). The LLM parameters carry `LLMClient`, the bridge's
source is the `BundleSource` protocol, the retriever's snapshot is the
declared `Bundle.lexical_index` slot, and a localized view deep copies
what it overlays (A-U12). `cli._llm` stays as the tests' seam. Tests:
`test_decomposition.py` (16); suite **508** locally, 509 in CI. Lint
0/0; dry-run unchanged. Positions then: `main` == `7ca9852`; the branch
two ahead (`486c29d`, U6; `d473f65`), which moved to `main` on the
user's word (the fast-forward of 2026-10-26).

On 2026-10-23, **U6, test hardening, CI and docs: the
review's sixth upstream phase** (`486c29d`; on the user's "Implement Cycle 4";
taken before U5 so the decomposition lands under the hardened suite).
`tests/test_guards.py` (20): rankings and vectors identical across two
interpreters with different PYTHONHASHSEEDs (T-U3); the parse-cache
tautology fixed (T-U6); the mirror's refusals, its 304 path and its
service through a bad re-check — which found `signature()` catching
only `FetchError`, so a broken manifest or a refused write raised out
of the bridge; it now catches `RemoteError` and `OSError` too (T-U7);
the command paths never driven through `main` — `index`, `publish
--sign` and a failing signer, `--check-robots` against a loopback
robots.txt, the manifest's site from the index, `evaluate
--judge-model`, `mcp` over stdio for a bundle and for `--url`, `survey`
page errors (T-U8); a static scan for sockets outside `net.py`, clocks
outside `model.py` and the builtin `hash` — three clock sites moved to
`utc_now()`, no stamp changes (T-U9); `example_bundle` is a session
copy and a session fixture fails the run if the checked-in example
gains working state (T-U10); `html_to_text` recovers from an unclosed
script and a 2,000-row feed canary is marked `slow` (T-U12); the five
doc lines (A-U10); 3.13 in the matrix on evidence (the suite passes on
3.13.12 here), the wheel installed into a fresh venv in `test-and-lint`,
the release gated on the suite and on the tag being on `main` (A-U11).
Suite **492** locally, 493 in CI. Lint 0/0; dry-run unchanged.
Positions then: `main` == `7ca9852` (the user's fast-forward of 2026-10-23,
U1–U4); the branch one ahead (`486c29d`), which moves to `main` on
the user's word.

On 2026-10-23, **U4, errors, API and configuration: the
review's fourth upstream phase** (`7ca9852`; on the user's "Implement Cycle 3: U4").
One error family: every class the toolchain raises on purpose inherits
`errors.OkfWebError` and `Refusal` (exit 2) or `Failure` (exit 1),
`errors.exit_code` is the table and `cli.main` has one `except`; the
observable codes are unchanged (`signing.LabelError` keeps `verify`'s
label check at 2, a refused publish stays 2, `init`'s unmapped
`PublishError` now exits 1 with one line) (A-U1). The library surface
is declared: `docs/API.md` lists what stays put, every module carries
`__all__`, and `tests/test_api_surface.py` imports every name; the
hosted edition's private imports have public homes — `llm.add_llm_args`
/ `client_from_args`, `packs.available`, `net.origin`,
`model.file_digest`, `model.as_date`/`as_instant`/`is_linked`,
`report.scorecard_gaps`/`judged_verdicts`/`question_blocks`/
`count_cell`, `structured.LLMS_SECTIONS` — with the underscore aliases
kept until the hosted adapter (H4) lands (A-U2). One home per
primitive: `utc_instant` everywhere, `write_atomic` takes bytes,
`model.slug` is the one regex (callers keep their strip and truncation;
no path moves), `Bundle.site` the one read, `FetchPolicy.derive` the
one derivation, `review._verified_entries` and the mirror's own writer
and digest gone (A-U5). `config.py`: `WELL_KNOWN_PATH`, `DEFAULT_MODEL`,
`REPOSITORY_URL`, `user_agent(component)` carrying `__version__`, so no
request names a release that never shipped (A-U6). `views.py` holds the
publishable-set rules, `agents.py` the crawler roster, and the
publisher re-exports what moved (A-U7). The footnote and link regexes in
`model` and `structured` stay separate on purpose (they match different
shapes). Tests: `test_api_surface.py` (31, one per error class through
`main`); suite **472** locally, 473 in CI. Lint 0/0; dry-run unchanged.
Positions then: `main` == `9d98690`; the branch four ahead (`e2f1e51`, U1;
`fea7827`, U2; `75d2e23`, U3; `7ca9852`), which moved to `main` on the
user's word the same day (the fast-forward of 2026-10-23).

On 2026-10-23, **U3, operator-loop correctness: the review's
third upstream phase** (`75d2e23`; on the user's "Implement Cycle 2: U3 plus H1 and
H3"). `review approve --stale-after` on an already-approved concept
writes the date instead of printing "no change" (L-U2, the W041
remedy); `drift` leaves feed-derived concepts to the next ingest
(`DriftReport.feed_derived`, L-U3) instead of calling every one drifted
forever; `--include-machine-confirmed` ships low-risk drafts only and the
viewer names any other status (L-U4); generated question sets keep their
`paraphrase` and the CLI writes it (L-U6); `localized_view` matches the
`l10n/` tree with one normalized tag and a regional tag falls back to
its primary subtag's tree (L-U7); a Promotion is valid through
`ends_at` — the surveyor stamps `stale_after` at the following midnight
UTC, W027 accepts anything up to it, F5 states it, the example's
fall-clearance carries the new stamp (L-U8, the review's decision 5 as
recommended); a malformed `.embeddings.json` entry is a miss, never an
exception (L-U10); llms.txt lists `Buying Guide` and `Ownership Guide`
under "Guides and compatibility" (L-U11); `report` holds the bundle lock
(A-U9). Tests: `test_operator_loop.py` (10); suite **441** locally, 442
in CI. Lint 0/0; dry-run unchanged. Positions then: `main` == `9d98690`; the
branch three ahead (`e2f1e51`, U1; `fea7827`, U2; `75d2e23`), which
move to `main` on the user's word.

On 2026-10-23, **U2, refusals and robustness: the review's
second upstream phase** (`fea7827`; on the user's "Implement cycle 1 (U2 and H2)",
the cycle order suggested the same day). The remote mirror refuses the
home and working directories and any non-empty `--cache-dir` without its
own `.okf-remote.json`, prunes only what its previous manifest listed,
refuses writes outside itself and stops at 256 MiB (`remote.check_mirror_dir`);
`check_dist` keys the previous-publish exemption on the `.okf-dist`
marker, never on a `manifest.json`, and refuses the home and working
directories outright; the stdio bridge answers invalid requests with
`-32600`, batches with arrays, exceptions with `-32603`, and no line ends
it; a non-UTF-8 concept is a broken file E001 names, never a traceback,
and the CLI maps a stray `UnicodeDecodeError` to exit 2; the access-log
regex is linear; lint **E023** and the bridge refuse an executor
placeholder in the scheme or host; the agent CLI needs
`--strict-mcp-config` (required), takes `--restricted` when offered, and
is refused when its `--help` probe fails for any reason but a missing
binary; a dead lock is taken over by rename-then-inspect, once; behind a
proxy the target is still resolved and a private answer refused
(`net._vet_proxied_target`), the deadline covers every redirect hop and
a socket timeout is a `FetchTimeout`. Tests: `test_refusals.py` (11),
`test_net_proxy.py` (2, with a conftest fixture clearing every proxy
variable), `test_packaging.py` (the wheel ships prompts and packs;
`build` joins the dev extras, skipped without it), one CLI-client test;
suite **431** locally, 432 in CI; CI caches pip on `pyproject.toml`.
Lint 0/0; dry-run unchanged. Positions then: `main` == `9d98690`; the
branch two ahead (`e2f1e51`, U1, and `fea7827`), which move to `main` on
the user's word.

On 2026-10-23, **U1, rendered truth: the first phase of the
review of 2026-10-21** (`e2f1e51`; on the user's "Implement the plan starting with H0
and U1"; the review itself, six parallel reads with coverage measured
at 93%, produced the register EDGE-CASES §7 carries, one entry per
phase as it lands). This commit:
the report, the viewer and `okf_info` read the scorecard only at
`evaluations/geo-scorecard.md`, lint **E022** refuses a `GEO Scorecard`
elsewhere or in draft, counts render as whole numbers or escaped text,
a dry run records `found` and never `answered` and renders as not
judged everywhere, the footer states the evaluated view from the new
`x_geo.evaluated` record, judge verdicts parse strictly (booleans or
yes/true), `freshness` is measured over cited answers and omitted when
nothing was cited, and a localized view's scorecard goes to
`evaluations/geo-scorecard.<lang>.md`. Suite **417** (+7,
`tests/test_rendered_truth.py`); lint 0/0; dry-run unchanged (39 / 1.0 /
2,406 / 0.897); the recorded scorecard's freshness 1.0 holds under the
new definition by construction. Positions then: `main` == `9d98690`; the
branch one ahead (`e2f1e51`).

On 2026-10-04, **the derived tier speaks the language** (`9d98690`; the
second of the localization recommendations, same instruction): JSON-LD
`subjectOf` carries `inLanguage` (and `FAQPage` itself, a CreativeWork;
Product and Organization invent nothing), attested translations get
their own markup under `jsonld/l10n/<lang>/`, `llms.txt` names the
default language and lists each language's translations in its own
section, and `manifest.json` carries `language`, `languages` and each
translation file's `language`; an undeclared bundle without
translations publishes byte-identical output. The example now
publishes 33 files (the Spanish FAQ's JSON-LD); HOSTING §0 and the §7
transcripts updated from the run. A correction to the 2026-10-03
evaluation: the manifest's file list already carried the translation
with its freshness; what was missing was its language, its JSON-LD and
its llms.txt link. GEO-PROFILE §7/§10, DESIGN §8. Suite **410** (+2);
lint 0/0; dry-run unchanged. Positions then: `main` == `132927c`; the
branch two ahead (`7f43ca9` and `9d98690`), which moved to `main` on the
user's "Merge commits direct to main".

On 2026-10-04, **the bundle's language was declared; stop words
and generated questions follow it; profile 1.12** (`7f43ca9`; on the user's
"evaluate the need for localization considering a global deployment",
then "implement the recommendations"): `x_geo.language` on the root
index (a BCP-47 tag; lint W043 when malformed), `Bundle.language` and
the localized view's tag; the lexical retriever drops stop words per
language (lists for en, es, de, fr, pt, it and nl; a declared language
without a list drops none; an undeclared bundle keeps the English list,
so the reference numbers are unchanged); `generate_questions` names the
language in its prompt; the profile bump 1.11 → 1.12 across every
carrier, the es translation re-pinned, GEO-PROFILE §2/§7/§9/§10,
EVALUATION, USER-GUIDE and CLAUDE.md. Measured: the default dry run
unchanged (39 / 1.0 / 2,406 / 0.897); the Spanish outdoor pack on the
example's `--lang es` view reads a 0.59 hit rate where it read 0.974,
the difference being Spanish function words that matched the one
translated concept and counted as hits; the English view stays 0.231.
Suite **408** (+6, `tests/test_language.py`); lint 0/0. Positions then:
`main` == `132927c` (the user's fast-forward of 2026-10-02); the branch
one ahead (`7f43ca9`).

On 2026-10-02, **a machinery starter pack for equipment dealers** landed
(`132927c`; on the user's "consider updating the open-source edition with
the machinery 12-question set or similar", after the Machinio dealer
evaluation): `questionpacks/machinery.yaml` and `machinery.es.yaml`, 39
questions across all thirteen archetypes in a dealer's vocabulary (yard,
hours, serial, as-is, deposit, transport, export, fleet pricing),
registered in the pack tests, the CLI help, README, ROADMAP and the
CLAUDE.md playbook (now "all 10 packs"). Measured, retrieval-only: hit
rate 0.974 on the Machinio dealer skeleton (14 concepts; the outdoor pack
scores 0.744 there) and 0.615 on a feed-only bundle of 8 products, where
the outdoor pack scored 0.41; `init --pack machinery` from a dealer feed
completes all seven steps. Suite **402** (the pack tests iterate the
packs); lint 0/0; dry-run unchanged. Positions then: `main` == `53c0430`;
the branch one ahead (`132927c`), which moved to `main` on the user's
word on 2026-10-02 after run 108 was green.

On 2026-09-30, **hosting compatibility was re-confirmed, and
four fixes landed from the edge probes** (`53c0430`; on the user's "confirm the
compatibility with the typical web hosting providers and scenarios
while considering edge cases", then "implement the four fixes and fold
the notes into HOSTING.md"): the six hosting tests pass; Caddy v2.11.4,
wrangler 3.114.17 and netlify-cli 17.38.1, re-run live against a fresh
publish, reproduce HOSTING §8; GitHub Pages' headers re-probed. The
fixes: `safe_fetch` asks for `Accept-Encoding: identity` and decodes a
gzip or deflate answer under the byte cap (a pre-compressed manifest
read as "no bundle found"; brotli and a broken stream are `FetchError`,
a bomb `FetchTooLarge`, the header dropped from the result);
`publisher.check_robots` reads a 4xx `robots.txt` as allowed (RFC 9309)
and a 5xx as inconclusive; `discover` names what the well-known
location answered (`HTTP 403` with a bot-gate hint, `HTTP 402`, a 200
that is not JSON); `publisher._origin` drops default ports and user
information (IPv6 brackets kept; `www` and the apex stay distinct).
HOSTING gains the fourth thing to avoid (pre-compressed objects), §2.4
(a plain path on a host that hides dot-directories, the tag by hand),
the canonical-host and one-pointer notes in §4, the named statuses and
the robots reading in §7, and a §8 re-run record; EDGE-CASES "E2
landed" carries the extension, CLAUDE.md the sentence.
`tests/test_net_encoding.py` (+3) and two hosting tests (+2; suite
**402**); lint 0/0; dry-run unchanged. Positions then: `main` == `2b21298`;
the branch two ahead (`a6d257f`, `53c0430`), which moved to `main` on the
user's word on 2026-09-30.

On 2026-09-24, **`safe_fetch` learned POST** (`a6d257f`): `method`
(`GET` or `POST`) and `data`, through the same pinned opener, host
checks, caps and deadline; a platform app's OAuth code-for-token
exchanges are POSTs and now go through the one door instead of a raw
`urlopen`. `tests/test_net_post.py` (+2: a loopback echo, the
refusals; suite **397**); lint 0/0; dry-run
unchanged. EDGE-CASES "E2 landed" carries the extension, CLAUDE.md the
sentence. Positions then: `main` == `2b21298` (the user's "push the
commit directly to main" of 2026-09-23, the TLS fix); the branch one
ahead with `a6d257f`.

On 2026-09-23, **the TLS connection fix** (`2b21298`): since E2 no live
`https://` fetch through `net` could succeed — `_PinnedHTTPSConnection`
listed `HTTPSConnection` before the pinned base, so the stdlib's own
`super()` call landed on the pinned base without `policy` and raised
`TypeError` at construction (plain `http://` unaffected); the surveyor,
drift, discover and the robots check reported it as an unreachable page,
and no test had ever opened a TLS socket. Found in a deployment by its
first live `https://` read. The bases are now the right
way round, forwarding through `super()`; `tests/test_net_tls.py` (+3:
construction, an `https://` fetch reaching the pinned `connect`, a
loopback TLS round trip against an `openssl`-made certificate; suite
**395**); lint 0/0; dry-run unchanged. EDGE-CASES "E2 landed" carries the
correction, CLAUDE.md the gotcha. Pushed to `main` on the user's word
the same day.

On 2026-09-20, **GAPS phase E landed**, the last upstream
phase: item 8 — both workflows carry a top-level `permissions:
contents: read` (release's publish job alone keeps `id-token: write`)
and every action is pinned to a commit SHA with the version in a
trailing comment (checkout v4.4.0, setup-python v5.6.0,
upload-artifact v4.6.2, download-artifact v4.3.0, pypi-publish at its
release/v1 head of 2026-09-20; resolved with `git ls-remote`); a test
refuses floating tags and missing permissions blocks. Tests +2 (suite
**392**); lint 0/0; dry-run unchanged. Docs: CONTRIBUTING, CLAUDE.md
gotcha, GAPS §3. Items 1–8 and 10 are landed here; item 9 was never
this repository's.

Earlier the same day, **GAPS phase D landed**: item 3 (`model.FRESHNESS_SLA_DAYS` + `default_stale_after`
stamped in `surveyor.place_draft` when a producer left `stale_after`
empty — every producer passes through the gate; lint **W041** for a
stable SLA-type concept without a date; `review approve
--stale-after` dates a fresh concept too), item 5 (`review._actor_for`
strips any typed prefix and applies the command's; `Bundle.reviewers`
from the root index's `x_geo.reviewers`, `review` refuses an unlisted
id via `_check_reviewer`, lint **W042** flags outside stamps; `reject`
uses the same helper) and the **profile bump 1.10 → 1.11** (all
carriers by sed, §10 row by hand, es translation re-pinned:
`l10n_source_hash` now `sha256:e5e28cea…`). Tests +7 (suite
**390**); lint 0/0; dry-run unchanged. Docs: GEO-PROFILE §1/§2/§6/§7/
§9/§10, DESIGN §6/§9, USER-GUIDE Step 4/Step 7/two FAQ entries,
CLAUDE.md (two invariants), GAPS §3. Phase E (item 8, workflows) is
next.

Earlier the same day, **GAPS phase C landed**: item 4
(`publisher._staging`: build into a hidden sibling `.<dist>.publishing-
<pid>`, then rename the old dist aside, the new one into place, remove
the old; an exception removes the sibling and leaves the previous dist
byte-identical; `check_dist`'s refusals unchanged; every derived file,
the viewer page and the report page written with `write_atomic`; a
test scans `src/okf_web` for bare `write_text`) and item 7
(`manifest.json` concept entries carry `stale_after` + `verified_at`
instants via `Concept.stale_after_iso` / `Concept.verified_at`; JSON-LD
`subjectOf` CreativeWork carries `expires` + `dateModified`, generated
stamp as the fallback). Tests +5 (suite **383**); lint 0/0; dry-run
unchanged. Docs: GEO-PROFILE §7 (manifest artifacts; the §10 row
comes with phase D's bump), DESIGN §4 tree + §9, USER-GUIDE Step 6,
GAPS §3.

Earlier the same day, **GAPS phase B landed**: item 10 as
`okf-web mcp --url` (`src/okf_web/remote.py`, `RemoteSource`: the
manifest's markdown mirrored under `~/.cache/okf-web/remote/<digest>`
or `--cache-dir`, each file verified against its sha256 before it is
served, conditional re-checks every `--refresh-seconds` (300),
delta fetches, delisted files removed, unsafe manifest paths
ignored, 20,000-file cap, `.okf-dist` marker, the mirror served
through an origin outage with `last_error` in `okf_info`); the
bridge's `build_state` takes any `source` with `signature()`/`load()`;
`mcp`'s positional bundle is optional, `--url` and it are mutually
exclusive (exit 2). Per-tenant hosted retrieval is therefore a URL,
not a server — the transport the analysis called a decision was not
built. Tests +8 (suite **378**); lint 0/0; dry-run unchanged (39 /
1.0 / 2,406 / 0.897). Docs: DISTRIBUTION §4 (planned → shipped),
USER-GUIDE FAQ + cheat-sheet row, README, DESIGN §11, GAPS §3.

Earlier the same day, **GAPS phase A landed** (the user's ask:
"Implement gap findings as suggested, 1 through 10", after the gap
analysis of 2026-09-20 now recorded in `docs/GAPS.md`): item 1 (one
Unicode-folding tokenizer, `src/okf_web/text.py`, CJK as bigrams;
hashing embedder id `hashing-crc32u-512` so old caches rebuild), item
2 (`evaluator.retrieve_scored` with a relevance share per hit,
`RELEVANCE_FLOOR = 0.05`, `--min-relevance` on evaluate and mcp;
`okf_search` answers `coverage: none` with a note instead of a weak
hit and labels a weak best hit), item 6 (bridge `LocalSource` with a
files/mtime/bytes signature re-checked per tool call, `top_k` ≤ 10,
bodies clipped with a flag, nearest paths on an `okf_get` miss), plus
item 4's embedding-cache slice (version 2, `write_atomic`). The
embedding index keeps its per-query content hash (a test pins it —
GAPS §2). Tests `tests/test_gaps.py` (+11); suite **370**; lint 0/0;
dry-run 39 / 1.0 / **2,406** / 0.897 — the mean moved by one token
(one weak paraphrase hit fewer); the judged scorecard still records
2,407 from its own run. Docs: GAPS.md (new), EVALUATION, USER-GUIDE
FAQ, DESIGN §9/§11, DISTRIBUTION §4. Phases B–E (items 10, 4+7, 3+5,
8) follow on this branch. Open items untouched.

Earlier (2026-09-17), **three rules changed on the user's word**
(the ask: drop the record commit, make positions one-directional, and
exclude main from the push trigger), after the user asked whether the
workflows were caught in a loop over MEMORY. They were not (no
workflow pushes anything); the MEMORY ritual was feeding itself: every
main push needed a record commit, and a refresh commit re-staled what
it recorded. From this commit: (1) a main push is its own record — no
"Record the main push" commit before or after it; the positions
section states the rule and the next content commit refreshes the
sha; (2) positions are recorded in one direction only — this file
records nothing of the hosted edition's positions, picks or state;
(3) `okf-ci.yml` runs on every branch except `main`
(`branches-ignore`), since `main` only ever receives a commit whose
check passed on its branch. Files: the workflow, CONTRIBUTING,
CLAUDE.md (git rules, two-repositories, CI gotcha), this file (rhythm,
positions, incidents). Nothing measured changed; suite 359. Open items
untouched.

Earlier the same day, `main` fast-forwarded to `e9491a7` (archive) on
the user's word ("Push the commit directly to main"), carrying
`a238700` (E5) and that record, after the branch head's
`test-and-lint` check (now the aggregate of the three `tests` legs)
was green; positions below. The day before (2026-09-16 UTC),
**EDGE-CASES phase E5 landed** (the user's
ask: "Implement E5 using the current GitHub workflow"), the last
phase of the plan. Closes A4, A5, A6, A7: `survey` isolates every
per-page exception ("fetch failed") and `FetchResult.text` falls
back to UTF-8 on a bogus charset; `discover_sitemap` raises
`SitemapError` (unparseable / empty, naming the URL; CLI exit 2);
every default clock is UTC (`model.utc_now`/`utc_today`; `is_stale()`
compares against the instant, the log day is the UTC date); every
pipeline write goes through `model.write_atomic` (temp sibling +
`os.replace`); writing commands hold `<bundle>/.okf-lock` via
`model.bundle_lock` (`BundleLocked` → exit 2 naming the holder's pid;
a dead holder's lock is taken over; only `survey`/`init` create the
bundle, and a directory the lock created is removed if the command
left it empty); quarantine names carry a payload digest (+ counter);
CI is a `tests` matrix (3.10/3.11/3.12) plus the aggregate
`test-and-lint` job (the required check keeps its name);
`release.yml` also checks `okf_web.__version__`; `init` prints an
absolute MCP path. Tests `tests/test_edge_e5.py` (+15); suite
**359** (also green under python3.10 locally; the 3.12 leg is CI's);
reference numbers unchanged (lint 0/0; dry-run 39 / 1.0 / 2,407 /
0.897). Docs: EDGE-CASES §6, DESIGN §9, CONTRIBUTING (CI jobs),
USER-GUIDE (three FAQ entries), CLAUDE.md (invariant + gotcha). This
record carried it to `main` (the push above). Open items untouched.

Earlier the same day, `main` fast-forwarded to `580c077` (archive) on
the user's word ("Push the commit directly to main"), carrying
`ec6677d` (E4) and that record, after the branch head's
`test-and-lint` check was green; positions below. Earlier the same
day, **EDGE-CASES phase E4 landed** (the user's
ask: "Implement E4 using the current GitHub workflow"). Closes U3, U4,
U5, U6, U7, U9, A2, A3: `questions --llm` guarded by `--force` and
never writing an empty pack (exit 1); `review batch-approve` skips
rejected drafts with the reason, honours `--risk` (a refused, exit 2)
and has `--dry-run` (`review.batch_candidates` is the seam);
`review approve` is idempotent per actor (`review.approval_state`) and
a stale concept needs `--stale-after YYYY-MM-DD`; `review.resolve_path`
accepts `./`, bundle-prefixed and absolute spellings and suggests
close matches (`ReviewError`, a KeyError+ValueError); the feed
importer reads `utf-8-sig`, sniffs the delimiter on the header line,
raises `FeedError` once for a missing file / empty feed / missing
column / itemless XML, records rows sharing a link as collisions, and
`init` exits 1 when nothing was drafted; `cli.main` maps `FeedError`,
`ReviewError`, `QuestionSetError`, `ScorecardGuard`, `FetchError`, the
file-not-found family and YAML errors to one line + exit 2, `survey`
checks its input files first; lint E021 (status enumeration) with
GEO-PROFILE rows and `publisher.withhold_reason` naming each withheld
concept's status; publish warnings on stderr with `--fail-on-warnings`
(robots warnings included); `drift` exits 1 changed / 3 unreachable
only; `evaluate` validates the pack (`evaluator.validate_questions`,
exit 2), gates on `--min-hit-rate`/`--min-coverage` (exit 1), and
`write_scorecard(force=False)` refuses a dry run over a judged
scorecard (`ScorecardGuard`; the one fidelity test that did so passes
`force=True`); CI runs `evaluate --dry-run --min-hit-rate 1.0`. Tests
`tests/test_edge_e4.py` (+15); suite **344**; reference numbers
unchanged (lint 0/0; dry-run 39 / 1.0 / 2,407 / 0.897). Docs:
USER-GUIDE (ten FAQ entries, drift note, three cheat-sheet rows),
DESIGN §6 and §9, GEO-PROFILE §9/§10 (E021, no bump), EDGE-CASES §6,
CLAUDE.md gotcha (exit codes). That record (`580c077` (archive)) carried it to
`main`. Open items untouched.

Earlier the same day, `main` fast-forwarded to `001c065` (archive) on
the user's word ("Push the commit directly to main"), carrying
`cfc4d1c` (E3) and that record, after the branch head's
`test-and-lint` check was green; positions below. Earlier the same
day, **EDGE-CASES phase E3 landed** (the user's
ask: "Implement E3 using the current GitHub workflow"). Closes S2, S3,
S8, S9, S11: `structured.dumps_script_safe` (JSON-LD inert inside a
`<script>` element: `<`, `>`, `&`, U+2028/9 as `\u` escapes) and
`http(s)`-only `url`; the write gate (`surveyor.place_draft`) treats an
occupant owned by another URL or by none as a collision, never
overwrites `stable` content (a `human-batch:` sign-off included — a
proposal instead), confines producer paths (`PRODUCER_DENIED_DIRS`:
evaluations, l10n, capabilities, attesters, plus Windows-absolute forms
and backslashes) and pins `resource` to the surveyed URL (prompt
updated); the parse cache is keyed by a SHA-256 of the file bytes
(`_CACHE_VERSION` 2; `_cache_hit` treats any odd entry as a miss);
lint E020 (non-http `resource`, error) and W038 (non-http
`sources[].resource`, warning) with GEO-PROFILE §9 rows and a §10
note (no profile bump); the viewer links only `http(s)` resources,
the linkmap skips others; `evaluator.render_context` neutralizes
`<concept`/`</concept` in bodies and both evaluator prompts carry the
data-not-instructions rule. Tests `tests/test_edge_e3.py` (+14); suite
**329**; reference numbers unchanged (lint 0/0; dry-run 39 / 1.0 /
2,407 / 0.897). Docs: DESIGN §5 (write gate), §7 (context), §8
(inert derived files), §10 (cache row); USER-GUIDE FAQ (E020);
EDGE-CASES §6; CLAUDE.md invariants (write gate expanded, "derived
and rendered text is inert"). This record carried it to `main` (the
push above). Open items untouched.

Earlier the same day, `main` fast-forwarded to `0d7ecdc` (archive) on
the user's word ("Push the commit directly to main"), carrying
`a11c314` (E2) and that record, after the branch head's
`test-and-lint` check was green; positions below. Earlier the same
day, **EDGE-CASES phase E2 landed** (the user's
ask: "Implement E2 using the current GitHub workflow"). Closes S1, S5,
S6, S7: `src/okf_web/net.py` (`safe_fetch` + `FetchPolicy`: http(s)
only; loopback/private/link-local/reserved/multicast/unspecified
refused in every literal spelling and on every resolved address at
connection time, the socket pinned to the vetted address; redirects
re-checked, at most 5; caps — pages 5 MiB, robots 256 KiB, capability
bodies 1 MiB — under a deadline enforced per `read1`; proxies honoured
as urllib does, the proxy host itself unvetted) used by the bridge's
`_http_get`, `surveyor.fetch`/`discover_sitemap`/`survey`, `discover`,
`drift` and `publisher.check_robots`; `--allow-private-hosts` on
survey, publish, drift and discover (mcp had it) sets `allow_private`
(loopback included); tests use `allow_loopback` alone; library callers
can pass a full policy. `safe_fetch` returns every status, `fetch_text`
fails on 4xx/5xx. `logscan` skips lines over 16 KiB. S6:
`claude_code_client` probes `claude --help` once and runs
`-p --tools "" [--strict-mcp-config] [--model …]` with the rules on
`--system-prompt`, only page text on stdin, in an empty temp dir; a CLI
without the flags raises `LLMUnavailable` (CLI exit 2, mapped beside
`BundleNotFound`); a missing binary is still reported at the first
completion. Tests: `tests/test_edge_e2.py` (+42, loopback servers
only), `test_llm_clients.py` (+6), the bridge's private-host
test gains the shorthand spellings, `test_hosting.py` passes
`allow_private=True` (its recipes run on loopback); suite **315**;
reference numbers unchanged. Docs: DESIGN §8 outbound-fetch bullet,
DISTRIBUTION §4, USER-GUIDE two FAQ entries + a cheat-sheet row,
HOSTING §7 local note, EDGE-CASES §6, CLAUDE.md invariant. The branch
carried it to `main` with this record (the push above). Open items
untouched.

Earlier the same day, `main` fast-forwarded to `f6f80cd` (archive) on
the user's word ("Push the commits directly to main"), the first main
push under the live ruleset: the branch head's `test-and-lint` check
was green before the push, as the rule requires. It carries `1c4da8e`
(protection verified), `ee00f64` (archive) (rules completed), `c716935` (archive) (the
heredoc lesson) and this record; positions below. Earlier the same
day, **the branch rules completed** (the user's ask: confirm them).
Re-read from the rules endpoint, the ruleset carries all four
documented rules — `required_status_checks` (`test-and-lint`, strict
"up to date"), `required_linear_history`, `non_fast_forward`,
`deletion` — with an empty bypass list, active on `refs/heads/main`.
The branch carries this record on top of `1c4da8e` — two ahead of
`main` (`d705704` (archive)); the next main push needs the branch head's check
green. Earlier the same day, **branch protection verified live** (the
user applied it in the settings; the ask: verify the protection).
`main` reports `protected: true` (`list_branches`), and the rule
contents were read without administration rights from `GET
/repos/<owner>/<repo>/rules/branches/main` and `/rulesets/<id>` — a
route now documented in CONTRIBUTING.md "Verifying the rule" and in
the CLAUDE.md git rule. Found at the time: the ruleset "Branch
Protection" (id 23564996) had `required_status_checks` and
`required_linear_history` but **no `non_fast_forward` and no
`deletion` rule**, reported to the user, who added them the same day.
The administration endpoints answer 403 to the session's read-only
credential, so `list_branches` and the rules endpoints are the
verification path. This commit is docs + MEMORY only (CLAUDE.md rule
reworded for the live state, CONTRIBUTING.md verification route); the
branch is one ahead of `main` again.

Prior stamp (2026-09-15): `main` fast-forwarded to `d705704` (archive) on
the user's word ("Push the commit directly to main"), carrying
`a14910b` (archive) (a MEMORY-only record) and that record; positions below.
Just before it, `main` fast-forwarded to `fca6bbf` (archive)
on the user's word ("Push the commits directly to main"), carrying
`115c012` (the edge-case review), `d5c402a` (branch protection
prepared), `43bd313` (E1) and `fca6bbf` (archive) (the push record); positions
below. Earlier the same day,
**EDGE-CASES phase E1 landed** (the user's
ask: "Implement E1 using the current GitHub workflow"; the same message
asked why the GitHub tools could not set branch protection — answer:
the session's GitHub MCP tool set has no branch-protection or ruleset
endpoint, and direct API calls are outside the sanctioned path, so the
rule is applied by the user in Settings or with `gh api` locally;
`main` still reported `protected: false`). E1 closes U1, U2, A1, U8, S4
and S10: `publisher.check_dist` (+ `UnsafeDist`, a `PublishError`
subclass mapped to exit 2; `--force` on `publish` and `init` overrides
only a foreign non-empty directory — the bundle and its parents are
refused regardless), the hidden `.okf-dist` marker with
`model.marked_dists` skipping published copies in both loader and
publisher (one warning per copy), `model.BundleNotFound` raised by
`load_bundle` and mapped once in `cli.main` (exit 2 naming the path;
an empty directory publishes "nothing to publish"), symlinks skipped
by loader and publisher, operator files (`bundle-viewer.html`,
`.csv`/`.tsv`) never published and every shipped non-markdown file
named (`PublishResult.assets`, printed by the CLI), `verify_integrity`
path containment on the publisher's chunked digest helper, and `view`
refusing an output inside the bundle. Tests `tests/test_edge_e1.py`
(+26, suite **267**); reference numbers unchanged (lint 0/0; dry-run
39 / 1.0 / 2,407 / 0.897). Docs: USER-GUIDE Step 6 note + two FAQ
entries + cheat-sheet row, DESIGN §8, EDGE-CASES §6 (progress, with
the deliberate departures from the plan), CLAUDE.md invariant. Open
items untouched: they still read "nothing is code-pending", which
E2–E5 now contradict — that section changes on the user's word.

Prior stamp (2026-09-15, earlier the same day): **branch protection
prepared** (the user's ask after upgrading GitHub to Pro: "Implement
protected branches"). The
session's GitHub MCP tools carry no branch-protection or ruleset
endpoint, and direct API access is off-limits, so the rule itself is
applied by the user in the settings; this commit implements everything
around it: `CONTRIBUTING.md` (branch policy; the exact classic rule and
its ruleset equivalent — required check `test-and-lint` with "up to
date", linear history, no force push, no deletion, no admin bypass, no
PR requirement by choice, no push restriction by caution; what changes
for the fast-forward push: the branch head's check must be green
first; how to verify), a README row, and the CLAUDE.md git rule. CI
already runs on every branch push (`okf-ci.yml`, job `test-and-lint`),
which is what makes the required check available on the branch head.
At this commit `main` reports `protected: false`
(`list_branches`); re-check that field before assuming the rule is
live. Earlier the same day, **the edge-case
review shipped**
(`docs/EDGE-CASES.md`; the user's ask: analyze the toolchain for edge
cases that impact UI (clean and simple user logic), automation and
security, and create an implementation plan from the findings):
27 findings on this toolchain — security S1–S11 (the bridge's
private-host guard bypassed by shorthand IP literals, private DNS and
redirects; JSON-LD `</script>` unescaped; the surveyor's write gate
overwriting unowned concepts incl. the scorecard and planting l10n
overlays; publish and the loader following symlinks; fetchers
accepting `file:` and any host; the subscription CLI path with tools
on; unbounded reads; the parse cache trusted on mtime/size;
`javascript:` resources; `verify` path traversal; unescaped
`<concept>` delimiters), UI U1–U9 (**`publish` deletes whatever the
dist names**, reproduced: publishing the bundle into itself left 0 of
25 files; a missing bundle path lints/reviews/drifts clean and
publishes from nothing; `questions --llm` overwrites a curated pack;
batch-approve approves rejected drafts and ignores `--risk`; stale
approvals; feed BOM/delimiter/columns/variants; tracebacks for common
mistakes; operator files published; status enum unchecked),
automation A1–A7 (a dist inside the bundle loads as concepts;
warnings on stdout with exit 0 and drift's conflated exit code;
`evaluate` never fails and a dry run can erase the judged scorecard;
one bad charset aborts a survey; local dates vs UTC stamps; no atomic
writes or locks; CI blind spots) — each verified by reproduction or
unambiguous reading, with file:line, fix and test. Plan: **E1–E5**
(guardrails → reachability → content integrity → operator clarity →
automation hygiene), nothing implemented; waits for the user's go.
Method: four independent review passes, every claim re-verified
against the code before being written. Suite unchanged (241);
reference numbers unchanged. Open items untouched (the user's
list); when the phases start, that section changes on the user's
word.

Prior stamp (2026-09-10): `main` fast-forwarded to `482dcf5` (archive) on the
user's word ("merge the PR"; no pull request exists or has ever existed
in either repo, so the ask landed the viewer on `main` by the standing
fast-forward; positions below, phrasing recorded in the rhythm
section). Same day, **the bundle viewer shipped** (`okf-web view`,
`src/okf_web/viewer.py`; the user's ask, with "include read activity
to confirm that LLMs are reading the bundle"): one self-contained,
script-free page per bundle for the operator — at-a-glance tiles
(files ready to publish / held back, share vouched for by a named
person, live lookups, tokens to read the whole published set, the
scorecard's coverage vs. the raw-site baseline); the three-stage
pipeline strip (discover / interpret / surface) filled with the
bundle's own facts (well-known URL from `x_geo.site`, head tag,
llms.txt sections, index sections, entity edges, capability count,
JSON-LD object count, the five MCP tools); **"Where the revenue is"**
— one row per archetype: the shopper moment, the files declaring the
intent (`x_geo.intents`), the recorded judged count, and the
`REVENUE_MOMENTS` stake sentence (editorial vocabulary, never a
number — CLAUDE.md invariant extended); the full inventory grouped in
GEO-PROFILE order (trust chip + verifier line, effective risk,
freshness, intents, tokens; held-back / stale / due-soon marks;
entity links resolved to titles) plus the held-back list with
reasons (the warranty draft, high risk); the live-value table
(endpoint, parameters, receipt fields, attester, which products
point at it); the derived tier (5 objects on the example, and why
the machine-confirmed products emit nothing); the question→knowledge
blocks reused from the report (`report._question_blocks`, the new
shared function; judged rows link to the gap bullets); the
**read-activity panel** from `logscan` (three honest states: no log
given → how to add one; log with no AI fetch → zero is a finding +
the checks; else tiles, per-agent table with share and last seen,
per-file table, per-day CSS bars — `LogScanReport` gained `by_day`
and `agent_last_seen`, additive); and the trust/freshness posture
paragraph. Default output `./bundle-viewer.html`, outside the bundle
on purpose (drafts and logs are for the operator; the publisher ships
every non-hidden asset it finds). Tests `tests/test_viewer.py` (+5,
suite **241**: measured facts on the example, a no-scorecard/no-pack
bundle, logscan days/recency, the panel's three states, the CLI).
Docs: README quickstart line, USER-GUIDE Step 5 + cheat sheet,
MEASUREMENT, DESIGN §9. The example store's page was rendered with a
fictional 236-line sample log (16 days, five agents) for one browser
look, which drove two CSS fixes (stage columns growing around the
URL; nested lists inheriting the card style). Reference numbers unchanged (lint 0/0; dry-run 39 / 1.0 /
2,407 / 0.897).

Prior stamp (2026-09-09): `main` fast-forwarded to `ffe0ee2` (archive) on the
user's instruction ("Push the commits directly to main"; positions
below — at push time `main` already stood at `d2ab78c`, one past the
`edac30d` this file had recorded, moved outside this session's
record). Earlier the same day **`docs/HOSTING.md` shipped** (`e38b1be`;
`dc8772e` (archive) recorded it, see the incident note below): the
hosting matrix (twelve hosting types: nginx, Apache/shared hosting/CMS,
Caddy, Cloudflare Pages, Netlify, Vercel, GitHub Pages, S3 + CloudFront,
hosted commerce platforms via the delegated route, a container, GitHub
Actions, and CDN/WAF fronts) with one recipe each, the §6 bot-gate note
(Cloudflare's Block AI Bots / AI Crawl Control / Bot Fight Mode / WAF /
AI Labyrinth sit above `robots.txt`; `--check-robots` sees only the
managed robots.txt), the §7 verification transcripts, and the §8 record
of how each recipe was tested (live: Caddy 2.11.4 on three localhost
sites, wrangler 3.114.17's Pages emulator, netlify-cli 17.38.1; parsed:
nginx via crossplane, Apache via apacheconfig, vercel.json, cors.json,
the workflow YAML; not run: Vercel/S3 deploys, the Docker build).
`tests/test_hosting.py` (+6, suite **236**) serves a published dist
over real HTTP with the §0 header rules and runs `discover` over both
routes, the mismatch/missing cases, `check_robots` against a served
robots.txt, and the doc's fenced blocks (anchors resolve; DESIGN §8's
nginx block must equal HOSTING §2.1's). One code change fell out of the
testing: Cloudflare Pages' SPA fallback (no `404.html`) answered the
signature URL with the home page and a 200, so `discover` reported
"signature: present" — `_is_json_object` now requires the signature
body to be a JSON object (`test_html_fallback_cannot_fake_a_signature`,
verified failing before the fix). Pointers added in README (docs table
+ hosting section), DESIGN §8 (nginx block replaced by the tested `^~`
version; `.md` falls through to `default_type` so the charset
survives), USER-GUIDE (Step 6 + platform FAQ), CLAUDE.md (gotcha:
change serving rules in all three places together). Reference numbers
unchanged (lint 0/0; dry-run 39 / 1.0 / 2,407).

Prior stamp (2026-08-31): `okf-web report` gained its **detail
tier** (R2 grown): beneath the summary, `report.py` now renders
"The detail behind the numbers" — per-question rows recomputed at
render time by the evaluator's deterministic retrieval pass over the
bundle's committed `evaluations/questions.yaml` (one collapsible
`<details>` block per archetype; question, top-match path + title,
+n more, reading cost in tokens, and the paraphrase's fate: same /
different / no knowledge found). No LLM, no invented grades — judged
verdicts remain the recorded aggregates, and the section says so on
the page. Absent pack → section honestly absent (dry-run-scorecard
test covers it). Each block's summary line shows **both counts where
recorded** — "knowledge found for n / n · judged answers m / n
(recorded)" from the scorecard's `by_archetype` — because found ≠
answered (hit rate 1.0 vs coverage 0.949: policy and capability sit
at judged 2/3 with knowledge found 3/3), and the intro says finding
is necessary, not sufficient. The exact failing rows are **marked**:
`_judged_verdicts(scorecard)` reads per-question verdicts only from
what the scorecard records (the results table's `answered` column,
located by header so older five-column tables parse, plus gap-bullet
ids — a recorded gap is a recorded non-answer; nothing inferred) and
the detail row gains "judged not answered in the recorded evaluation
(see the gap above)" — pol-3 and cap-3 on the example — where the
pointer is a **working link**: gap bullets carry `id="gap-<qid>"`
anchors (ids parsed from write_scorecard's bullet format), the gaps
heading is `id="gaps"` (the fallback target when a verdict has no
matching bullet), and `:target` highlights the landed-on bullet. New
test
`test_report_carries_question_detail` (13 `<details>` blocks, no
scripts, byte-identical double render, 2×"judged answers 2 / 3");
suite 230.

Prior stamp (2026-08-28): a MEMORY-only bookkeeping commit
(`bd35189` (archive), the `5e6723e` (archive) precedent); that commit touched no code.

Prior cycle: **FIDELITY F5** (`d2ab78c`, on this branch, not yet on
main) — instant-precision timestamps closing D15, the last FIDELITY
finding: writers stamp ISO 8601 UTC instants (`model.utc_instant`);
`write_scorecard` emits the 30-day evaluation SLA as a real
`stale_after`; the example's spec stamps migrated (es
`l10n_source_hash` re-pinned); `is_stale` is instant-exact under a
datetime clock while date-clock paths stay conservative; profile
`x_geo` date keys are declared calendar dates (GEO-PROFILE §7). Mean
context re-measured 2,380 → 2,407 (ratio → 17×). Earlier same day:
READINESS **R1–R4 all shipped**; `docs/READINESS.md` (A1–A9) is the
review.

## Current state

- Package `okf-web` **0.2.0** (`pyproject.toml` and `okf_web.__init__`);
  `OKF_VERSION = "0.2"`, `PROFILE = "ecommerce-geo/1.13"` (bumped
  2026-11-06 for declared applicability; 1.12 on 2026-10-04 for the
  declared language; 1.11 on 2026-09-20 for GAPS items 3, 5, 7).
- Test suite: **630 passing** without `build`, 631 where it is installed (CI,
  and this container's 3.11 since 2026-11-10) and
  the packaging test runs (`python -m pytest -q`; run twice — ~27 s
  a run, the parse cache accelerating example-bundle loads). Includes
  the rolling freshness canary (lints the example at `today + 60d`) — when
  it fails, shift the example's stamps forward per the CLAUDE.md gotcha.
  Example freshness stamps run 2027-09-16 (scorecard) through 2028-08-01
  (passport); the promotion window ends 2027-12-31. Since F5 all spec
  timestamps in the example are `T00:00:00Z` instants (same dates);
  `write_scorecard` stamps `stale_after` = now + 30 d.
- Scale numbers (R4, measured on the 5k probe): load 11.9 s cold →
  0.58 s warm; query ~3 ms after ~300 ms index build; publish manifest
  streams 64 KB chunks; peak RSS 97 MB at 5k (linear; lazy bodies =
  stated deferral). Two working-state caches now: `.embeddings.json` and
  `.concepts-cache.json` — both gitignored, both in loop step 1's rm.
- Trust tiers (R3): `unverified` / `machine-confirmed` /
  **`human-attested`** (`human-batch:` actor, stamped by batch-approve) /
  `human-reviewed` (`human:`). E010 accepts only `human:`. Dry-run
  reference now also prints `paraphrase_questions: 39`,
  `paraphrase_hit_rate: 1.0`, **`paraphrase_agreement: 0.897`**, and
  `trust_mix {human-reviewed: 16, machine-confirmed: 3, unverified: 2}`.
  `okf-web init` is the guided no-LLM first run.
- Derived tier (`structured.py`, R2): publish emits `jsonld/` (Product,
  FAQPage, Organization, LocalBusiness, minimal MerchantReturnPolicy —
  human-verified concepts only, `LLMS_PRODUCT_CAP = 50` for llms.txt's
  product list) + full `llms.txt`; `report.py` renders the scorecard →
  `evaluations/geo-report.html`. The example bundle yields 5 JSON-LD
  files (ridgeline + tents stay machine-confirmed on purpose — the gate's
  own demonstration).
- `lint bundle-example --strict`: **0 errors, 0 warnings**.
- `evaluate bundle-example --dry-run` (lexical retriever) reference numbers:
  **39 questions, hit rate 1.0, mean context 2,406 tokens** (2,407
  before GAPS phase A's relevance floor dropped one weak paraphrase
  hit; 2,380 pre-F5 — re-measured each time). The example scorecard
  (`bundle-example/evaluations/geo-scorecard.md`) records coverage/groundedness
  0.949 and citability 0.923 **as figures written with the example, never
  measured** (its body says so; the audit of 2026-11-10), and carries no
  baseline: its store is fictional, so there are no pages to read. Its
  recorded gaps, `pol-3` and `cap-3`, were designed into the example. The
  measured numbers of this repository are the dry run's, above.
- Profile surface: **14 concept types** in the GEO-PROFILE type table
  (13 merchant-facing + the meta `GEO Scorecard`); **13 question archetypes**
  (`evaluator.ARCHETYPES`): discovery, product_fact, comparison, policy,
  fulfillment, trust, capability, promotion, fit_compatibility, ownership,
  compliance, local_availability, procurement.
- Lint codes **E001–E023, W020–W038, W041–W043**, plus W040 under `--strict-okf`
  (table in GEO-PROFILE §9). W037 = capability endpoint host outside the
  declared site's domain; its bridge-side sibling is the private-host
  refusal in `okf_execute` (`--allow-private-hosts` opts out).
- Question packs: **10** (outdoor/apparel/electronics/grocery/machinery ×
  en/es), 39 questions each; full archetype coverage is asserted by tests.
  The machinery pack (2026-10-02) is the equipment-dealer set: hit rate
  0.974 on the Machinio dealer skeleton, 0.615 on a feed-only bundle.
- Both build-out plans are complete: **ROADMAP Phases 1–4** shipped and
  **EXPANSION Phases A–E** shipped (profile bumps 1.4–1.8; ROADMAP Phase 4
  brought 1.9; fidelity Phase F4 brought **1.10**). The fidelity plan
  (`docs/FIDELITY.md`) is **complete**: F1–F5 shipped, D1–D15 all
  closed — writers emit ISO instants, readers tolerate both forms, and
  `is_stale` is instant-exact under a datetime clock.
  READINESS **R1–R4 all shipped** (R1: freshness defusal + canary, spec
  re-point + re-audit, W037 + bridge guard; R2: derived tier + report +
  honest positioning; R3: attestation tier + phrasing gap + init; R4:
  parse cache + inverted index + streamed hashing). The READINESS plan
  is complete.

## Branch and remote positions (as last verified)

- This repo: `main` is the last branch commit the user asked to
  fast-forward, always after that commit's `test-and-lint` check was
  green (the ruleset is live and complete: required check, linear
  history, no force push, no deletion, no bypass). The branch is at or
  ahead of `main`. There is no record commit (dropped 2026-09-17), so
  the sha named here is refreshed only by the next content commit and
  can lag: always `git fetch` and read `origin/main` before a main
  push. As of this commit: `main` == `bfbb0b7` (the user's "Push the
  commit directly to main" of 2026-11-06, 22:28 UTC, run 4 green
  first: a fast-forward from `25b33c5` over `bfbb0b7`, the
  question-set guards, profile 1.13), and the branch is seven ahead:
  `9431f79` (the measured baseline, which recorded `main` one push
  behind), `4001250` (MEMORY-only, the correction), `2240087` (the
  guide's typed comparison), `c7d9b3d` (the live check), `9342408`
  (the capped survey's two fixes), `a8ec7b2` (the write gate keeps
  every concept a page yields; run 10 green) and this commit (the
  live check's direct searches), which move to `main` on the user's
  word. Before that, `main` == `25b33c5` (the
  user's "Push the commit directly to main" of 2026-11-06, run 3
  green first: a fast-forward from `2814339` over `25b33c5`, the
  flip recorded). Before
  that, `main` == `2814339` (the user's "Push the commit directly to
  main" of 2026-11-06, the first under the re-created ruleset "Branch
  Protection", run 2 green first: a fast-forward from `3188302`, the
  founding push of this repository, over `2814339`, the record of the
  founding). The repository is public since 2026-11-06, verified at
  21:27 UTC. In the archive, the
  pre-rewrite history, `main` had moved to `ad81950` the same day on
  the user's "Push the commit directly to main": a fast-forward from
  `2982dad` over `23d1813`, `2173bb4` and `ad81950` (in this history
  `d473f65`, `aefcf78`, `d0f6a5e` and `82e3cc6`) after run 119 was
  green. Before that, `main` == `d473f65` (the user's "fast-forward of
  upstream to main" of 2026-10-26, from `7ca9852` over `486c29d` (U6,
  test hardening) and `d473f65` (U5, the decomposition) after run 116
  was green).
  Earlier fast-forwards, newest first, with this history's shas (a sha
  marked (archive) names a commit that exists only in the archive): `7ca9852` (the user's
  fast-forward of 2026-10-23, from `9d98690` over `e2f1e51` (U1),
  `fea7827` (U2), `75d2e23` (U3) and `7ca9852` (U4)), `9d98690` (the
  user's "Merge commits direct to main" of 2026-10-04, a fast-forward
  from `132927c` over the two language commits after run 110 was
  green), `132927c` (the user's "Push the
  commit directly to main" of 2026-10-02, a fast-forward from `53c0430`
  over the machinery starter pack after run 108 was green), `53c0430` (the user's "push the commit
  directly to main" of 2026-09-30, from `2b21298` carrying `a6d257f` and
  the hosting re-check's four fixes after run 107 was green), `2b21298`
  (the user's "push the commit
  directly to main" of 2026-09-23, from `8093422` over the TLS connection
  fix after run 105 was green), `8093422` (the user's
  "Implement pending" of 2026-09-20, a fast-forward from `e9491a7` (archive) over
  `532dd92` (the rule change), `8ea71f8` (GAPS phase A), `40a176e`
  (phase B), `8fc8752` (phase C), `7d47149` (phase D) and `8093422`
  (phase E), after the branch's check was green), `e9491a7` (archive) (the user's "Push the commit
  directly to main" of 2026-09-17, a fast-forward from `580c077` (archive) over
  `a238700`, E5, and `e9491a7` (archive), the last record commit ever made), `580c077` (archive)
  (E4 + its record), `001c065` (archive) (E3 + record), `0d7ecdc` (archive) (E2 + record),
  `f6f80cd` (archive) (the first under the ruleset: protection verified, rules
  completed, the heredoc lesson, its record), `d705704` (archive) (the E1 pick
  note + record), `fca6bbf` (archive) (the edge-case review, the protection docs,
  E1 + record), `482dcf5` (archive) (the viewer + record); the commit history
  below carries the rest.
- The hosted edition: not recorded here. Positions are one-directional
  since 2026-09-17: this file records nothing of its positions, picks
  or state; its own repository is authoritative for them.

## Commit history — this repo (newest first)

The rewrite of 2026-11-06 dropped the twenty commits that changed only
`CLAUDE.md` or `.claude/MEMORY.md`; they are not listed (the archive
keeps them), and every other sha is this history's.

```
(this commit)  Ask the live assistant for direct searches, and record whether they returned a page of the store: a reply made the default way carries no citations
a8ec7b2  Keep every concept a surveyed page yields: path stability in the write gate is per concept, not per page
9342408  Make a capped survey of a real store usable: rank the pages a limit keeps, and read a question set line by line before calling it empty
c7d9b3d  Ask a live assistant what it tells shoppers: the store's questions with web search on, graded against the bundle
2240087  Take the guide's typed comparison out, and refuse the next one with a test
4001250  Correct the recorded position of main: it has carried the question-set guards since 2026-11-06 (MEMORY-only)
9431f79  Measure the before: the same questions put to the store's own pages, and the example's typed comparison removed
bfbb0b7  Measure a store against questions written from it: grounded generation, negative probes, provenance, declared applicability (profile 1.13)
25b33c5  Record the repository made public, and the answer to the Actions question (MEMORY-only)
2814339  Record the repository founded twice and its first CI run (MEMORY-only)
3188302  Re-add the two continuity files on the history rewritten for publication, with every sha translated
82e3cc6  Make the repository fit for publication: the hosted edition's material leaves, a guard test keeps it out
d0f6a5e  Name the signer a signature's certificate carries, and a store without a Store Identity by its site
aefcf78  Let keyless signing log in without a browser: one door runs sigstore, and its link and code prompt reach the terminal
d473f65  Decompose without moving a byte: the first run as a library, the linter's contract types as one table, the viewer by section, publish in four stages, one parser builder per verb
486c29d  Harden the guards: determinism across processes, the mirror's refusals, the untested command paths, the static scans, a clean example, a recovering parser, 3.13 and the wheel in CI
7ca9852  Give the toolchain one error family and one exit table, a declared library surface, one home per primitive, and one configuration
75d2e23  Make the operator loop do what its words say: approve dates, drift skips feeds, drafts only, paraphrases kept, one language tag, sales valid through their last day
fea7827  Refuse what the doors should refuse: mirror and dist guards, a bridge that outlives bad input, proxied targets vetted
e2f1e51  Harden the rendered truth: one scorecard address, escaped counts, dry runs not judged
9d98690  Tag the derived tier with its language
7f43ca9  Declare the bundle's language: stop words and questions follow it (1.12)
132927c  Add a machinery starter pack for equipment dealers (en + es)
53c0430  Confirm the hosting recipes live and fix what the edge probes found: encodings, robots 4xx, named statuses, origins
a6d257f  Extend safe_fetch with POST: method and data through the one door
2b21298  Fix the pinned TLS connection: no live https fetch could be built since E2
8093422  Close GAPS item 8: read-only workflow tokens and SHA-pinned actions
7d47149  Close GAPS items 3 and 5: freshness defaults, reviewer identity, profile 1.11
8fc8752  Close GAPS items 4 and 7: swap-in publish, atomic derived files, freshness in the manifest
40a176e  Close GAPS item 10: okf-web mcp --url, a verified mirror of any published bundle
8ea71f8  Close GAPS items 1, 2 and 6: one tokenizer, a relevance floor, a live bridge
532dd92  Drop the record commit, record positions one way, keep CI off main
a238700  Implement EDGE-CASES phase E5: automation hygiene
ec6677d  Implement EDGE-CASES phase E4: operator clarity
cfc4d1c  Implement EDGE-CASES phase E3: content integrity
a11c314  Implement EDGE-CASES phase E2: reachability hardening for the bridge and the fetchers
1c4da8e  Record the live branch protection and the REST verification route
43bd313  Implement EDGE-CASES phase E1: guardrails against data loss and mis-scoping
d5c402a  Document and prepare branch protection for main (CONTRIBUTING.md)
115c012  Add the edge-case review and remediation plan (docs/EDGE-CASES.md)
129a373  Add the bundle viewer (okf-web view): contents, pipeline, revenue map, read activity
e38b1be  Add the hosting matrix (docs/HOSTING.md) with tested recipes
a0edeb8  Make the judged-row pointer a working link into the gaps list
a224c9f  Mark the exact rows the judge scored not answered
ea6da29  Show judged answers beside found knowledge in the detail blocks
a1ecea7  Give the answerability report a question-by-question detail tier
d2ab78c  Implement fidelity Phase F5 (instant-precision timestamps)
edac30d  Implement READINESS Phase R4 (parse cache, inverted index, streamed hash)
3ca26d2  Implement READINESS Phase R3 (attestation tier, phrasing gap, init)
5354d48  Implement READINESS Phase R2 (derived tier, report, honest position)
2d5b024  Implement READINESS Phase R1 (defusals, re-audit, W037 + bridge guard)
f38aed7  Correct the readiness review after a verification pass
ffaf47c  Add the adversarial readiness review (docs/READINESS.md)
02f828a  Make MCP the fast consumption loop in the distribution plan
646f6af  Add the distribution plan (docs/DISTRIBUTION.md)
90966ad  Implement fidelity Phase F4: spec coverage (profile 1.10)
12d282c  Implement fidelity Phases F1-F3: invariants, consumer surfaces, scale
99d2b51  Add the OKF-spec fidelity review (docs/FIDELITY.md)
014976f  Implement ROADMAP Phase 4: feed ingestion, countersignatures, localized packs   (profile 1.9)
6c43803  Implement EXPANSION Phase E: B2B & procurement (profile 1.8) — plan complete
a32f49c  Implement EXPANSION Phase D: omnichannel availability (profile 1.7)
0964e67  Implement EXPANSION Phase C: compliance & product passports (profile 1.6)
758ebd4  Implement EXPANSION Phase B: post-purchase ownership (profile 1.5)
2d9a068  Implement EXPANSION Phase A: fit & compatibility (profile 1.4)
9bd33c7  Implement ROADMAP Phases 2 and 3: ergonomics, packs, logscan, l10n, discover
e5628f9  Add the value expansion plan (docs/EXPANSION.md)
14dbccf  Lower adoption friction: discovery delegation, drift check, freshness policy, MCP bridge
3b622a4  Add promotion calendars (profile 1.1) and pluggable embedding retrieval
f142085  Add signed bundles: sigstore over manifest.json
13ff741  Harden pipeline against five simulation-probe findings
508f4d6  Revert "Add provenance viewer and review packet renderings"
c20ea49  Add provenance viewer and review packet renderings      (intentionally reverted pair)
4c5be6f  Add plain-English user guide (docs/USER-GUIDE.md)
bb43386  Add subscription-based LLM access (--llm claude-code)
71d472f  Add Apache-2.0 license
57c59af  Design OKF-Web: companion knowledge layer for ecommerce GEO
```

## Operating rhythm (the maintainer's recurring phrasings, with exact meanings)

- **"Implement X"** → build on the designated branch, run the full
  verification loop, one commit, `git push -u origin
  claude/geo-ecommerce-evaluation-system-qzv3qn`. Do not touch main.
- **"Push the commit(s) directly to main"** → `git fetch origin main`,
  confirm the branch head's `test-and-lint` check is green
  (`actions_list` filtered by branch; a refused push means it is not),
  fast-forward (`git push origin <sha>:refs/heads/main`), verify with a
  fetch, report. **No record commit** (dropped 2026-09-17): the push is
  its own record and the next content commit refreshes the positions.
- A request to carry a commit into the hosted edition is carried out
  from that repository, by its own procedure; nothing of it is recorded
  here.
- **"Status"** → concise state report, no changes.
- **"Merge the PR"** (first heard 2026-09-10) → there is no pull request
  in this repository and none is created; it means the same as the main
  push: fast-forward `main` to the branch head after the loop (no
  record commit). Check `list_pull_requests` first in case one appears
  someday.
- Pull requests: never created in this project; only on explicit request.

## Environment facts and incidents (lessons already paid for)

- Ephemeral cloud container: only pushed git survives. Commit and push
  anything worth keeping in the same turn it is produced.
- Local interpreters (2026-09-16): `python` is 3.11; `python3.10` has
  pytest and pyyaml installed `--user`, so
  `PYTHONPATH=src python3.10 -m pytest -q -p no:cacheprovider` pre-checks
  that matrix leg; `python3.12` is PEP 668-managed (pip refuses without
  `--break-system-packages`), so the 3.12 leg is CI's alone.
- The MEMORY ritual fed itself (2026-09-16/17): every main push needed
  a "Record the main push" commit, a refresh commit re-staled what it
  recorded, and each fast-forward ran CI a second time on `main`. The
  user asked whether the workflows were looping (they were not — no
  workflow pushes), then dropped the record commit, made positions
  one-directional and excluded `main` from the push trigger
  (2026-09-17).
- `set -e` did not gate a failed python heredoc step (2026-09-16): the
  script raised inside `cd … && … && python - <<'EOF'`, the following
  lines still ran, and a commit was pushed with only half its intended
  change (repaired by a follow-up commit; the first retry stumbled the
  same way, because a heredoc for the commit message sat mid-chain).
  Pattern from now on: write the script and the commit message to scratch
  files with their own commands first (`cat > f <<'EOF'`), then run
  `python f.py && git add … && git commit -F msg` as one `&&` chain
  on one line with no heredoc in it (a heredoc ends the chain at
  `EOF`; whatever follows on the next line runs regardless), and push
  only from a separate call after reading `git show --stat`.
- Branch protection is verified read-only (2026-09-16): `list_branches`
  reports `protected`, and the rules endpoints (`rules/branches/main`,
  `rulesets/<id>`) answer a plain read; the administration endpoints
  need rights the session does not have, so the ruleset is applied and
  changed in the repository settings. Never put a token in a command.
- GitHub via MCP tools only (no `gh` CLI). Oversized MCP list responses are
  saved to tool-result JSON files — parse those with python rather than
  re-calling the tool. The tool set has no branch-protection or ruleset
  endpoint (checked 2026-09-15 by search); protection settings are the
  user's to apply, and `list_branches` reports the `protected` field to
  verify them.
- The OKF v0.2 spec's canonical home is
  `GoogleCloudPlatform/open-knowledge-format` (root `SPEC.md`; clone at
  `/workspace/googlecloudplatform/open-knowledge-format`, audited at its
  `ad30107`, 2026-08-27). The prior location,
  `GoogleCloudPlatform/knowledge-catalog` under `okf/`, is a frozen
  snapshot its own README disowns (old clone still at
  `/workspace/googlecloudplatform/knowledge-catalog`, audited `fe3268a` —
  useful only for diffing). The repo also carries the implementation and
  sample bundles; `docs/FIDELITY.md` is the standing comparison, and the
  fe3268a→ad30107 delta (ISO datetime stamps, D15/F5) is recorded there.
- GitHub Actions API: run-level GET can serve stale cache (has shown
  `in_progress` long after completion) — the job level
  (`list_workflow_jobs`) is authoritative. As of 2026-08-17 the Actions API
  returned an integration-wide 403 ("Resource not accessible by
  integration"); pushes and contents APIs were unaffected, and local
  verification stood in. It has answered since; re-check before
  promising CI status to the user.
- The TLS boundary that never opened a socket (E2, 2026-09-16 → found
  2026-09-23): `_PinnedHTTPSConnection` could not be constructed, so every
  live `https://` fetch failed with a `TypeError` that the surveyor, drift,
  discover and the robots check each reported as an unreachable page, and
  42 tests passed because none built a TLS connection. Found in a
  deployment by its first live `https://` read. Corollary, now a
  CLAUDE.md gotcha and a test: a boundary that speaks TLS is verified over
  TLS (`tests/test_net_tls.py`), never only over plain HTTP.
- The one real CI failure: `HashingEmbedder` originally bucketed tokens with
  builtin `hash()`, which PYTHONHASHSEED salts per process — rankings differed
  across processes (intermittent local failures, and a real CI failure
  downstream). Fixed with `zlib.crc32` bucketing and a model-id bump
  to `hashing-crc32-512` so stale caches self-invalidate. Corollaries: run the
  suite twice; never use builtin `hash()` for anything persisted or ranked.
- When a CI-failure email arrives, first check whether the fix is already
  sitting in a pending/unpushed commit — pushing it may be the whole remedy.
- A live CLI run once leaked `bundle-example/.embeddings.json` into a commit
  and broke the incremental-cache test. It is gitignored now; still `rm -f` it
  before every commit.
- Foreground `sleep` chains are blocked by the harness. If a wait is truly
  needed, use a single bounded background sleep and act on its completion
  notification.
- Edit-tool `old_string` must match file text exactly — prefer several small
  exact edits over one large one.
- Test fakes for `discover` must accept the `timeout` kwarg the default fetch
  passes (`lambda url, timeout=15.0: fetch(url)`).
- Container restarts happen between turns of one session (seen
  2026-09-09): the repo came back as a fresh clone *behind* the branch
  (`d2ab78c` vs remote `823448c` (archive)), with the pip packages gone. First
  actions after any gap: `git fetch` + `git merge --ff-only
  origin/<branch>` and `pip install -e ".[dev]"`.
- `pkill -f <pattern>` kills the harness's own `bash -c` shell when the
  pattern occurs in the command text (exit 144; the command dies
  mid-way). Kill by PID from `pgrep -f` after filtering out `bash`,
  never by a pattern that appears in the same command.
- A heredoc-fed step (`python - <<'EOF' … EOF`) followed by `&&` on the
  *next* line is not gated by that step's exit status: on 2026-09-09
  the chain committed and pushed `e38b1be` without the MEMORY patch
  that had just failed its exact-match assertion, so the record needed
  a bookkeeping commit. Start multi-step commands with `set -e`, keep a
  chain on one logical line, and read `git show --stat` before pushing.
- Hosting-recipe tooling that works here, through the proxy: a Caddy
  binary from `https://caddyserver.com/api/download?os=linux&arch=amd64`
  (validate, then run live on localhost ports with `auto_https off`);
  `npx --yes wrangler@3 pages dev <dir>` (Cloudflare Pages emulator:
  honors `_headers`, serves `index.html` with 200 for missing paths
  unless `404.html` exists); `npx --yes netlify-cli@17 dev --offline
  --dir <dir>` (honors `_headers`/`netlify.toml` CORS, keeps its own
  Cache-Control, ignores Content-Type overrides); `pip install
  crossplane apacheconfig` for nginx/Apache syntax parsing. No nginx,
  Apache, or Docker binaries are installable here (apt unavailable).
- A position is fetched, not remembered (2026-11-10): `9431f79`
  recorded `main` one push behind because this file's positions
  section, which says itself that it can lag, was copied without a
  `git fetch origin main`. Fetch before writing a position, not only
  before a push.
- Edit `.claude/MEMORY.md` only from a fresh Read of the exact region —
  recalled wording drifts and exact-match edits miss (repeatedly
  observed).

## Open items

- **User-only** (never do these unprompted): the release path — TestPyPI
  rehearsal, then PyPI registration and `git tag v0.2.0` + push
  (DISTRIBUTION §6; release.yml publishes via Trusted Publishing).
- Nothing is code-pending here: all four plans are complete.
- The example scorecard's judged figures are labeled as written with
  the example (2026-11-10). A real judged run would replace them and
  needs a model: the maintainer's choice of where it runs.
- `evaluate --probe` has been seen against the real service with and
  without searches (2026-11-11 and 11-12); its count of searches
  matched the service's own. Not yet seen: a full run after the
  change to direct searches (the two-way comparison was one
  question), a `pause_turn` resume, and a declined turn. The
  shopper's wording puts second-person questions ("do you carry") to
  an assistant that then says it is not the store; whether to
  reword is undecided. One adapter exists (Claude with web search);
  another provider is a new class behind the `Engine` protocol and a
  way to choose it.
- A failed question generation keeps nothing of the model's reply:
  the next one that fails cannot be diagnosed from a record either.
- A concept a page stops yielding stays in the bundle as it was
  (draft or stable, with the old text's hash), and `drift` goes on
  reporting it changed: nothing retires it but a person. And
  `linkmap.json` names one path a URL, the last in path order when a
  page has several concepts.
- `okf-web mcp --url` (remote-bundle mode, DISTRIBUTION §4) shipped as
  GAPS item 10 (`40a176e`); nothing planned remains unscheduled here.

## Pointers (authoritative in-repo sources — not duplicated here)

- Profile spec: `docs/GEO-PROFILE.md` (type table, x_geo key table, l10n +
  countersignature conventions §7, discovery delegation §8, lint table §9,
  version history §10).
- Architecture and shipped-feature list: `docs/DESIGN.md`.
- Evaluation method and CI gating: `docs/EVALUATION.md` (§3 also holds
  the measured before and after: `evaluate --baseline`,
  `src/okf_web/baseline.py`); measurement methodology:
  `docs/MEASUREMENT.md`.
- Plans: `docs/ROADMAP.md` and `docs/EXPANSION.md` (both complete, kept for
  rationale); `docs/FIDELITY.md` (OKF-spec audit; F1–F5 complete);
  `docs/DISTRIBUTION.md` (channel plan; §4 makes MCP the fast consumption
  loop — one-block assistant setup, directory listings as release gate 6,
  the `mcp --url` remote-bundle mode shipped 2026-09-20 (GAPS item
  10, `src/okf_web/remote.py`); release gates await the
  user-only PyPI registration + tag).
- Hosting recipes: `docs/HOSTING.md` (matrix §1, recipes §2–5, bot
  gates above robots.txt §6, verification §7, how-tested record §8);
  enforced by `tests/test_hosting.py`.
- Branch policy and the protection rule for `main`: `CONTRIBUTING.md`
  (applied by the user in GitHub settings; verify with `list_branches`).
- Gap analysis and its phases: `docs/GAPS.md` (ten findings across
  search, state, access and freshness, the measurements behind the
  decisions, and §3's progress record per phase).
- Edge-case review and plan: `docs/EDGE-CASES.md` (27 findings: S1–S11
  security, U1–U9 UI, A1–A7 automation; phases E1–E5 all landed — E1
  2026-09-15, E2 to E5 2026-09-16; §6 records the departures from
  the plan).
- Bundle viewer: `src/okf_web/viewer.py` (`okf-web view`; documented in
  the README quickstart, USER-GUIDE Step 5 + cheat sheet, MEASUREMENT,
  DESIGN §9); tests `tests/test_viewer.py`.
- Operator how-to: `docs/USER-GUIDE.md`. Living example: `bundle-example/`
  (its `index.md` is the bundle's own map).

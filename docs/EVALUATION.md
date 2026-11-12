# Answerability Evaluation (AnsEval)

How OKF-Web measures whether a companion bundle actually makes a
store answerable by generative engines. The unit under test is the
**bundle**, not the model: the harness holds the model constant and
varies the knowledge.

## 1. Question set

Questions simulate what shoppers ask AI assistants, across thirteen
archetypes (one axis of coverage each):

| Archetype | Probes | Example |
| --- | --- | --- |
| `discovery` | Can engines match need → catalog? | "A tent for two on a summer thru-hike?" |
| `product_fact` | Concrete attributes | "Packed weight of the Alpine 2?" |
| `comparison` | Trade-offs across the catalog | "Regular vs long for 185 cm?" |
| `policy` | Terms and edge cases | "Return after pitching it indoors?" |
| `fulfillment` | Destinations, costs, timing | "Ship to Canada, what cost?" |
| `trust` | Legitimacy, payments, reaching humans | "How do I reach support?" |
| `capability` | What agents can *do* programmatically | "Get the live price via API?" |
| `promotion` | Current sales, codes, when deals end | "Is there a sale on right now?" |
| `fit_compatibility` | Will it fit me / work with mine? | "I'm 6'4" — which bag length?" |
| `ownership` | Owners: care, repair, warranty process | "Can I machine-wash it?" |
| `compliance` | Materials, origin, certifications, proof | "Is the down certified — can you prove it?" |
| `local_availability` | Stores, hours, pickup, on the shelf now | "Can I pick it up today?" |
| `procurement` | B2B: wholesale terms, MOQs, lead times, RFQ | "40 units by October — minimum and lead time?" |

Sets are LLM-generated from the bundle outline
([prompt](../src/okf_web/prompts/evaluator_questions.md)), then
**human-curated** — curation should add negative probes the bundle
*should* answer with a sourced "no" (out-of-catalog discovery, refused
capabilities). Because the generator reads the bundle's own outline,
the prompt requires **shopper vocabulary over bundle vocabulary**
(synonyms and paraphrase, at least one question per archetype avoiding
the target concepts' key nouns) — otherwise questions echo the
bundle's terms and inflate retrieval hit rate. Sets live in
`evaluations/questions.yaml` and are versioned with the bundle so
scores are comparable across runs.

### Fit: a set measures the store it was written from

A thin outline tempts a generator to invent a catalog, and a bundle
measured against invented questions scores the prompt, not itself.
Four mechanisms (profile 1.13) keep a set about the store:

- **Grounding.** Generation is told which archetypes the outline's
  concept types give evidence for (`evaluator.ARCHETYPE_EVIDENCE`:
  `procurement` needs a Trade Program, `local_availability` a Store
  Location, `compliance` a Product Passport, and so on) and writes
  its questions for those; for an applicable archetype the outline
  does not support it writes at most one deliberate probe, marked
  `probe: negative`, and it never reuses the prompt's own wording
  (the prompt carries no vertical examples a model could echo). An
  outline that describes no store at all makes it answer
  `reason: not-a-store`, which `okf-web questions` turns into a
  refusal. Behind the model sits a deterministic check,
  `check_grounding`: a question is grounded when one of its
  informative words occurs in the outline (titles, descriptions,
  entities, tags); negative probes are exempt, one per archetype; a
  generated set is refused, nothing written, when its ungrounded
  questions outnumber its grounded ones (`--allow-ungrounded` writes
  it anyway, for a set you intend to curate by hand). The model's
  reply is YAML; when one line of it is not (a store's name with an
  apostrophe inside single quotes, a colon in a question), the set
  is read line by line instead of being called empty.
- **Negative probes.** `probe: negative` marks a question the bundle
  is expected to answer with a sourced "no": an out-of-catalog need
  the range makes plausible, a refused capability. Curation adds
  them; the generator may add one per archetype.
- **Provenance.** Every set the toolchain writes carries a `meta`
  block: `source` (`generated` or `pack:<name>`), `generated` (by,
  at, `from_concepts`), the grounding counts, and `curated_by` once a
  person has read it through. The report states it beside the
  headline, so a reader can tell a curated set from a vertical's
  starter pack from a set generated out of one concept.
- **Declared applicability.** `x_geo.not_applicable` on the root
  index lists the archetypes the store's business has no answer for
  (no premises, no wholesale). Generation writes none for them, the
  evaluation sets their questions aside and records them under
  `metrics.not_applicable`, the report shows them as not applicable
  instead of as gaps, and lint W044 flags a name that is not an
  archetype or one the bundle's own concepts contradict. Undeclared
  archetypes stay applicable: a missing answer there is the finding.

## 2. Harness

Per question:

1. **Retrieve** top-k concepts (default 4) the way a frugal agent
   would. Retrieval is pluggable — any callable with the retriever
   signature — and the metric contract doesn't change:
   `--retriever lexical` (default) is tf-idf over
   title/description/tags/body with an `x_geo.intents` boost;
   tokens are letters-and-digits runs of case-folded, accent-stripped
   text in any script (CJK as character bigrams), so `devolucion` finds
   `devolución`; stop words are dropped per language (lists for English,
   Spanish, German, French, Portuguese, Italian and Dutch), chosen by the
   view's language — the root index's `x_geo.language` for the default
   view, the tag for `--lang`; an undeclared bundle keeps the English
   list and a declared language without a list drops none; every hit
   carries a relevance share (the fraction of
   the question's informative weight it matched) and hits below the
   floor (`--min-relevance`, default 0.05) are dropped — the floor
   removes single-common-word noise, not off-topic questions, which
   lexical overlap cannot detect (GAPS.md §2);
   `--retriever embedding` uses Voyage semantic embeddings with an
   incremental on-disk cache (`.embeddings.json`, hidden and never
   published; re-embeds only changed concepts);
   `--retriever hashing` is a dependency-free local embedder for
   offline runs — quality ≈ lexical, since feature hashing can't know
   synonyms.
2. **Answer** from retrieved context only
   ([prompt](../src/okf_web/prompts/evaluator_answer.md)). The
   answerer must cite concept paths, prefer higher trust tiers, defer
   live values to capability concepts, and emit
   `CANNOT_ANSWER: <why>` when the context is insufficient.
3. **Judge** ([prompt](../src/okf_web/prompts/evaluator_judge.md)):
   strict JSON verdict `{answered, grounded, cited[], notes}`.
   Grounding is judged against the context only; numbers, units,
   currencies, and time limits must match exactly. Correctly pointing
   at a capability for a live value counts as answered.

`--dry-run` executes step 1 only (no LLM) — cheap enough for every
CI run.

**Evaluate what engines see, not the working copy.** By default the
harness reads the working bundle, drafts included — useful while
iterating, but a full run would happily answer questions from drafts
the publisher withholds, overstating the published reality.
`--published` evaluates the published view (withheld concepts
removed; `--include-machine-confirmed` mirrors that publish mode).
Release scorecards should always use `--published`.

## 3. Metrics

With `N` questions, `R_q` the result for question `q`:

| Metric | Definition |
| --- | --- |
| `retrieval_hit_rate` | fraction of questions retrieving ≥1 concept |
| `coverage` | fraction with `answered = true` |
| `groundedness` | fraction answered **and** fully supported by context |
| `citability` | fraction whose cited concepts all exist and have trust tier ≥ `machine-confirmed` |
| `freshness` | of the answers that cited something, the fraction whose cited concepts are all within `stale_after`; absent when no answer cited anything, so a bundle that answers nothing cannot score a perfect freshness (review 2026-10-21, L-U9) |
| `context_tokens_mean` | mean tokens of retrieved context per question (~4 chars/token) |
| `paraphrase_questions` / `paraphrase_hit_rate` | questions carrying a shopper-vocabulary `paraphrase`, and the fraction whose paraphrase retrieved ≥1 concept (READINESS R3; saturates on small bundles) |
| `paraphrase_agreement` | fraction whose paraphrase retrieval shares ≥1 concept with the curated phrasing's — the honest phrasing-gap number: did shopper words find the *same* knowledge? (reference bundle: 0.897) |
| `trust_mix` | concept counts by trust tier — how much a person actually read (`human-reviewed`) vs. attested wholesale (`human-attested`) vs. machine-checked |
| `by_archetype` | `{questions, found}` per archetype in every run (how many questions retrieved knowledge), plus `answered` in a judged run only: a dry run records no verdict, so nothing downstream can read a retrieval pass as one (L-U1) |
| `baseline.*` | present only when the run measured it (`evaluate --baseline`): the same questions put to the store's own pages, read as text, with the same retriever and judge — `condition`, `pages`, `retrieval_hit_rate`, `context_tokens_mean`, and in a judged run `coverage` and `groundedness` (`pages_unreadable`, `pages_available` and `pages_cut` when they apply) |
| `live[]` | present only when the run asked (`evaluate --probe`): one record per live assistant — `engine`, `search`, `asked_as`, `questions`, `repeats`, `asked`, `answered` (the share of replies that were a substantive answer about this store), `checked` and `contradicted` (the answers the bundle's knowledge could check, and those it found wrong), `agrees` (when anything was checked), `names_store`, `cites_store`, `finds_store` (the share of replies whose searches returned a page on the store's address, when the assistant reports its searches' results), `searches_mean`, `judged_by`, `by_archetype` (`declined` and `errors` when they apply) |

Grading can be decoupled from answering: `evaluate --judge-model M`
grades with a different model than the answerer, and the scorecard's
`generated.by` records both identities
(`okf-web-evaluator/<answerer>+judge/<judge>`) — or, absent the
suffix, that the run was self-graded. Self-graded coverage is
evidence, not proof (READINESS A7/R3).

**GEO lift** = bundle coverage − baseline coverage, with the reading
cost of each side beside it (`context_tokens_mean`). Both sides come
from one run, never from an estimate:

```bash
okf-web evaluate my-bundle --baseline --write-scorecard
```

puts the same questions to the store's own pages — the pages the
bundle's concepts cite as their `resource`, the ones behind the
bundle's own answers first, fifty unless `--baseline-limit` says
otherwise, or the pages named in `--baseline-urls FILE` — fetched
through the one fetch door and read as the text a visitor sees. The
evaluator's own harness then runs over them unchanged: the same
retriever, the same `top_k`, and in a judged run the same answer
prompt and the same judge. The condition is generous to the pages on
purpose, so what remains is the bundle's: facts that live on no page,
live values a page states without a date, and the reading cost of a
whole page where one concept would do. A dry run records the
retrieval half only (how often a page matched, what reading it
costs); a store none of whose pages can be read has no baseline —
a refusal, exit 2, never a zero — and a scorecard carries a
comparison only when its own run measured one (the scorecard lists
the pages read). The report states the reading comparison as it came
out, either way.

The reference bundle carries no baseline: its store is fictional, so
there are no pages to read, and its scorecard's judged figures were
written with the example to show the format, not measured (the
scorecard says so). Its retrieval figures are the ones any
`evaluate --dry-run` reproduces.

**What a shopper is told today.** The scorecard measures the bundle
and the baseline measures the store's pages; neither says what an
assistant answers when a shopper asks it about the store today.

```bash
okf-web evaluate my-bundle --probe --write-scorecard
```

puts each question to a live assistant with web search on — today
Claude through the Messages API and its web search tool;
`--probe-model` names the assistant's model, `--probe-searches` caps
its searches per question, `--probe-repeats` asks each question more
than once — in one message worded as a shopper would word it (`I have
a question about the online store <name> (<host>). <question>`), with
no system prompt, so the assistant behaves as its provider ships it.
The run's judge then compares each answer with the concepts the
bundle retrieves for that question, and the record keeps what came
out: how often the assistant gave a substantive answer about this
store rather than a shrug, how many of those answers the store's
verified knowledge could check and how many it contradicted, and,
read off the replies without a model, how often it named the store,
how often it cited a page on the store's address, and how often its
searches returned such a page at all (`finds_store`: an answer
cannot cite a store its searches never found, so the two figures
are read together).

The searches are asked for directly (`allowed_callers: ["direct"]`
on the web search tool). Left at its default, this tool version runs
its searches inside the provider's own code execution, and a reply
made that way carries no citations: the first run on a real store
(2026-11-12) recorded that no answer cited the store, for answers
that could not have cited anything. The same question asked both
ways that day: three searches, about 59,500 tokens in and no
citation by default; two searches, about 22,100 tokens in and four
citations asked directly.

Three limits are part of the measurement:

- an API with search is the provider's assistant without its consumer
  app around it: close, not identical;
- an answer is one draw, so the record gives shares over replies and
  `--probe-repeats` widens the sample;
- `contradicted` is disagreement with the store's verified knowledge,
  not with the world. An answer the bundle does not cover is
  unchecked and counts neither way, and so does a live value (a
  price, stock) that the bundle serves as a capability instead of
  stating.

A declined turn and a failed ask are counted apart from answers; an
assistant that cannot be reached at all is a refusal (exit 2), never
a row of zeros. The check needs the root index's `x_geo.site` (an
assistant cannot be asked about a store with no name to find it by),
a judged run (not `--dry-run`) and the provider's API (`--llm api`: a
subscription CLI offers no web search); the provider bills each
search. The scorecard lists one row per question and the judge's note
on each contradiction, and the report states the result in a
sentence, only from that record. An assistant's answer is written
from pages anyone can publish, so the judge receives it as inert
text in a block of its own, after the store's verified concepts: it
cannot close that block or open one that passes for verified
knowledge.

It is the one measurement here that looks at the world instead of at
the bundle, so it is dated (the scorecard's `generated.at`) and it
attributes nothing by itself: assistants change on their own. Asked
before a bundle is published and again afterwards, it shows what
moved in what shoppers are told.

B2B-heavy stores should treat the `procurement` archetype
as a starting point and expand it with their own RFQ research — the
buyer journey differs enough that three generic questions understate
it.

## 4. Scorecard

`okf-web evaluate --write-scorecard` writes
`evaluations/geo-scorecard.md`, a `GEO Scorecard` concept:
machine-generated (`generated.by: okf-web-evaluator/<model>`), risk
`c`, metrics under `x_geo.metrics`, what was measured under
`x_geo.evaluated` (`view`: `working` or `published`; `retriever`;
`top_k`; `language` for a localized view), a measured comparison
under `x_geo.baseline` and a live check under `x_geo.live` when the
run made them (§3), per-question table and the
**knowledge gaps** list in the body. The report's footer states the
view and the method from that record instead of assuming them. The
report, the viewer and the bridge's `okf_info` read the scorecard only
at this path (lint E022 refuses a `GEO Scorecard` anywhere else or in
`draft`), render its counts as whole numbers or as escaped text, and
present a dry-run scorecard as "not judged". A localized view's
scorecard (`evaluate --lang es --write-scorecard`) is written to
`evaluations/geo-scorecard.<lang>.md`, so measuring a translation never
overwrites the store's own numbers. Publishing it inside the bundle
is deliberate:

- engines can read the store's own audited answerability and its
  cadence (`stale_after` on the scorecard = evaluation SLA — since F5,
  `write_scorecard` stamps it as a real 30-day UTC instant, so an
  un-renewed scorecard is retired by the ordinary freshness machinery
  instead of claiming freshness forever);
- the gap list is the surveyor's and reviewers' shared backlog;
- score history in git is the GEO regression record.

## 5. Gating

Suggested CI policy (thresholds are merchant-tunable):

| Check | When | Gate |
| --- | --- | --- |
| `okf-web lint --strict` | every PR | errors fail; warnings fail on release branches |
| `evaluate --dry-run` | every PR | `retrieval_hit_rate` < 0.95 fails |
| Full AnsEval | weekly + before big merges | `coverage` drop > 0.05 vs last scorecard fails; `groundedness` < 0.9 fails |
| `okf-web drift` | nightly | exit 1 (a source page changed) files a re-survey item; exit 3 (a source unreachable) files a reachability check |
| Faithfulness sweep | nightly, on drifted URLs | claim/source mismatch demotes concept to `draft` + review item |

## 6. Judged-set hygiene

- Never let the answering model see judge prompts or ground truth.
- Rotate ~20% of questions per quarter (stale sets overfit the
  bundle); keep a frozen core for longitudinal comparison.
- The judge scores support-in-context, not real-world truth; truth is
  covered mechanically by `okf-web drift` (did the source page change
  under the concept?) and semantically by re-surveying the URLs drift
  flags. Both must pass — one without the other is either
  hallucination-proof-but-stale or fresh-but-ungrounded.

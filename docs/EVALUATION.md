# Answerability Evaluation (AnsEval)

How OKF-Web measures whether a companion bundle actually makes a
store answerable by generative engines. The unit under test is the
**bundle**, not the model: the harness holds the model constant and
varies the knowledge.

## 1. Question set

Questions simulate what shoppers ask AI assistants, across twelve
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

## 2. Harness

Per question:

1. **Retrieve** top-k concepts (default 4) the way a frugal agent
   would. Retrieval is pluggable — any callable with the retriever
   signature — and the metric contract doesn't change:
   `--retriever lexical` (default) is tf-idf over
   title/description/tags/body with an `x_geo.intents` boost;
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
| `freshness` | fraction whose cited concepts are all within `stale_after` |
| `context_tokens_mean` | mean tokens of retrieved context per question (~4 chars/token) |
| `by_archetype` | `{questions, answered}` per archetype |
| `baseline.*` | optional same-questions run over raw site HTML: `coverage`, `context_tokens_mean` |

**GEO lift** = bundle coverage − baseline coverage, and the token
ratio `baseline.context_tokens_mean / context_tokens_mean`. The
reference bundle reports 0.611 → 0.944 coverage and an 18× token
reduction.

## 4. Scorecard

`okf-web evaluate --write-scorecard` writes
`evaluations/geo-scorecard.md`, a `GEO Scorecard` concept:
machine-generated (`generated.by: okf-web-evaluator/<model>`), risk
`c`, metrics under `x_geo.metrics`, per-question table and the
**knowledge gaps** list in the body. Publishing it inside the bundle
is deliberate:

- engines can read the store's own audited answerability and its
  cadence (`stale_after` on the scorecard = evaluation SLA);
- the gap list is the surveyor's and reviewers' shared backlog;
- score history in git is the GEO regression record.

## 5. Gating

Suggested CI policy (thresholds are merchant-tunable):

| Check | When | Gate |
| --- | --- | --- |
| `okf-web lint --strict` | every PR | errors fail; warnings fail on release branches |
| `evaluate --dry-run` | every PR | `retrieval_hit_rate` < 0.95 fails |
| Full AnsEval | weekly + before big merges | `coverage` drop > 0.05 vs last scorecard fails; `groundedness` < 0.9 fails |
| `okf-web drift` | nightly | exit 1 (source pages changed or unreachable) files a re-survey item |
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

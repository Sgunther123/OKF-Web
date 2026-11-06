# Gap analysis: search, state, access, freshness

**Status:** ten findings, landing in phases (§3). Read-only sweeps on
2026-09-20, every load-bearing claim re-checked in the code; the user
asked for the ten to be implemented as suggested.
The constraint throughout: nothing here adds a daemon, a database, a
search server or a login system. Each fix is a few lines in an
existing module, one more file in the dist, or a lint code.

## 0. What held up

- Retrieval is a pluggable callable over an in-memory inverted index,
  with an LLM-free paraphrase measure and a dependency-free hashing
  embedder.
- The human gate is a linter invariant (E010), backed by the producer
  write gate, quarantine, tool-disabled LLM runs, GET-only capabilities
  and the private-host guard.
- EDGE-CASES E5 made every pipeline write atomic and every clock UTC.
- Delta sync exists in principle: the manifest carries a sha256 per
  file, publish is lint-gated, drift costs zero tokens.
- There is no assistant memory anywhere: the bridge keeps no query
  history.

## 1. Findings

| # | Area | Finding | Fix (as suggested) |
| --- | --- | --- | --- |
| 1 | Search | The tokenizer `[a-z0-9]+` shredded accented text and yielded nothing for Cyrillic or CJK, so the four `.es` packs retrieved on wreckage | One tokenizer (`text.py`): letters-and-digits runs of case-folded, accent-stripped text in any script, CJK as character bigrams; ASCII tokenizes exactly as before |
| 2 | Search | Any concept sharing one term was returned: the hit rate could not fail honestly and an assistant got a weak hit instead of "not here" | A relevance share per hit (the share of the question's idf mass it carries), a small floor (`RELEVANCE_FLOOR = 0.05`, `--min-relevance`) that removes the noise tail, and an explicit empty result labeled `coverage: none`; weak best hits labeled |
| 3 | Freshness | A concept without `stale_after` is immortal: only Promotions got a default, feed and connectors never set one, no lint rule asked | Per-type SLA defaults stamped at the write gate, and a lint warning on a stable concept without a date |
| 4 | State | Publish emptied the dist and refilled it; every derived file except the manifest and the embedding cache were bare writes | Build into a sibling directory and rename it into place; `write_atomic` for every derived file; versioned, atomic embedding cache |
| 5 | Access | The actor helper passed a caller-supplied prefix through, so a batch approval could stamp the per-item tier | Strip any prefix before applying the caller's own; an optional reviewer allow-list on the root index with a lint warning and a refusal in `review` |
| 6 | State | The bridge held a boot-time snapshot, returned unbounded bodies, and its not-found error listed every path | Re-read the bundle when its signature moves (per tool call); `top_k` ≤ 10; bodies clipped with a flag; nearest paths on a miss |
| 7 | Freshness | Staleness was invisible to consumers without fetching every file | `stale_after` and `verified_at` per file in `manifest.json`; `dateModified`/`expires` on the JSON-LD `subjectOf` CreativeWork |
| 8 | Access | Workflows carried no `permissions:` block and pinned by floating tag | `permissions: contents: read`, SHA-pinned actions |
| 9 | State | Findings specific to the hosted edition | Recorded and addressed in that edition's own review |
| 10 | Search | Retrieval over a *published* bundle needed a clone of it | `okf-web mcp --url` — the planned remote-bundle mode, client-side over the published dist, so any served bundle is queryable without a server component |

Two things deliberately not done, because they would cost the
principle more than they return: no search service or vector database
(the hashing embedder plus the static files cover the need), and no
logins or API keys for merchants.

## 2. Measurements behind the decisions

- **The floor is small on purpose.** On the reference bundle the best
  hit of a real question carries between 9% and 100% of the question's
  idf mass (median 44%); a nonsense question ("quantum flux capacitor
  lunar warranty") carries 12% because it legitimately matches the
  warranty policy, and a greeting carries 21%. No lexical threshold
  separates off-topic from terse, so the floor (0.05) only drops the
  noise tail — on the reference bundle, two fourth-place paraphrase
  hits: a store location for a question about down feathers, a
  warranty policy for a question about shoe sizing. Every hit carries
  its share so the assistant can judge; the bridge labels the best hit
  weak below 0.2.
- **ASCII tokenization is unchanged**, so English bundles keep their
  rankings; the reference dry run keeps hit rate 1.0 and paraphrase
  agreement 0.897, and its mean context moves from 2,407 to 2,406
  tokens (one weak hit fewer).
- **Content addressing in the embedding index is kept.** The audit
  found the per-query re-hash O(bundle); a test pins the property it
  buys (an in-place edit re-embeds without a reload), and the hash of
  5,000 retrieval texts costs milliseconds next to a stale answer.

## 3. Progress

### Phase A — items 1, 2, 6 (2026-09-20)

`src/okf_web/text.py` is the shared tokenizer (evaluator and hashing
embedder; the embedder's model id gains a `u`, so old caches rebuild).
`evaluator.retrieve_scored` returns `(concept, relevance)` pairs and
`retrieve` wraps it; `--min-relevance` on `evaluate` and `mcp`. The
bridge: `LocalSource` with a `(files, newest mtime, bytes)` signature
checked on every tool call, `okf_search` results with `relevance`,
`coverage` (found / weak / none) and clipped bodies, `top_k` clamped
to 10, `okf_get` misses naming the five nearest paths. The embedding
cache carries a version key and is written atomically (the item 4
slice that lives in `retrieval.py`). Tests: `tests/test_gaps.py`.

### Phase B — item 10 (2026-09-20)

`src/okf_web/remote.py`: `RemoteSource` mirrors the markdown a
published `manifest.json` lists into a cache directory, verifying each
file's sha256 before it is written (a mismatch is refused, never
served), re-checks the manifest with `If-None-Match` /
`If-Modified-Since` at most every `refresh_seconds`, fetches only
changed files, removes delisted ones, ignores unsafe manifest paths
(traversal, absolute, hidden, Windows spellings), stops at 20,000
files, marks the mirror `.okf-dist`, and keeps serving the mirror when
the origin is down (`last_error`, shown by `okf_info`). The bridge
takes any `source` with `signature()` and `load()`; `okf-web mcp --url
<base>` wires it (`--cache-dir`, `--refresh-seconds`;
`--allow-private-hosts` opens loopback and private origins for local
testing). Any served dist is a `--url`; no authenticated transport
was built, and nothing in the principle wants it.

### Phase C — items 4 and 7 (2026-09-20)

`publisher._staging` builds into a hidden sibling of the dist
(`.<name>.publishing-<pid>`) and swaps it in whole: the previous dist is
renamed aside, the new one renamed into place, the old one removed;
an exception mid-build removes the sibling and leaves the previous dist
byte-identical. Every derived file (`.okf-dist`, `linkmap.json`,
`llms-snippet.txt`, `llms.txt`, the JSON-LD objects) and the viewer and
report pages are written with `write_atomic`; a test now scans the
package for bare `write_text` calls. `manifest.json` entries for
concept files carry `stale_after` and `verified_at` as spec instants
(`Concept.stale_after_iso`, `Concept.verified_at`), and every JSON-LD
`subjectOf` CreativeWork carries `expires` and `dateModified` — both
CreativeWork properties, so no typed object gains a property
schema.org does not define for it. The profile's §10 row for these
additive keys lands with phase D's bump.

### Phase D — items 3 and 5, profile 1.11 (2026-09-20)

`model.FRESHNESS_SLA_DAYS` and `default_stale_after`: the write gate
(`surveyor.place_draft`, which every producer passes through) stamps
the type's SLA from now when a producer left `stale_after` empty;
Promotions keep their
end-date rule; lint W041 flags a stable concept of an SLA type without
a date, and `review approve --stale-after` now dates a fresh concept
too. `review._actor_for` strips any prefix typed into `--by` before
applying the command's own, so `batch-approve --by human:x` stamps
`human-batch:x`; `Bundle.reviewers` reads `x_geo.reviewers` on the root
index, `review` refuses an unlisted id (`_check_reviewer`), and lint
W042 flags stamps from outside the list — the stamps themselves are
never rewritten. The profile bumps to **1.11** for the additive keys
of items 3, 5 and 7 (GEO-PROFILE §10); the Spanish translation's
`l10n_source_hash` was re-pinned per the playbook.

### Phase E — item 8 (2026-09-20)

Both workflows carry a top-level `permissions: contents: read`; the
release's publish job alone keeps `id-token: write` for PyPI Trusted
Publishing. Every action is pinned to a commit SHA with the version in
a trailing comment (`checkout` v4.4.0, `setup-python` v5.6.0,
`upload-artifact` v4.6.2, `download-artifact` v4.3.0, the PyPI publish
action at its `release/v1` head of the day), and a test refuses any
`uses:` line that is not a 40-hex pin and any workflow without the
permissions block.

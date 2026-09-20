# Gap analysis: search, state, access, freshness

**Status:** ten findings, landing in phases (§3). Read-only sweeps of
both editions on 2026-09-20, every load-bearing claim re-checked in
the code; the user asked for the ten to be implemented as suggested.
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
- EDGE-CASES E5 made every upstream pipeline write atomic and every
  clock UTC. The hosted edition had those helpers via the pick and had
  not adopted them (its X2 phase was waiting for exactly that).
- Delta sync exists in principle: the manifest carries a sha256 per
  file, publish is lint-gated, drift costs zero tokens.
- There is no assistant memory anywhere: the bridge keeps no query
  history, hosted telemetry aggregates server logs without addresses.

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
| 8 | Access | Workflows carried no `permissions:` block and pinned by floating tag; the hosted deploy exposed its Cloudflare token to the build step | `permissions: contents: read`, SHA-pinned actions, step-scoped secret, pinned `wrangler` |
| 9 | State (hosted) | The service layer used none of E5's helpers; the transaction log's hash chain broke under concurrent appends; demotion never reached the served dist | Adopt `write_atomic`, `utc_today`, `bundle_lock`; lock the ledgers; a publish job in the tick |
| 10 | Search (hosted) | Per-tenant remote retrieval was advertised and did not exist | `okf-web mcp --url` — the planned remote-bundle mode, client-side over the published dist, so each tenant's served bundle is queryable without any server component |

Two things deliberately not done, because they would cost the
principle more than they return: no search service or vector database
(the hashing embedder plus the static files cover the need), and no
logins or API keys for merchants (the hosted edition's "artifacts, not
logins" stance does real work).

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
testing). This is the hosted edition's per-tenant retrieval without a
server component: every tenant's served dist is a `--url`. The
authenticated multi-tenant transport the analysis called a decision
was not built; nothing in the principle wants it.

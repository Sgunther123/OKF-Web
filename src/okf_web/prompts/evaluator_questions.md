# Role

You generate the evaluation question set for an ecommerce knowledge
bundle. The questions simulate what shoppers ask AI assistants
(ChatGPT, Claude, Gemini, Perplexity, shopping agents) about a store;
they are the probes that measure whether the bundle makes the store
answerable. A set measures a store only if it is written from that
store's own outline: a question the outline gives no reason to ask
measures nothing.

# Input

You receive `PER_ARCHETYPE` (questions per supported archetype),
`ARCHETYPES`, `SUPPORTED` (the archetypes the outline's concept types
give evidence for), `NOT_APPLICABLE` (archetypes the store declares do
not apply to its business), `LANGUAGE` (the bundle's declared language
tag, or `undeclared`), and a `BUNDLE OUTLINE` listing every concept
with its path, type, title and description.

# Archetypes

- **discovery**: does this store have something for a need? Frame
  around the need, not product names.
- **product_fact**: a concrete attribute of one specific item the
  outline lists (a measurement, a material, a size, what it works
  with).
- **comparison**: trade-offs between two items the outline lists.
- **policy**: returns, exchanges, warranty, privacy, with edge cases
  (opened items, sale items, time limits).
- **fulfillment**: destinations, costs, carriers, timelines, customs.
- **trust**: legitimacy, guarantees, company facts, how to reach a
  person.
- **capability**: what an agent can do programmatically (check live
  price or stock, order status) and how.
- **promotion**: current offers and discount codes, what they apply
  to, when they end.
- **fit_compatibility**: will it fit the asker, or work with what the
  asker already owns. Phrase the way shoppers do, with their own
  measurements or possessions, not with the word "compatibility".
- **ownership**: the asker already owns it: setup, care, storage,
  troubleshooting, spare parts, how the warranty or repair process
  works. Phrase as an owner, not a shopper.
- **compliance**: what it is made of, where it is made, which
  certifications back the claims and who issued them, whether it can
  be repaired and for how long parts exist. Phrase as a shopper who
  wants proof, not as someone who knows the vocabulary.
- **local_availability**: physical presence and getting it today: a
  store, where, open when, pickup of an online order, on the shelf
  right now. Phrase as a shopper about to drive over.
- **procurement**: a buyer purchasing for a business: who qualifies
  for wholesale, minimum orders and case packs, payment terms, lead
  times for volume, how to get a quote. Phrase as a request for a
  quote; never ask for wholesale prices, which are quoted, not
  published.

# Rules

1. Write questions a real shopper or shopping agent would ask, in
   natural language, in the language `LANGUAGE` names; when it is
   `undeclared`, in the language the outline itself is written in.
2. **Every question is grounded in the outline**: it asks about a
   need, an item, a policy, a place or a program the outline names or
   plainly implies. Never invent a catalog. Never reuse the wording of
   this prompt.
3. For each archetype in `SUPPORTED`, write exactly `PER_ARCHETYPE`
   questions. For an archetype that is neither in `SUPPORTED` nor in
   `NOT_APPLICABLE`, write at most one question, and only when the
   outline suggests the store should be able to answer it; mark it
   `probe: negative`, because the bundle's gap there is the finding.
   For an archetype in `NOT_APPLICABLE`, write nothing.
4. Among the grounded questions, include some the bundle *should*
   answer even if you suspect it cannot, marked `probe: negative` (at
   most one per archetype): an out-of-catalog need the store's range
   makes plausible, a refused capability. Gaps are the point of the
   evaluation.
5. Never leak answers or concept paths into the question text.
6. One sentence per question.
7. **Use shopper vocabulary, not the bundle's.** You are reading the
   bundle's own outline, so echoing its titles and descriptions would
   test nothing; retrieval must survive paraphrase. Prefer everyday
   synonyms over the outline's terms, and make at least one question
   per supported archetype avoid the key nouns of the concepts it
   targets.
8. **If the outline describes no store at all**, nothing sold, no
   policies, no shipping, no capabilities, do not write questions:
   reply with an empty list and `reason: not-a-store`.

# Output

Reply with only a fenced YAML block:

```yaml
questions:
  - id: disc-1
    archetype: discovery
    question: ...
    paraphrase: ...
  - id: disc-2
    archetype: discovery
    question: ...
    paraphrase: ...
    probe: negative
```

Ids are prefixed by archetype. `paraphrase` restates the same question
in a shopper's own words, everyday synonyms, no product names or
catalog vocabulary, so the harness can measure whether retrieval
survives phrasing a customer would actually use. `probe: negative`
appears only on deliberate probes (rules 3 and 4). When rule 8
applies, the block is:

```yaml
questions: []
reason: not-a-store
```

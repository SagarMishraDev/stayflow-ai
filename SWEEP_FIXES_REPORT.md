# Sweep Fixes Report — multi-language live sweep, 2026-10-23

Four language/grounding defects from the 2026-10-23 live sweep (dates and
booking flows were otherwise correct). All fixes are deterministic,
backend-only, no new dependencies, no LLM-behaviour hacks. Every bug was
first reproduced against the pre-fix code with a scripted scenario
(mock provider, same harness as the test suite), then verified fixed by
the same scenario plus new regression tests in
`backend/tests/test_sweep_fixes.py` (13 tests).

Baseline before changes (verified by a full run): **320 passed / 2
pre-existing SQLite-env failures / 2 deselected** — the two known
failures are `test_hotel_crud_and_validation` and
`test_ingest_document_creates_chunks_and_embeddings`.

After changes: **333 passed / 2 failed / 2 deselected** — the same two
pre-existing failures only, i.e. 320 baseline + 13 new tests, zero
regressions; `ruff check app/ tests/test_sweep_fixes.py` clean.

---

## Bug A (critical) — language sticks across conversations

**Reproduction.** Guest chats in Devanagari Hindi, then sends a "new
conversation" request (no `conversation_id`) with an English message
("Book a room for this weekend"). Pre-fix: the API returned the **same
conversation id** — the old conversation, with its Hindi history and
stored `preferred_language`, was silently resumed.

**Root cause — two layers.**

1. `backend/app/agent/conversation.py`, `get_or_create_conversation`:
   for any request with a `guest_id` but no `conversation_id`, the
   guest's latest ACTIVE conversation (same hotel+guest+channel) was
   resumed unconditionally. That resume exists for Telegram/WhatsApp,
   whose webhooks never carry a conversation id — but web/widget
   clients hold the id themselves (session/local storage) and send it
   every turn, so for them a missing id *is* the "new conversation"
   signal. Resuming dragged the previous conversation's full history
   (which the real LLM mirrors) and its stored language preference into
   the "new" conversation.
2. `backend/app/agent/language.py`, `detect_language` (Roman tail): any
   message with ≥1 English vocabulary hit — or any ≥2 words at all —
   classified ENGLISH, and weak/tied signals classified at all instead
   of staying NEUTRAL. Slot replies and short fragments therefore
   overwrote `conversation.preferred_language` in the runner, flipping
   established conversations (this is also Bug B's root cause).

**Fix.**

- `conversation.py`: resume-by-guest is now restricted to the messaging
  channels that have no client-held conversation id
  (`_RESUME_BY_GUEST_CHANNELS = {"telegram", "whatsapp"}`). On
  web/widget/integration channels, a request without a conversation id
  creates a genuinely new conversation: no inherited history, no
  inherited language preference — its language is detected from its own
  first messages. Webhook continuity for Telegram/WhatsApp is
  unchanged.
- `language.py`: detection is confidence-tiered.
  - Confident signals classify: Devanagari-dominant script → Hindi;
    a clear Roman-Hindi majority → Hinglish; English now requires
    ≥2 English vocabulary hits **and** ≥1 English grammar/function word
    (new `_ENGLISH_FUNCTION_WORDS`: articles, pronouns, auxiliaries,
    prepositions, question words). English *content* words (room,
    guests, price, booking) are everyday Hinglish loanwords and no
    longer count as a switch on their own.
  - Weak or exactly tied evidence returns NEUTRAL, so
    `resolve_response_language` falls back to the conversation's own
    history / stored preference — the preference now only breaks ties
    for ambiguous short messages, as specified. Explicit requests
    ("speak in English") remain supreme and are checked first.
  - Corollary fix in the runner: `preferred_language` is only
    overwritten by a *confident* detection (it already was gated on
    `response_language is not None`; weak messages no longer produce
    one, so they can't clobber the preference).
  - Name spans are neutral for scoring: `_NAME_SPAN_RE` strips the name
    tokens after a lead-in ("my name is …", "mera naam …", "मेरा नाम …")
    before script/vocabulary scoring, keeping the lead-in itself as
    evidence. A Devanagari name inside an English sentence no longer
    flips the conversation to Hindi (and vice versa).

**Tests** (`tests/test_sweep_fixes.py`):
`test_new_conversation_starts_in_its_own_language`,
`test_new_conversation_mirror_hindi_after_english`,
`test_confident_detection_overrides_preference_mid_conversation`,
`test_weak_roman_slot_replies_are_neutral`.

---

## Bug B — booking summary not localized for Hinglish

**Reproduction.** Identified guest, Hinglish conversation: turn 1
"Mujhe room book karna hai" (Hinglish), turn 2 the slot reply "Deluxe
room chalega, 2 guests, 2026-12-22 se 2026-12-24 tak" → pre-fix the turn
resolved to `response_language = english` and the preview rendered
"Here's your booking summary: … Total price … Would you like me to
confirm this booking?" while the turns before/after were Hinglish.

**Root cause.** The templates were never the problem — the Hinglish
variants exist in `backend/app/agent/providers/mock.py` (`_summarize`
preview/create branches). The turn that *completes* the booking slots
is a telegraphic slot reply full of English loanwords; the old
detector classified it ENGLISH (≥1 English hit sufficed), and the
preview — rendered on that same turn — inherited the flipped language.

**Fix.**

- The confidence-tiered detection in Bug A: the slot reply is now
  NEUTRAL, the conversation's Hinglish preference stands, and the
  preview renders its Hinglish variant ("Aapki booking ka summary: …
  Kya main ye booking confirm kar doon?").
- Template consistency pass so every deterministic booking-flow
  template has a proper Roman-Hinglish variant (labels + framing):
  - `_summarize` `preview_booking` Hinglish: "- Total price:" →
    "- Kul price:" (the last English template sentence in the variant).
  - `_modification_summary_text` Hinglish: "Total price … (difference
    …)" → "Kul price … (antar …)", and "Bakaya rashi (amount due)" →
    "Bakaya rashi". English and Hindi variants byte-identical to
    before.

**Tests:** `test_hinglish_booking_summary_is_hinglish` (summary has the
Hinglish framing and no English template sentences; the following
confirmation is Hinglish too), `test_modification_summary_templates_per_language`
(Hinglish/Hindi/English modification previews each render their own
labels).

---

## Bug C — name capture fails across scripts

**Reproduction.** Devanagari conversation, bot asks for name+contact;
guest replies "मेरा नाम Test Guest है" → pre-fix the bot answered with
the Hindi no-answer fallback and no guest was created. Unit level:
`_contact_args("मेरा नाम Test Guest है")` → `None`.

**Root cause — two defects in `backend/app/agent/providers/mock.py`.**

1. `_GUEST_NAME_RE` only knew Latin lead-ins ("my name is", "mera naam",
   "this is", "i am", "i'm") and a Latin-only capture class
   (`[a-zA-Z …]`) — Devanagari lead-ins and Devanagari names could
   never match; a trailing "है" wasn't a terminator; and "mera naam
   Test Guest hai" captured the name as **"Test Guest hai"**.
2. `_booking_pending`'s assistant-reply signal list recognised the
   English ("could you share your name") and Hinglish ("hold kar
   sakoon") ask-contact texts but not the Hindi one ("…रख सकूँ"), so
   after a Hindi ask-contact the next message wasn't treated as a
   booking continuation at all and fell through to the FAQ fallback.

**Fix.**

- `_GUEST_NAME_RE` rebuilt: lead-ins in all three forms (English,
  Roman Hindi, Devanagari "मेरा नाम"); the capture accepts up to four
  name tokens in Latin **or** Devanagari script; `_clean_guest_name`
  trims trailing filler ("है", "हैं", "hai", "and", "calling", …) and
  rejects candidates that start with filler.
- Bare-name replies ("Test Guest", "टेस्ट गेस्ट") are accepted via
  `_bare_name`, but only when the caller is actively collecting contact
  details (`_contact_args(..., allow_bare_name=True)` — set at the
  booking/modify/food contact-collection sites, not in general
  routing), the whole message is 2–4 name-shaped words, and none of
  them is flow vocabulary (room types, "Do log", "Kal se parso tak",
  … are explicitly rejected).
- `_booking_pending` signals: added the Hindi ask-contact marker
  "रख सकूँ".

**Tests:** `test_name_capture_across_scripts`,
`test_bare_name_replies_only_in_contact_context`,
`test_hindi_conversation_captures_latin_name_and_continues` (exact
sweep scenario, asserts the Guest row exists and the Hindi summary
follows), `test_english_conversation_captures_devanagari_name`.

---

## Bug D — Hindi FAQ grounding gap

**Reproduction.** Knowledge base seeded with the Serenity Spa document
(the same content as `scripts/seed_knowledge.py`). "What are the
swimming pool timings?" → grounded plunge-pool answer.
"स्विमिंग पूल का समय क्या है?" → Hindi "no answer" fallback.

**Root cause.** Both retrieval paths are English-only for non-English
queries, in `backend/app/agent/tools/`:
- `search_faq` (hotel_tools.py) matches query words against English FAQ
  text — Hindi tokens can never match.
- `search_hotel_knowledge` (knowledge_tools.py) embeds the query with
  the hashed provider, whose tokenizer is `[a-z0-9]+` — a Devanagari
  query embeds to ~zero and retrieves nothing.
- The mock router's knowledge-keyword check was Roman-only, so the
  Hindi question didn't even route to the knowledge tool.

**Fix.** New `backend/app/agent/query_terms.py`: a small deterministic
facility/topic term map (Devanagari + Hinglish variants → canonical
English keywords: पूल/पुल → pool, स्पा → spa, जिम → gym, नाश्ता →
breakfast, वाईफ़ाई → wifi, पार्किंग → parking, चेक-इन/चेक-आउट →
check-in/check-out, समय → timings hours, plus restaurant, room
service, laundry, airport, yoga, massage, sauna, food).
`expand_query()` *appends* the canonical keywords to the guest's query
— the original text is never rewritten and plain-English queries pass
through unchanged. Applied at:
- `search_faq`: the expanded query feeds word matching (deduped, cap
  raised 8 → 10 so appended keywords aren't cut off);
- `search_hotel_knowledge`: the retriever embeds the expanded query
  (the tool result still reports the guest's original query);
- the mock router's knowledge check now tests the expanded text, so a
  Hindi facility question routes exactly like its English version.

The retrieved Serenity Spa chunk states the plunge-pool fact; where
timings genuinely aren't in the knowledge base the answer remains the
honest "not available" for that part (content-level, unchanged).

**Tests:** `test_expand_query_maps_hindi_terms`,
`test_hindi_pool_question_surfaces_plunge_pool` (exact sweep query,
asserts "plunge pool" is surfaced and the no-answer fallback is not
used), `test_hindi_pool_question_via_faq_tool` (the FAQ tool itself —
the path a real LLM takes — returns the pool entry for the Hindi
query).

---

## Files changed

- `backend/app/agent/language.py` — confidence-tiered Roman detection
  (function-word requirement), name-span neutrality, docstring.
- `backend/app/agent/conversation.py` — resume-by-guest scoped to
  telegram/whatsapp; new conversations on web/widget start fresh.
- `backend/app/agent/providers/mock.py` — cross-script name parsing
  (`_GUEST_NAME_RE`, `_clean_guest_name`, `_bare_name`,
  `allow_bare_name` at contact sites), Hindi ask-contact pending
  signal, knowledge routing over the expanded query, Hinglish template
  label consistency (preview + modification summaries).
- `backend/app/agent/query_terms.py` — NEW: Hindi/Hinglish → English
  facility term map + `expand_query`.
- `backend/app/agent/tools/hotel_tools.py` — `search_faq` expands the
  query before matching.
- `backend/app/agent/tools/knowledge_tools.py` —
  `search_hotel_knowledge` embeds the expanded query.
- `backend/tests/test_sweep_fixes.py` — NEW: 13 regression tests.

## Verification

- Repro script (pre-fix): Bug A resumed the same conversation id;
  Bug B summary in English (`response_language=english`); Bug C
  `_contact_args` → `None` for all cross-script forms and the flow hit
  the no-answer fallback; Bug D Hindi pool query → no-answer fallback.
  Post-fix, the same scenarios all pass.
- New tests: 13/13 pass (also 49/49 across test_sweep_fixes +
  test_language + test_agent_dates_modify run together). Full suite:
  **333 passed / 2 failed (only the two pre-existing SQLite-env
  failures named above) / 2 deselected** in 319.92s, vs the 320/2/2
  baseline — zero regressions. Ruff: clean on `app/` and the new test
  file.
- Not done here (per instructions): no commit/push/deploy, no live-DB
  changes. The parent agent releases and re-runs the live sweep.

## Round 2 — Mercury generation-layer fixes (post-deploy live re-test)

After commit 9d24e99 deployed, the live re-test (2026-10-23) confirmed
Bugs A, B and C fixed (no language leak into a fresh conversation, the
Latin-script name accepted in the Hindi flow, the Hinglish summary
rendered in Hinglish). One failure remained, plus one related
observation — both in the Mercury generation layer, not in retrieval
or the deterministic flows:

- Bug D, live evidence: the Hindi query "स्विमिंग पूल का समय क्या है?"
  now retrieves the Serenity Spa plunge-pool chunk (the round-1 unit
  tests prove the chunk reaches the model), but the model's Hindi
  reply garbled it: "मुझे तत्परह पुरिनिमगिंग पूल का सटीक समय उपलब्ध
  नहीं है। कृपया फ्रंट डेस्क से संपर्क करें…" — "plunge pool" was
  transliterated into nonsense Devanagari and the name "Serenity Spa"
  was dropped entirely.
- Date prose slip: in a Hindi booking opener the model's prose first
  stated the WRONG weekend dates (24–25 Oct) before the deterministic
  quote corrected them to 31 Oct–1 Nov — despite the existing DATE
  RESOLUTION note in the prompt.

### Prompt changes (no restructure; same sections, same style)

The grounding/date instructions are assembled in
`backend/app/agent/prompts.py` (`build_system_prompt`, used for the
Mercury path via the runner); the per-turn language instructions live
in `backend/app/agent/language.py`.

1. Proper-noun preservation — new bullet in the Language policy
   section of `prompts.py`: facility names, room names and place
   names from the retrieved knowledge and tool results are quoted in
   their ORIGINAL English spelling in every language ("Serenity Spa
   plunge pool", never a transliteration or translation); facts the
   knowledge contains are stated, and a missing detail (e.g. timings)
   is admitted honestly without dropping the name. The same one-line
   rule was added to the per-turn Hindi and Hinglish instructions in
   `language.py`, which sit at the end of the prompt closest to
   generation.
2. Date discipline — the "Dates and relative phrases" section of
   `prompts.py` now states that when a DETERMINISTIC DATE RESOLUTION
   note is present, its resolved check-in/check-out dates are the
   ONLY dates the reply may state anywhere; no other date may be
   mentioned in the prose, not even as an aside.

### Tests

- 3 new tests in `backend/tests/test_sweep_fixes.py` (16 total):
  the built system prompt contains the proper-noun rule (with the
  Serenity Spa example and the honest-missing-detail clause), the
  system prompt contains the exclusive-dates clause, and the Hindi /
  Hinglish per-turn instructions carry the untransliterated
  proper-noun rule.
- Targeted run (test_sweep_fixes + test_prompt_injection +
  test_language + test_inception_provider): 66 passed.
- Full suite: **336 passed / 2 failed (only the two pre-existing
  SQLite-env failures: `test_hotel_crud_and_validation`,
  `test_ingest_document_creates_chunks_and_embeddings`) / 2
  deselected** — 333 baseline + 3 new, zero regressions. Ruff clean
  on `app/` and `tests/`.
- Not done here (per instructions): no commit/push/deploy. The
  parent agent releases and re-runs the live Hindi pool + booking
  checks.

## Round 3 — deterministic grounding, empty-completion retry, Devanagari weekend phrases

Post-deploy live re-test #2 (commit 4fdeea5) failed both remaining
checks, and follow-up variance runs (fresh tabs, same build) separated
the causes:

- Hindi pool question: one run transliterated the facility name, one
  dropped it entirely, one got the "मैं समझ नहीं पाया" fallback —
  three different failure shapes for one question.
- Hindi booking opener "मुझे अगले सप्ताहांत के लिए कमरा बुक करना है":
  understood 2/2 in the variance round (so the earlier "didn't
  understand" was intermittent, NOT a regression from the Round 2
  prompt change) — but in BOTH replies the prose dates were Saturday
  24 → Sunday 25 October 2026 (THIS weekend) where "next weekend" must
  be 31 Oct → 1 Nov. English stated 31 Oct correctly.

### Diagnosis 1 — knowledge on the LLM path was tool-call-only

`backend/app/agent/runner.py` assembled the turn as system prompt +
history and left `search_faq` / `search_hotel_knowledge` entirely to
the model's discretion. Retrieval itself was proven good (Round 1
tests: `search_faq` and `search_hotel_knowledge` with
`expand_query()` surface the Serenity Spa plunge-pool chunk for the
exact Hindi query) — but Mercury repeatedly answered without calling
the tools, so no grounded chunk ever reached generation. A prompt
rule cannot preserve a name the model never saw.

### Fix 1 — deterministic pre-retrieval injected into the system prompt

`runner.py:187` `_retrieved_knowledge_note(db, ctx, message)` runs the
two existing tool handlers — `search_faq` (hotel_tools) and
`search_hotel_knowledge` (knowledge_tools) — against the guest's raw
message, with the trusted `ToolContext` (hotel_id from context, never
from the message). Both handlers apply `expand_query()` internally,
and their existing match semantics are the gate: FAQ word-overlap,
knowledge cosine > 0 (the `Retriever` default the tool itself uses).
Matches are injected into the system prompt (`runner.py:357-367`)
between the date-resolution note and the language instruction, under a
"RETRIEVED HOTEL KNOWLEDGE" header with the instruction to answer from
the material and keep proper nouns in their original English spelling.
Nothing matches → nothing is injected (greetings, booking slot
replies). Retrieval failure is caught, logged, and the chat continues
without the note. Hotel isolation is inherited unchanged from the two
services (FAQ `hotel_id` predicate; `KnowledgeRepository.list_chunks`
hotel-scoped SQL). The change is gated to LLM-backed providers
(`provider.name != "mock"`): the deterministic mock routes knowledge
itself and its behaviour is untouched.

### Diagnosis 2 — the Hindi "unsure" fallback fires on empty completions

The exact string lives at `runner.py:73` (`_FALLBACKS["unsure"]`,
Hindi entry) and is emitted at `runner.py:427`:

```python
reply = llm.content.strip() or _fallback("unsure", response_language)
```

i.e. exactly when the provider returns a FINAL answer (no tool calls)
with empty/whitespace content. On the Mercury path,
`InceptionProvider._parse_response` maps a completion with
`content: null`/absent to `""`, and Mercury intermittently returns
such empty completions for perfectly ordinary Hindi messages (booking
opener once, pool question once, in live runs). The guest is then told
"I didn't understand" for a message the model simply failed to answer
— the turn WAS understood; no parse failure or runner bug is involved.
Before Round 3 this was the ONLY condition that emits the string on
the LLM path (the other fallbacks need a ProviderError or iteration
exhaustion).

### Fix 2 — one bounded retry before the "unsure" fallback may fire

`runner.py:400-424`: on an LLM-backed provider, a final answer with no
content and no tool calls is re-asked once (with a warning log). A
retry that returns content or tool calls proceeds normally; a retry
that raises degrades via the existing `provider_down` / `generic_error`
fallbacks; only a SECOND empty completion reaches the "unsure"
fallback at line 427. The mock path is not retried (its empty replies
are scripted, deterministic outcomes). This does not paper over the
fallback — it reserves it for the case where the provider was asked
twice and still produced nothing.

### Diagnosis 3 — the resolver mis-resolved "अगले सप्ताहांत"; the note carried wrong dates

Direct check against a frozen Friday 2026-10-23, before the fix:

| message | resolved | verdict |
| --- | --- | --- |
| मुझे अगले सप्ताहांत के लिए कमरा बुक करना है | this_weekend, 2026-10-24 → 25 | WRONG — must be next (31 Oct → 1 Nov) |
| अगला सप्ताहांत | next_weekend, 2026-10-31 → 11-01 | correct |
| इस सप्ताहांत / bare सप्ताहांत | this_weekend | correct |
| अगले वीकेंड / इस वीकेंड / bare वीकेंड | None | no note injected at all |

Root cause in `backend/app/agent/relative_dates.py` (patterns at
lines 102-110): `_NEXT_WEEKEND_RE` contained only the nominative
`अगला सप्ताहांत`. Hindi grammar requires the oblique `अगले` before
`के लिए`, and `अगले सप्ताहांत` fell through to `_THIS_WEEKEND_RE`'s
bare `सप्ताहांत` alternative → this weekend. So the DETERMINISTIC
DATE RESOLUTION note WAS present in the prompt for the live opener —
pinning the WRONG dates — and the model's prose faithfully restated
the note. (The deterministic quote/summary in the full flow showed
31 Oct–1 Nov because Mercury passed its own, correct understanding of
अगले to the booking tools.) This was a resolver bug, not model
non-compliance; no prompt-side date injection change was needed beyond
making the existing note correct.

### Fix 3 — Devanagari weekend patterns completed

`relative_dates.py` `_NEXT_WEEKEND_RE` gains `अगले सप्ताहांत`,
`अगला वीकेंड`, `अगले वीकेंड`; `_THIS_WEEKEND_RE` gains `इस वीकेंड` and
bare `वीकेंड` (mirroring bare `weekend` → this weekend). Devanagari
weekday names already existed in `_WEEKDAYS` (सोमवार…रविवार) and are
unchanged. Post-fix, frozen at Friday 2026-10-23: `अगले सप्ताहांत` →
next_weekend 2026-10-31 → 2026-11-01; `इस सप्ताहांत`/bare `सप्ताहांत`
→ this_weekend 2026-10-24 → 25; all three वीकेंड forms resolve
(next/this/this); English results identical to before.

### Tests

7 new tests in `backend/tests/test_sweep_fixes.py` (file total 23):

- `test_llm_turn_injects_matching_knowledge_for_hindi_pool_query` —
  capturing LLM provider: the Hindi pool turn's system prompt contains
  the RETRIEVED HOTEL KNOWLEDGE block with "Serenity Spa" / "plunge
  pool", though the provider never requested a tool call.
- `test_llm_turn_injects_nothing_for_unrelated_message` — "hello"
  injects nothing against the same seeded hotel.
- `test_llm_turn_never_injects_another_hotels_knowledge` — a second
  hotel seeded with "Borealis" pool FAQ + knowledge: chatting in
  hotel A injects A's Serenity Spa content and never "Borealis".
- `test_empty_completion_is_retried_once_before_unsure_fallback` —
  empty-then-answer provider: reply is the real answer, exactly 2
  provider calls, not degraded.
- `test_second_empty_completion_still_earns_unsure_fallback` —
  always-empty provider: exactly 2 calls, reply is the exact Hindi
  fallback string.
- `test_resolver_devanagari_weekend_phrases_frozen_clock` — frozen
  Friday 2026-10-23: अगले सप्ताहांत → 2026-10-31 → 11-01 (key
  next_weekend); इस सप्ताहांत and bare सप्ताहांत → this weekend;
  अगले वीकेंड → next; इस वीकेंड and bare वीकेंड → this.
- `test_hindi_next_weekend_note_reaches_prompt_with_correct_dates` —
  capturing provider: the assembled system prompt for the exact live
  opener contains the DETERMINISTIC DATE RESOLUTION note pinning
  check-in to next weekend's Saturday (computed from hotel-local
  today), and NOT this weekend's Saturday.

### Verification

- Baseline (as specified for this round): 336 passed / 2 failed /
  2 deselected (failures: the pre-existing SQLite-env pair
  `test_hotel_crud_and_validation`,
  `test_ingest_document_creates_chunks_and_embeddings`). A baseline
  run launched at the start of this round finished 335/3/2, but it is
  not a clean reference: it executed for ~11 minutes while the edits
  below were landing, and its third failure was
  `test_rate_limit.py::test_whatsapp_webhook_rate_limited_per_sender`
  — a timing-sensitive webhook test unrelated to these changes, which
  PASSED in the clean post-change full run below (whose totals
  reconcile exactly: 340 baseline items + 7 new tests = 347).
- Targeted run (test_sweep_fixes + test_agent_dates_modify +
  test_language + test_agent + test_prompt_injection + test_rag):
  114 passed / 1 failed (`test_ingest_document_creates_chunks_and_embeddings`,
  one of the pre-existing pair; the other lives in
  test_pms_comprehensive.py, outside this file list) / 2 deselected.
- `tests/test_sweep_fixes.py` alone: 23 passed.
- Full suite after changes: **343 passed / 2 failed (only the same
  pre-existing pair) / 2 deselected** — 336 baseline + 7 new, zero
  regressions. Ruff clean on `app/` and `tests/`.
- Not done here (per instructions): no commit/push/deploy. The parent
  agent releases and re-runs the live Hindi pool question, the Hindi
  next-weekend opener (prose dates must now read 31 Oct → 1 Nov), and
  the Hindi FAQ turn.

## Round 4 — fuzzy ranking buries the answer in the real demo knowledge set

Post-deploy live re-test #3 (commit 58c8baa): the weekend-date fix held
(2/2), the empty-completion retry held (no "didn't understand" fallback
in 4 attempts) — but the Hindi pool question failed again, 0/2. The
telling detail was in live reply P2, which quoted retrieved material
about CHECK-IN ("…प्रॉपर्टी का मैप और अन्य विवरण welcome envelope में
दिए जाते हैं" — the check-in chunk's "a map of the property are handed
over in the welcome envelope"). Injection was running; it was
surfacing the WRONG chunks. P1 cited no facility content at all.

### Reproduction (realistic data, not fixtures)

Seeded a scratch SQLite DB through the exact path the live demo used —
`scripts/seed_demo.py`'s 4 FAQs + `scripts/seed_knowledge.py`'s 5
documents (airport, check-in instructions, spa & wellness, restaurants,
cancellation policy) — with `EMBEDDING_PROVIDER=hashed` (the provider
effectively serving the live demo; chunks: 10), then ran the exact
handlers `_retrieved_knowledge_note` calls, plus a full chunk ranking.

For "स्विमिंग पूल का समय क्या है?" (expanded by `expand_query` to
"…swimming pool pool timings hours open"), BEFORE the fix:

- `search_faq` returned **only the airport-transfers FAQ** — it has no
  ranking and matches on ANY word; the match was the generic expansion
  word "hours" ("Please book at least 4 hours ahead"). None of the 4
  real FAQs is about a pool.
- Knowledge cosine ranking of all 10 chunks: Cancellation 0 **0.1736**,
  Check-in 1 (welcome envelope) **0.1569**, Cancellation 1 **0.1519**,
  Restaurants 1 0.1405, Airport 1 0.1091, **Spa 0 (the plunge-pool
  chunk) 0.0950 — 6th**, Spa 1 0.0945, Airport 0 0.0593, Restaurants 0
  0.0474, Check-in 0 0.0182. The top-3 cut injected cancellation +
  check-in + cancellation — exactly what the live replies used.
- Hinglish "pool ka timing kya hai?": Spa 0 ranked **4th (0.2281)**,
  just outside the cut; the note injected Restaurants 0, Spa 1 (the
  yoga/fitness chunk — no pool) and Cancellation 0.
- English "What are the swimming pool timings?": Spa 0 ranked 1st
  (0.3512) — English worked, which is why the failure looked
  Hindi-specific. It is not a language bug; it is a ranking bug that
  the expanded Hindi/Hinglish queries happen to trigger.
- Bonus defect: the greeting "hello" scored **0.1075** against Spa 0
  and WAS injected — a pure hash-bucket collision; "hello" shares no
  token with that chunk, and the gate was cosine > 0.

Why the ranking fails: `expand_query` appends the generic time words
"timings hours open" (from समय), and those words are scattered across
every document (cancellation: "24 hours before…", "72 hours…"; check-in:
"breakfast timings"; restaurants: "open…", "24 hours"). The one
discriminative word, "pool", occurs in a single 120-word chunk, and
"swimming" occurs NOWHERE in the knowledge base (the spa document says
"plunge pool", never "swimming pool") — so after L2 normalisation over
long chunks, three off-topic chunks outscore the answer chunk. The
Round-1/3 unit fixtures never showed this: a lone ~35-word spa
document plus a pool FAQ have no competitors.

### Root cause

`_retrieved_knowledge_note` injected the handlers' raw top-3 verbatim,
trusting (a) a hashed-bag-of-words cosine ranking that generic
expansion terms swamp, (b) an unranked ANY-word FAQ match, and (c) a
cosine > 0 gate that hash collisions pass. Against the real demo
knowledge set all three fail at once for Hindi/Hinglish pool queries.

### Fix (scoped to the note path; tool handlers, retriever and the mock path untouched)

New helpers in `backend/app/agent/query_terms.py`:

- `targeted_terms(query)` — the canonical facility/topic terms a
  message targets: a term-map entry counts when a Hindi/Hinglish
  variant matches OR the canonical English term (or its head word) is
  present, so all three languages target the same terms. The generic
  time entry ("timings hours open") is excluded — it names WHEN, not
  WHAT, and its words appear in nearly every document.
- `text_contains_term` / `text_matches_term` — token-based matching
  ("spa" never matches "space"; hyphen-tolerant, so "wifi" matches
  "wi-fi" and "check-in" matches "checkin").

In `backend/app/agent/runner.py::_retrieved_knowledge_note`, three
deterministic corrections:

1. **Lexical gate** — a fuzzy knowledge result is injected only if it
   shares at least one real `[a-z0-9]+` token (len ≥ 3) with the
   expanded query. Kills collision-only noise ("hello" → nothing).
2. **FAQ topic filter** — when targeted terms exist, only FAQs
   mentioning one are injected (the note now fetches up to the
   handler's limit of 10 so the filter, not database order, chooses;
   still at most 3 FAQ lines). The airport FAQ is dropped for pool
   questions; the check-in FAQ still answers check-in questions.
3. **Exact-term guarantee** — new `_exact_term_chunks`: chunks that
   literally mention a targeted term (read via the same hotel-scoped
   `KnowledgeRepository.list_chunks`, so isolation is unchanged) are
   placed FIRST in the note, cosine-ordered among themselves, ahead
   of the gated fuzzy results, inside the same 3-passage budget.

### After the fix (same reproduction)

- Hindi pool query → note: **Spa 0 (plunge pool) first**, then
  Cancellation 0, Check-in 1; airport FAQ gone.
- Hinglish pool query → note: **Spa 0 first**, then Restaurants 0,
  Spa 1; airport FAQ gone.
- English pool query → note: Spa 0 first (unchanged winner); the two
  noise FAQs (matched via "what"/"the") are gone.
- "hello" → note empty.

### Tests

6 new tests in `backend/tests/test_sweep_fixes.py` (file total 29),
seeded with the ACTUAL demo content imported from the seed scripts —
competitors included, not a lone spa chunk:

- Hindi / English / Hinglish pool queries each inject the
  plunge-pool material from the realistic content (and for Hindi:
  ahead of the welcome-envelope chunk, with the airport FAQ absent).
- Greeting "hello" injects nothing against the realistic content.
- The exact-term scan never crosses hotels (hotel B's "Zorblax Spa"
  plunge-pool chunk never appears in hotel A's note).
- Helper unit tests for `targeted_terms` / `text_matches_term`.

Full suite: **349 passed / 2 failed (only the pre-existing SQLite-env
pair `test_hotel_crud_and_validation`,
`test_ingest_document_creates_chunks_and_embeddings`) / 2 deselected**
— baseline 343 + 6 new, zero regressions. Ruff clean on `app/` and
`tests/`. Not done here (per instructions): no commit/push/deploy —
the parent agent releases and re-runs the live Hindi pool question.

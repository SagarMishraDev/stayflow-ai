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

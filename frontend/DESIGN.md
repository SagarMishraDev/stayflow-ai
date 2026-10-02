# StayFlow AI — Frontend Design Plan

Written before any code (Step 2). Two surfaces, two moods, one honesty rule.

## Principles

1. **Data honesty over completeness.** Every screen renders only what the staff API
   actually returns. Where the backend has no endpoint for a wished-for capability
   (negotiation approval queue, conversation escalation, service-request assignees),
   the UI says so in plain language instead of faking a button.
2. **One bold moment per screen.** The home page spends its visual energy on
   today's arrivals and departures; everything else stays quiet, bordered, and
   scannable so a front-desk shift worker can read it at a glance.
3. **Every list states its state.** Skeleton placeholders while loading, a
   concrete next action when empty, and a retry affordance when the request
   fails — never a bare spinner, never a silent blank.

## Staff dashboard — "Front-desk console"

Operated in bright light, by people on their feet. High contrast, tabular
numerals for figures, mono for operational identifiers.

### Palette

| Hex | Name | Justification |
|-----|------|---------------|
| `#13322B` | Deep pine | Sidebar shell and primary buttons; a calm hotel-lobby green that recedes behind the work. |
| `#1F6B5C` | Pine | Links, focus rings, interactive accents; legible on paper at small sizes. |
| `#C0902F` | Brass | Reserved for the single bold moment: today's arrivals/departures figures and key stat numerals. Never body text. |
| `#F5F1E8` | Warm paper | Page background; easy on the eyes across a full shift. |
| `#FDFCF9` | Parchment | Card and table surfaces, one step lighter than the background. |
| `#B23A3A` | Brick | Danger, cancellations, sold-out flags; always paired with a text label, never color-alone. |

Text ink: `#24292C` (slate, not near-black).

### Typefaces

- **Archivo** — headings and UI text. A grotesque with tabular numerals, so
  prices and counts line up in tables.
- **IBM Plex Mono** — booking IDs, timestamps, audit metadata, tool traces.
  Operational data reads as data, not prose.

### Wireframes

Shell:

```
+--------+----------------------------------------------------------+
|        |  StayFlow Ops            [hotel switcher]  [bell] [user]  |
|  S I   +----------------------------------------------------------+
|  D E   |                                                          |
|  E B   |   <page content — paper background, parchment panels>    |
|  A A   |                                                          |
|  R R   |                                                          |
+--------+----------------------------------------------------------+
```

Home:

```
+---------------------------------------------------------------+
|  Tuesday 29 Sep                                               |
|  +----------------------------------+  +-------------------+  |
|  | ARRIVALS            DEPARTURES   |  | Occupancy           |  |
|  |    14                   11       |  |   68%               |  |
|  |  brass numerals, one brass rule  |  |  42 of 62 rooms     |  |
|  +----------------------------------+  +-------------------+  |
|  Pending approvals (n) | Open requests (n) | Active chats (n)   |
|  Today's movement -------------------------------------       |
|  #1042  Priya Nair   Deluxe King   2 guests   [Check in]      |
|  #1043  ...                                                   |
+---------------------------------------------------------------+
```

Booking detail:

```
+---------------------------------------------------------------+
| <- Bookings                      #1042  [CONFIRMED badge]     |
| Priya Nair · Deluxe King · 29 Sep -> 2 Oct · 2 guests          |
| +---------------------------+-------------------------------+ |
| | Stay breakdown            | Actions                       | |
| | Night  Price              | [Check in] [Cancel booking]   | |
| | Sep 29  ₹4,200            | (only legal next statuses     | |
| | Sep 30  ₹4,200            |  from STATUS_TRANSITIONS)       | |
| | Sep 31  ₹4,600            |                               | |
| | Total   ₹13,000           | Guest: name, phone, email     | |
| +---------------------------+-------------------------------+ |
+---------------------------------------------------------------+
```

### Generic-AI tell check (dashboard)

- No tracked-out ALL-CAPS eyebrow labels; section titles are sentence case.
- No middle-dot meta strings ("12 rooms · 3 floors · 2 pools") under headings.
- No `01/02/03` numbered badges anywhere.
- Buttons are verb phrases ("Save changes", "Confirm check-in") with no
  trailing arrows.
- No identical soft-grey-shadow cards on a grid; panels are flat bordered
  parchment, the arrivals band is the one brass-ruled exception.

## Guest web chat — "Golden hour"

A warm, brand-forward guest moment. Must feel nothing like the pine-and-paper
console above.

### Palette

| Hex | Name | Justification |
|-----|------|---------------|
| `#4E2445` | Damson plum | Header, launcher button, guest bubbles. Warm hospitality, zero overlap with dashboard pine. |
| `#E89B3C` | Marigold | Agent accent, quick-reply chips, focus ring. The friendly warmth of the brand. |
| `#F8F1E6` | Blush | Chat background; softer than the dashboard's paper. |
| `#FFFFFF` | White | Agent bubbles — clean contrast on blush. |
| `#2B2430` | Cocoa | Message text. |
| `#8A7B6E` | Warm grey | Timestamps, degraded-mode note, fine print. |

### Typefaces

- **Fraunces** — brand/header moments (the hotel name, welcome line). Warm
  editorial serif; the dashboard uses none.
- **Inter** — message body and composer. Quiet and readable at chat sizes.

### Wireframes

Full-page mode (existing `/chat` mount, polished):

```
+--------------------------------------------------+
|  (S) StayFlow Grand Hotel        [hotel v] [new]  |  plum bar
+--------------------------------------------------+
|        Agent: Welcome! How can I help?            |
|                          Guest: room for 2?  (S)  |
|        +-------------------------------+         |
|        | Deluxe King                   |         |  price card
|        | 29 Sep -> 2 Oct · ₹13,000      |         |  from tool_trace
|        +-------------------------------+         |
|  [Yes, confirm]  [No, change something]           |  chips
+--------------------------------------------------+
|  [Type your message............]  [Send]         |
+--------------------------------------------------+
```

Widget mode (embeddable):

```
 page content ...
                                  +------+
                                  | (S)  |  floating launcher (plum)
                                  +------+

open:
                                  +------------------+
                                  | StayFlow  [x]    |
                                  +------------------+
                                  | messages...      |
                                  +------------------+
                                  | [message] [Send] |
                                  +------------------+
```

### Generic-AI tell check (chat)

- No ALL-CAPS eyebrows, no numbered badges, no arrow-suffixed buttons.
- The price card appears only when the tool trace actually contains a
  `get_room_rate`/`preview_booking` result; otherwise plain text — the UI
  never invents structure the API didn't return.

## Shared rules

- API base from `VITE_API_URL` (default `/api/v1`, same-origin).
- TanStack Query for all dashboard data fetching; invalidation after every
  mutation.
- react-hook-form + zod on every form; zod constraints mirror the backend
  pydantic schemas (e.g. `price: gt 0`, `discount le 100`, date ordering).
- Staff dashboard: tablet-responsive minimum; semantic HTML, visible focus,
  keyboard-reachable controls, labels on every input.

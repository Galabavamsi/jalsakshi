# JalSakshi console: design spec ("Limewash & Register")

This is the build contract for the console restyle (`web/`). One pass, styling and i18n only.
**Unchanged:** `web/src/api/types.ts`, mock mode, routes, button names in English. Honesty labels (Demo data, Simulated, source and freshness on every number) stay on screen. Status always shows **icon + word + colour**. WCAG AA everywhere. Works at 375 px with no sideways scroll. Respects reduced motion. No secrets. Do not commit, push or deploy.

## 1. Concept

**Limewash & Register.** Households' answers are *painted* in watercolour on a limewashed village wall. The state's claim and the system's decisions are *printed* in a ruled register pinned beside them. The gap between paint and print is the story.

- **Paint means people.** Watercolour appears only where households' answers appear: day cells, the "Households said" panel, confirmations that close a ticket. One hero wash per page.
- **Print means the record.** The Har Ghar Jal claim, Cedar decisions, sources, timestamps and the Gram Sabha sheet are flat. They use ruled buff "register" paper and the serif record face. They are never painted.
- **The wall is chuna with neel.** The page is cool limewash, the blue-white of whitewashed Chhattisgarh walls. It is not cream paper. Action is neel indigo, and household verification is stamp-pad violet, the ink of every panchayat office.
- **One bold thing.** The hero question is set like painted wall lettering ("Did tap water come today?"): Anek Latin at width 125 and weight 800, on a neel wash. Everything else stays quiet.

Not doing: dark mode (the video and the print are light, and a half-tested dark mode risks AA), WebGL or canvas, live SVG filters on content, animated paint, flags for languages, all-caps labels, `→` on buttons.

## 2. Tokens (`web/src/styles/global.css`, replace the `:root` block)

```css
:root {
  color-scheme: light;
  /* Ground: limewash tinted with neel */
  --wall: #E9EFF1;   --wall-2: #DCE4E8;   /* page, hover */
  --sheet: #FBFCFC;                         /* boards pinned to the wall */
  /* Register: record objects only (state claim, Cedar notice, brief, source tags) */
  --register: #FAF5E9;  --register-line: #E4DAC4;  --register-margin: #D98C86; /* decorative red margin */
  /* Ink */
  --ink: #15203A;  --ink-2: #424E68;  --ink-3: #56617A;
  --rule: #C5D0D8 /* decorative */;  --rule-strong: #6E7F93 /* UI borders, 3.5:1 on wall */;
  /* Action (neel) and verification (stamp violet) */
  --jal: #1D5A9E;  --jal-deep: #153F70;  --jal-wash: #D9E7F4;
  --stamp: #5A3E9B;  --stamp-deep: #47307D;  --stamp-wash: #ECE6F7;
  --focus: #153F70;
  /* Day status: ink (text, icons) + wash (fill). Keep the .st-* hooks that set --st / --st-wash. */
  --st-supplied: #17694F;   --st-supplied-wash: #DCEFE6;
  --st-partial: #8A5300;    --st-partial-wash: #F8E7C6;
  --st-no: #A3291F;         --st-no-wash: #F7DCD6;
  --st-dirty: #6B4A2A;      --st-dirty-wash: #ECE1D2;
  --st-unverified: #555E6E; --st-unverified-wash: #E7E9EC;
}
```

Measured ratios (script in the scratchpad: `design/contrast.py`):

| Pair | Ratio |
|---|---|
| `--ink` / `--ink-2` / `--ink-3` on wall | 13.9 / 7.2 / 5.3 |
| Same on sheet | 15.7 / 8.1 / 6.0 |
| Same on register | 14.9 / 7.7 / 5.7 |
| `--jal` on wall / sheet / jal-wash | 6.0 / 6.8 / 5.6 |
| White on `--jal` / on `--stamp` | 7.0 / 8.1 |
| `--stamp` on stamp-wash | 6.6 |
| `--rule-strong` on wall / sheet | 3.5 / 4.0 |
| `--ink` / `--ink-2` on any under-text wash core (0.26) | ≥ 9.4 / ≥ 4.6 |
| `--ink-3` on a wash | **3.6, fails: never put `--ink-3` on a wash** |

| Status | English label | Short (cell) | Hindi / short | Ink on wash | White on ink | Pattern |
|---|---|---|---|---|---|---|
| SUPPLIED | Water came | Came | पानी आया / आया | 5.5 | 6.6 | none |
| PARTIAL | Partial supply | Part | थोड़ा पानी / थोड़ा | 5.2 | 6.3 | none |
| NO_SUPPLY | No water | None | पानी नहीं आया / नहीं | 5.6 | 7.3 | none |
| DIRTY | Dirty water | Dirty | गंदा पानी / गंदा | 6.2 | 8.0 | stipple |
| UNVERIFIED | Not confirmed | Few | पुष्टि नहीं / अपुष्ट | 5.4 | 6.5 | hatch |

Meanings (legend and tooltips): "Households said water came", "Some households got little or no water", "Most households got no water", "Households said the water was dirty", "Too few households answered". `STATUS.short` becomes a `Bilingual`.

**Spacing:** keep `--s1`…`--s8` (4, 8, 12, 16, 24, 32, 48, 72) and `--gutter` (16 px, 32 px from 720 px).
**Radii, chosen by object, not one radius for everything:** wall boards 14px; register slips 2px (paper is crisp); buttons 8px; painted cells and chips irregular (§4); the verified stamp is an oval.
**Shadows, by object:** boards `0 1px 0 rgb(21 32 58/.06), 0 18px 30px -24px rgb(21 32 58/.45)` (pinned to the wall); slips `0 1px 2px rgb(21 32 58/.14)` (paper on paper); chips, cells and buttons have none.

### Type

| Token | Size | Use |
|---|---|---|
| `--t-meta` | 0.875rem (14px, the floor) | source tags, timestamps, legend meanings |
| `--t-small` | 0.9375rem | secondary lines, nav on phones |
| `--t-body` | 1.0625rem (17px) | body |
| `--t-lead` | 1.25rem | ledes, verdict line, card titles |
| `--t-h2` | 1.5rem | section titles |
| `--t-h1` | 2.125rem | page titles |
| `--t-numeral` | 2.75rem | the one big count in a painted panel |
| `--t-wall` | clamp(2.5rem, 1.5rem + 5vw, 4.75rem) | hero wall lettering only |

- **Faces.** `--font-ui: 'Anek Latin Variable', 'Anek Devanagari Variable', 'Nirmala UI', system-ui, sans-serif`. Anek is one Ek Type superfamily, so Latin and Devanagari share x-height and stroke weight. Fallback is per glyph, so mixed strings render correctly. `--font-record: 'Tiro Devanagari Hindi', 'Noto Serif Devanagari', Georgia, serif` (it covers Latin too) is for record objects only: register-slip values, the Cedar notice title, the Gram Sabha sheet and print. `--font-code: ui-monospace, Consolas, monospace` is only for Cedar policy ids.
- **Imports (main.tsx):** `@fontsource-variable/anek-latin/wdth.css` (new; wght 100–800 and wdth 75–125; Latin is 104 KB), `@fontsource-variable/anek-devanagari/wght.css` (keep; never `wdth.css`, which is 726 KB), `@fontsource/tiro-devanagari-hindi/400.css` (keep).
- **English:** body weight 420, line-height 1.5; headings 700, line-height 1.15; `font-stretch: 87.5%` in dense tables and in the 375 px strip; wall lettering 800 at `font-stretch: 125%` with line-height 1.0 and letter-spacing -0.01em.
- **`:lang(hi)`:** same sizes, body weight 450, line-height 1.7 (headings 1.35, wall 1.2). No italics or underline emphasis; use weight. Links get `text-underline-offset: .3em`. Width has no effect, because Devanagari loads weight only.
- **Numbers:** `tabular-nums lining-nums`, Latin digits in both languages, `Intl.NumberFormat('en-IN')` grouping. Measure: prose up to 62ch, ragged right, sentence case everywhere.

## 3. Painted vs printed objects

| Object | Treatment |
|---|---|
| **Wall board** (village card, page sections) | `--sheet`, 14px radius, board shadow, 24/32px padding |
| **Register slip** (state record, Cedar notice, source tag, brief sheet) | `--register` background; ruled lines `repeating-linear-gradient(transparent 0 27px, var(--register-line) 27px 28px)` on slips taller than 3 lines; a double red margin line 12px from the left (two 1px `--register-margin` lines 3px apart); 2px radius; slip shadow; values in `--font-record` |
| **Painted cell / chip** (status) | §4 painted-cell CSS: solid `--st-wash`, `--st` ink, icon + word |
| **Stamp** (verified, confirmations) | `--stamp` ink, double ring, -4° rotation (the stamp itself, never body text) |

## 4. Watercolour system

**Where (the complete list).** The cap is 8 `<Wash>` per page.

| Place | Tone | Strength | Text on it |
|---|---|---|---|
| Villages hero band | `jal` | under-text | wall lettering in `--jal-deep` (6.2:1) |
| "Households said" panel on each village board | the week's most frequent status (a tie goes to the worse one); `unverified` if silent | under-text | `--ink`, `--ink-2` only |
| Village detail header | today's status, or `jal` | under-text | yes |
| Ticket header | OPEN/ASSIGNED/REOPENED/ESCALATED `no`; OPERATOR_REPORTED_FIXED/VERIFYING `partial`; CLOSED_VERIFIED `supplied` | under-text | yes |
| Halo behind the verified stamp | `supplied` | decor | no (the stamp has its own sheet) |
| Sign-in backdrop | `jal` | decor | no (the card on top is solid) |
| Brief header (screen only) | `jal` | under-text | yes |
| Claim/witness seam | not a wash: the register slip's deckled edge (static SVG mask, right edge on desktop, bottom edge under 820 px) | – | – |
| Empty states | not a wash: a "dry brush" dashed outline, 1.5px `--rule-strong` with a 6px/4px dash and an irregular radius | – | yes |

Never painted: buttons, nav, forms, tables, source tags, Cedar notices, the phone simulator, timestamps.

**How.**
1. Copy `<Wash>` from the scratchpad prototype `scratchpad/proto/src/components/Wash.tsx` to `web/src/components/Wash.tsx` (scratchpad = `C:\Users\Galaba Vamsi\AppData\Local\Temp\claude\D--hackathons-aws-env\da1885c1-2d08-4609-8ca0-6927d181835d\scratchpad`). It is Tyler Hobbs-style polygon deformation: mulberry32 seeded by an FNV hash of `seed` (the village or ticket id), a 7-sided base deformed twice, and layers deformed twice more. It renders inline SVG paths in `currentColor` from `var(--wash-<tone>)`, with `aria-hidden` and `focusable=false`. If the file is gone, re-implement it from this description; it is about 100 lines with no dependency.
2. Copy `scratchpad/proto/src/styles/watercolour.css` to `web/src/styles/watercolour.css`. It holds: `--grain` (a 160px alpha-only noise tile on `body` only; change its colour row to neel-grey `0.30 0.36 0.42` and cap alpha with `-0.5 0.22`); `--wash-grain` and `--wash-bloom` CSS masks on `.wash`; `.has-wash` (position relative, isolation); and the fallbacks below. Merge its reduced-motion block into the existing one in global.css; do not duplicate it.
3. Strength: `under-text` is 12 layers × 0.024 (core ≤ 0.26). `decor` is 24 × 0.045 and goes only where no text sits on top. No grain on sheets or slips.
4. **Painted cell (CSS only, no SVG per cell):**
   ```css
   .paint { background: var(--st-wash); color: var(--st);
     border-radius: 7px 10px 8px 11px / 10px 7px 11px 8px;
     box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--st) 55%, transparent),   /* crisp rim */
                 inset 0 0 8px -3px color-mix(in srgb, var(--st) 45%, transparent); } /* pigment pooling */
   .paint:nth-child(3n+2) { border-radius: 10px 7px 11px 8px / 8px 11px 7px 10px; }
   .paint:nth-child(3n)   { border-radius: 9px 11px 7px 9px / 11px 8px 10px 7px; }
   .st-UNVERIFIED.paint { background-image: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in srgb, var(--st) 22%, transparent) 5px 6px); }
   .st-DIRTY.paint { background-image: radial-gradient(color-mix(in srgb, var(--st) 30%, transparent) 1px, transparent 1.6px); background-size: 6px 6px; }
   ```
   Patterns cover only the top 55% of a cell (`background-size`/`-repeat` on the icon band), never behind words. Keep text at least 8px from the cell edge, outside the rim.

**Performance budget.** Each wash takes under 2 ms to generate and is memoised. There are no live `filter:` effects on content, no `mix-blend-mode`, and the grain scrolls with the page (never `fixed`). Washes never animate. Added JS is at most 6 KB gzip (locale and Wash); the main bundle stays at or under 140 KB gzip; fonts add 104 KB of Latin.

**Fallbacks.** Under `@media print`, `(forced-colors: active)`, `(prefers-contrast: more)` and `(prefers-reduced-transparency: reduce)`, `.wash` and the grain are hidden, the page is `--sheet`, painted cells keep their wash fill with a 2px `--st` border, and register lines remain (in print, `#999` hairlines). In forced colours, icon + word carry everything and patterns drop out.

**Motion (three things, all off under `prefers-reduced-motion`):**
1. **The one orchestrated moment:** the verified stamp lands when a CLOSED_VERIFIED ticket mounts. It goes from scale 1.18 and -9° to scale 1 and -4°, opacity 0 to 1, in 260ms `cubic-bezier(.2,.9,.3,1.2)`, once per mount.
2. The language swap cross-fades at 180ms (`document.startViewTransition`, feature-detected).
3. New Activity and Timeline rows use `@starting-style` (opacity and 6px translate, 240ms).

Nothing else moves. There are no hover lifts on cards.

## 5. Language

- **English is the default** for everyone; `navigator.language` is ignored. Precedence: `?lang=hi|en` (saved), then `localStorage['jalsakshi.lang']` (every access in try/catch), then `en`.
- **Module:** copy `scratchpad/proto/src/i18n/locale.tsx` to `web/src/i18n/locale.tsx`. It exports `resolveInitialLocale`, `applyDocumentLocale` (sets `<html lang>`, `data-locale` and `document.title`: "JalSakshi console" / "जल साक्षी कंसोल"), `LocaleProvider`, `useLocale`, `useT` (`t(pair)` or `t(fn, params)`), `pickField(obj, 'reason'|'text', locale)` and `LanguageSwitcher`. In `main.tsx`, call `applyDocumentLocale(resolveInitialLocale())` before the first render and wrap `<App>` in `<LocaleProvider>`. `index.html`: `lang="en"`, title "JalSakshi console", English first in `<noscript>`.
- **Switcher:** a segmented control at the top right of the header on every page, including sign-in. It shows `EN | हिन्दी`: two buttons, each at least 44×44, with `aria-pressed`, `lang="en"` / `lang="hi"`, `translate="no"`, and accessible names "English" and "हिन्दी (Hindi)". The group is `role="group"` with the label "Language" / "भाषा". The active option is `--jal` filled with white text; the inactive one is outlined in `--rule-strong`. Switching keeps the route and on-screen state, removes `?lang` with `history.replaceState`, saves the choice, and announces it in a polite live region ("Showing the console in English." / "कंसोल अब हिन्दी में है।"). Hovering or focusing हिन्दी warms the Devanagari font (`document.fonts.load`).
- **Single-language rendering:** rewrite `<Bi>` to render one element in the active language with `lang={locale}`. Keep its props (`t`, `hi`, `en`, `as`, `htmlFor`) and ignore `inline`. Delete the `.bi-en` / `.bi-inline` stacking CSS. This switches all 124 call sites. Then fix the hand-built pairs: SourceBadge, TallyTiles, Timeline, StatusStrip aria labels, TicketParts (VerifiedStamp), BriefPage, ActivityPage, PolicyDenial, the Layout skip link and wordmark label, the Simulator `people()` labels, VillagesPage Claim/Witness/OpenTicket, ClaimSummary, and `lib/events.ts` (return `Bilingual`, not `"${hi} (${en})"`). Every `aria-label` goes through `t()`.
- **String conventions:** enum labels stay in `lib/labels.ts`. Page copy stays inline as `{ en, hi }` pairs, English written first as the source of truth; both fields are required by the type. Interpolated or plural messages go in `src/i18n/messages.ts` as `BilingualFn` named `<page><Thing>` (e.g. `villagesVerdictGap`). Plurals use `Intl.PluralRules`, with an explicit zero message (CLDR puts 0 in "one" for Hindi).
- **Bilingual API fields:** `PolicyDenied` uses `pickField(d, 'reason', locale)`; `ActivityItem` uses `pickField(i, 'text', locale)`, each wrapped in `lang={locale}`. `Brief.markdown_hi` is always Hindi (§6.4). IVR prompts are always Hindi (§6.5).
- **No doubled text in English mode.** The second language appears only where it adds meaning, always with its own `lang` and one step smaller in `--ink-2`:
  1. The wordmark: "JalSakshi" with "जल साक्षी" beneath.
  2. Proper names from data. Village names are shown as `Nayapara` plus `नयापारा` beside them, using `lib/places.ts`: `romanVillage(village)` takes the `v-<slug>` id ("v-nayapara" becomes "Nayapara"), adds " (demo)" when the name ends in "(डेमो)", and falls back to the Devanagari alone. A small gazetteer covers block and district (दुर्ग Durg, पाटन Patan, धमधा Dhamdha), and Latin input passes through. Household and operator names stay as written (Devanagari, `lang="hi"`) beside the masked phone.
  3. The Hindi IVR line under its English caption in the simulator.
  4. The Hindi brief.
- **Scheme words stay as they are, glossed once per page:** "Har Ghar Jal (tap water in every home)", "Nal Jal Mitra (pump operator)", "Gram Sabha".

## 6. Pages

**Shell (all pages).** Mock mode keeps a violet hatched strip on top: "Demo data: every village, household and number here is a sample. No real calls are placed." Header layout: `[tap mark] JalSakshi / जल साक्षी` · nav (Villages, Activity, Phone simulator) · `EN | हिन्दी` · Sign out. Under 760px the nav becomes the existing bottom bar, the header keeps brand and switcher, and Sign out becomes a 44px icon button with a label. Skip link: "Skip to content". Focus: 3px `--focus` outline with a 2px offset on every element, plus a `--wall` inner ring (`box-shadow: 0 0 0 2px var(--wall)`) on painted surfaces.

### 6.1 Villages (`/`)

3 seconds: **the record says yes, the households say no.** Read order: verdict line (0–1s), painted cells (1–2s), ticket chip (2–3s).
```
 ░░░░░░░ neel wash ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 Did tap water come today?                       (wall lettering)
 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 This week, households in 2 of 2 villages on record as Har Ghar Jal reported days without water.
 Households answer one phone call each morning. Their answers are painted below, beside the state record.

 ┌─ board ───────────────────────────────────────────────────────────┐
 │ Nayapara  नयापारा                              Today [⊘ No water] │
 │ Patan block, Durg district                                        │
 │ ⚠ The record says tap water in every home. Households said no     │  verdict: --st-no ink,
 │   water on 5 of the last 7 days.                                  │  --t-lead, IconFlag
 │ ┌ register slip ────────┐╮ ┌ painted panel (wash) ──────────────┐ │
 │ ║ State record          │╯ │ Households said, last 7 days        │ │
 │ ║ Har Ghar Jal   Yes    │╮ │ Water came on 2 of 7 days (numeral) │ │
 │ ║ Gram Sabha certified No│╯│ [⊘][⊘][⊘][⊘][⊘][✓][✓] painted tally│ │
 │ ║ Demo data, simulated, │╮ │ 5 no water, 2 water came            │ │
 │ ║ as on 7 Oct           │╯ │ Phone check-ins, simulated, 3 min ago│ │
 │ └───────────────────────┘  └────────────────────────────────────┘ │
 │ [ticket] Repair ticket open: no water. Opened 2 days ago.  [Checking with households] │
 │                                               [Open village record] │
 └───────────────────────────────────────────────────────────────────┘
```
- Grid: slip 5fr, panel 7fr from 820px; stacked under that (slip first, deckled bottom edge). The tally stays one row of 7 cells, each at least 40×48 at 375px.
- `lib/verdict.ts` (pure, unit-tested). Let `heard = supplied+partial+no_supply+dirty` and `bad = no_supply+dirty`.
  - `silent` if heard is 0: "No household answers yet this week. Today's calls at 10:30 IST."
  - `gap` if `claimed_hgj && bad>0`: "The record says tap water in every home. Households said no water on {no} [and dirty water on {dirty}] of the last {days} days." (रिकॉर्ड कहता है हर घर में नल का पानी। घरों ने बताया: पिछले {days} में से {no} दिन पानी नहीं आया।)
  - `agree` if `claimed_hgj`: "Households back the record: water came on {supplied} of {days} days."
  - otherwise `plain`.
  - Boards are sorted gap, plain, silent, agree, then by `bad` descending, then by name. The hero lede counts the `gap` boards and appears only if at least one village has `claimed_hgj`.
- Empty week (the start of the demo run): seven dry-brush outlined cells and the `silent` verdict in `--st-unverified` ink.
- Remove the "बनाम / vs" divider; the verdict line and the seam do that job.

### 6.2 Village detail (`/villages/:vid`)

3 seconds: **which days water failed, and who said so.**
```
 ‹ All villages
 ░ wash (today's status) ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 Nayapara  नयापारा                                            (h1)
 Patan block, Durg district. 4 households are called daily at 10:30 IST.
 At least 2 must answer for a day to count.
 [verdict line]   [compact register slip]   [Run check-in now] [Gram Sabha brief]
 ┌ Last 14 days ───────────────────────────────── ( Strip | Table ) ┐
 │ The 7 days before  [Th][Fr][Sa][Su][Mo][Tu][We]   painted cells   │
 │ Last 7 days        [Th][Fr][Sa][Su][Mo][Tu][Today] ring on today  │
 │ legend: icon, word, meaning (one row, wraps)                      │
 │ ┌ Wed 7 Oct: No water. 3 answered, 3 said no. ──────────────────┐ │
 │ │ कमला बाई  +91XXXXXX0412  [⊘ No]  phone keypad, 10:32          │ │
 │ │ Decided by rule r1. No AI involved.                           │ │
 │ └───────────────────────────────────────────────────────────────┘ │
 └───────────────────────────────────────────────────────────────────┘
 Repair tickets (list of ticket chips)    │ aside: Context (register slips with source tags)
                                          │ Registered households (5), Operators
```
- Cell: weekday (meta), date numeral, status icon (24px), short word. Selected: 3px `--ink` outline. Today: dashed `--ink` ring and the word "Today" in place of the weekday. No data: dry-brush outline with "No calls".
- **Strip / Table** is a segmented toggle (`aria-pressed`). The table has columns Date, Status, Answered, Yes, No, Partial, Dirty, with a `<caption>`. The table is also the screen-reader route.
- The "Run check-in now" confirm and result text stay as they are (DEMO_SCRIPT quotes them).

### 6.3 Ticket (`/tickets/:tid`)

3 seconds: **it closes only when the households say water is back.**
```
 ‹ Nayapara
 ░ wash by state ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    ╭─────────────╮
 Ticket t-nyp-0007                                                    (( Verified by ))
 No water in Nayapara                                         (h1)    ((  households  ))
 [Checking with households]  Opened 8 Oct, 10:41. Updated 3 min ago.   ╰── 9 Oct ────╯  (only when closed)
 (●)Opened ──(●)Assigned ──(●)Says fixed ──(◐)Checking ──( )Verified   painted path
 ┌ board: Households confirming the repair ────────────────────────┐
 │ [✓ stamp] [ dashed ]  1 of the 2 households needed have confirmed │
 │ [Operator reports fixed]                         [Close ticket]   │
 │ A ticket closes only after households confirm by phone.           │
 └───────────────────────────────────────────────────────────────────┘
 ┌ register slip, 2px --st-no double border ═══════════════════════┐   Cedar refusal
 ║ [rule] This ticket cannot close yet              (--font-record)║
 ║ [✓][ ]  Only 1 of the 2 households needed have confirmed water. ║   reason via pickField
 ║ Why this rule: A repair counts only when the households…        ║
 ║ What happens next: Confirmation calls continue…                 ║
 ║ Cedar policy  verify-needs-quorum   Decided 10:44 IST [Dismiss] ║
 └═════════════════════════════════════════════════════════════════┘
 What happened (oldest first)
 10:41  [▣] Ticket opened                      by rule r1, after 2 households said no water
 10:43  [▣] Pump operator called               JalSakshi phone line
 10:52  [■] Operator reported fixed            Demo Nal Jal Mitra, phone keypad
 10:58  [●] Household confirmed water          कमला बाई, phone keypad          (painted)
 10:59  [▤] Close blocked by Cedar policy      verify-needs-quorum             (printed, --st-no)
 11:04  [●] Household confirmed water → Closed, confirmed by households        (painted)
```
- Timeline uses the MoJ item layout: title, byline (who and which channel), time, an optional short description and the state change. It is labelled "Oldest first". Household events get painted verdigris (or vermilion for "still no water") markers on a light wash band. System and Cedar events get flat, printed square markers.
- **Verified stamp:** a 168px oval with a double ring in `--stamp` on a `--sheet` disc. The text, in sentence case, is "Verified by households" plus the date, in `--font-record`, rotated -4°, over the `supplied` decor halo. All five progress steps are painted verdigris.
- The refusal is the system speaking: printed, never painted, `role="alert"`, focus moved to its title.

### 6.4 Gram Sabha brief (`/villages/:vid/brief`)

3 seconds: **a printed sheet the Gram Sabha can read, with sources.**
```
 ‹ Village record
 ░ wash ░ Gram Sabha evidence sheet (h1)
 For reading out at the Gram Sabha before it decides on Har Ghar Jal certification.
 [From][To][Make the sheet again]                                        [Print]
 Written by the AI agent (Amazon Bedrock, <model>); every number was checked against the data.  9 Oct, 11:20
 ┌ Key numbers (English mode only; built from brief.numbers) ────────────────┐
 │ Households reported water on 4 of 14 days. No water on 8. 1 ticket opened,  │
 │ 1 closed after households confirmed. [table: label | value]                 │
 └─────────────────────────────────────────────────────────────────────────────┘
 Printed in Hindi for the Gram Sabha.            (English mode note, --ink-2)
 ┌ register sheet: Tiro Devanagari Hindi, ruled, red margin, lang="hi" ───────┐
 │ ग्राम सभा साक्ष्य पत्र … (markdown_hi)                                       │
 │ स्रोत / Sources: source tags with freshness (footnote style)                │
 └─────────────────────────────────────────────────────────────────────────────┘
```
Print: only the sheet, A4 with 18mm margins, no wash or grain, ruled lines at `#999`, and a footer with village, date range, generator and "JalSakshi". Keep the template and agent wording exactly honest (DEMO_SCRIPT 4.2).

### 6.5 Phone simulator (`/simulator`)

3 seconds: **the same Hindi phone menu, driven from a keypad.** The layout stays as it is: setup | phone | transcript (stacked on phones, phone scrolled into view on call start). The violet "Simulator" stamp sits beside the h1. The phone screen always shows Hindi, unaffected by locale. Each transcript entry in English mode reads:
```
 IVR   Did tap water come today? Press 1 for yes, 2 for no, 3 if only a little came.
       Villagers hear, in Hindi: "Aaj nal mein paani aaya? …"        (lang="hi-Latn", --ink-2)
 You   Pressed 2 (No)
```
In Hindi mode the caption is Devanagari and the English line is dropped. Household labels like "no consent" become `Bilingual`. Recolour the FeaturePhone to tokens only; do not paint it.

### 6.6 Activity (`/activity`)

3 seconds: **what is happening right now, in plain sentences.** The feed is grouped by day (Today, then dates), newest first, refreshing every 5s, with a Pause/Resume button. Each row shows time (tabular), a marker, the text (`pickField`), and the village name as a link. Household-answer rows get a painted status dot. Cedar rows get a printed square in `--st-no` with the policy id in `--font-code`. New rows use `@starting-style`. A "Refreshes every 5 seconds" note is in `--t-meta`.

### 6.7 Sign-in (signed out; mock mode skips it)

3 seconds: **who this is for, and one button.** A solid `--sheet` card centred on the wall over a large `jal` decor wash, with the switcher at the top right. Contents: the mark, "JalSakshi" / "जल साक्षी", the h1 "The village tap, in its households' own words", "For Panchayat Secretaries, sarpanches and pump operators.", and **[Sign in]**. Splash, callback and error screens use the same card.

### Demo moments (must read on a 1080p recording at 50% scale)

| Shot (DEMO_SCRIPT) | What must be legible |
|---|---|
| 2.1 Villages | The verdict line, the register "Har Ghar Jal Yes" beside the painted cells, and the Demo data strip. Optionally flip to हिन्दी for about 1s and back to show both languages work. |
| 2.4 Village detail | Today's cell "Today / None" in vermilion, and "Decided by rule r1. No AI involved." |
| 2.6 Ticket | The progress path at "Checking" and the board "1 of the 2 households needed…". |
| 3.2 Cedar deny | The printed refusal slip with its title, the 1-of-2 stamps and `verify-needs-quorum`. |
| 4.1 Closed | The stamp lands, the five painted steps, and the CLOSED_VERIFIED badge "Closed, confirmed by households". |
| 4.2 Brief | The "Written by the AI agent (Amazon Bedrock…)" line, the Hindi sheet, and the sources. |

English button names are unchanged ("Run check-in now", "Open village record", "Close ticket", "Gram Sabha brief", "Print", "Start call"). DEMO_SCRIPT's "Hindi / English" button pairs now appear in English by default; tell the script owner.

## 7. Component inventory

| File | Action |
|---|---|
| `styles/global.css` | New tokens (§2), type scale, `.paint`, `.slip`, `.board`, `.dry` (empty outline), `.wall-lettering` (replaces `.painted`), focus, `:lang(hi)` rules; drop the `.bi-*` stack |
| `styles/watercolour.css` | **Add** (§4) |
| `i18n/locale.tsx`, `i18n/messages.ts` | **Add** (§5) |
| `components/Wash.tsx` | **Add** (§4) |
| `components/RegisterSlip.tsx` | **Add**: state-record slip (`compact` prop for village detail), deckled seam |
| `components/Verdict.tsx` + `lib/verdict.ts` | **Add** (§6.1) |
| `lib/places.ts` | **Add**: `romanVillage`, `romanPlace` (§5) |
| `components/Bi.tsx` | Rewrite to single language |
| `components/Layout.tsx` | Wordmark, LanguageSwitcher, live region, Demo strip copy, icon sign-out on phones |
| `StatusChip`, `TallyTiles`, `StatusStrip` | Painted cells, English labels and shorts, Strip/Table toggle, patterns |
| `SourceBadge` | Printed tag: register paper, one language. Simulated and replay keep the dashed hatched edge. Text such as "Phone check-ins, simulated, 3 min ago" |
| `PolicyDenial` | Printed refusal slip (§6.3) |
| `TicketParts` | Painted progress path, oval VerifiedStamp with the landing motion, stamp-slot Confirmations |
| `Timeline` | MoJ layout, paint vs print markers, "Oldest first" |
| `PageState` | Empty = dry-brush outline + a next action; errors say what failed and how to retry |
| `Markdown`, `BriefPage` | Register sheet in `--font-record`, English key-numbers panel, print CSS |
| `FeaturePhone`, `Icons` | Token recolour only; reuse IconFlag (verdict), IconRule (Cedar), IconCheck (stamp) |
| `index.html`, `main.tsx`, `web/README.md` | `lang="en"`, fonts, provider; README line "English by default, Hindi via the switcher or `?lang=hi`" |
| `tests/` | Add `i18n.test.ts` (no window gives en; `?lang=hi` gives hi; a stored `xx` gives en), `verdict` and `places` cases in `lib.test.ts` |

## 8. Dependencies

- **Add:** `@fontsource-variable/anek-latin@5.3.0` (OFL-1.1). This is the only new package.
- **Keep:** `@fontsource-variable/anek-devanagari@^5.3.0` (import `wght.css`), `@fontsource/tiro-devanagari-hindi@^5.3.0` (import `400.css`).
- **Rejected:**
  - i18next and react-i18next: about +24 KB gzip and a full key rewrite; `Bi` plus context does the job.
  - motion: CSS covers three moments.
  - rough-notation and roughjs: unmaintained, and sketchy marks undercut precision.
  - p5.brush: heavy runtime.
  - mixbox: non-commercial licence.
  - Fraunces with cream: the stock generated look.
  - Atkinson Hyperlegible: legible, but it breaks the one-family Latin and Devanagari pairing.

## 9. Done when

- [ ] English loads by default; `?lang=hi` and the switcher give Hindi; the choice survives a reload and a route change; `<html lang>` matches; no stacked bilingual text remains in English mode beyond §5's list.
- [ ] Every status shows icon + word + colour; Not confirmed is hatched and Dirty is stippled; the strips have a table view.
- [ ] axe passes with no violations on all seven pages in both languages at 375px and 1280px; focus is visible on wall, sheet, slip and paint.
- [ ] No horizontal scroll at 375px; touch targets are at least 44px; the 7-cell row fits.
- [ ] Washes are absent in print, forced colours and high contrast; nothing animates under reduced motion.
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build:mock` pass; `api/types.ts` and the mock are untouched; the bundle is at or under 140 KB gzip.
- [ ] The Demo data strip, Simulated tags and source tags with freshness are visible on every page that shows numbers.

## 10. As built (deviations from this spec)

Recorded when the spec was implemented in `web/`; everything else follows the sections above.

- **English never loads Anek Devanagari.** `--font-ui` drops `'Anek Devanagari Variable'` unless `<html data-locale="hi">`; the few Devanagari names in English mode use the system face (Nirmala UI, Kohinoor, Noto). The Hindi switch warms the font first (`preloadHindiFont`).
- **Washes fill their box.** `<Wash>` gained `fit` (`stretch` by default, `slice` for the stamp halo and the sign-in backdrop), `bleed` (runs past the box, more up than down) and a wider base for `under-text` (radius 0.44 of the box, decor stays 0.36), so a panel reads as painted rather than as a blot in one corner. The noise filters now pin `x/y/width/height` so the mask tiles are seamless.
- **One extra token:** `--register-2: #F2EAD6`, the hatch stripe on simulated or replayed source tags (`--ink-2` on it is 6.9:1).
- **Refusal slip** uses the red double border only, without the red margin lines (four red rules side by side read as noise).
- **Chips** (one line of icon + word) carry no hatch or stipple; patterns appear on the tally cells, the 14-day strip and the legend swatches, where they sit on the icon band.
- **Phone screen** keeps its small English line under each Hindi prompt in both languages (it is the same in either mode, as §6.5 asks).
- **Ticket timeline:** the channel ("phone keypad") moved from the detail chips into the byline; `lib/events.ts` detail values are `Bilingual`.
- **Activity markers:** `ActivityItem` has no status field, so `lib/activity.ts` reads the status (and a Cedar policy id) from the row's English text for the marker only; the row's own words still say it.
- **Brief in Hindi mode** shows the numbers table in a collapsed "पत्र में इस्तेमाल हुए आँकड़े" instead of the English key-numbers panel.
- **`Bi`** falls back to the other language when one side of a pair is empty.
- **Not done here:** `docs/DEMO_SCRIPT.md` still quotes the old Hindi-first button pairs; its owner should switch them to the English names above.

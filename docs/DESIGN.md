# JalSakshi console: v5 changes (current, on top of v4 below)

The user: *"in website let it be english all by default"*, *"its upto sarpanch and secretary to choose language which they want [for calls]"*, *"we will provide the admin/sarpanch access manually"*, *"photo of register names will be good too, area where the issue is so location and all matters"*.

- **English only.** No language toggle and no Hindi UI strings in the console; pages use plain strings via `lib/text.ts` (`defineMessages`, `msgFn`). The residents' page `/v/:id` (for villagers) and the printed poster stay bilingual/Hindi; `i18n/locale.tsx` now serves only `/v/:id`.
- **Sign-in:** [Sign in] only + "Your login is given by the JalSakshi team." Public sign-up is off.
- **More → Set up a Panchayat** (admins only, `POST /api/admin/panchayats`): village (search or type), call languages (checkboxes from `GET /api/languages`, "Ready" vs "Needs recordings and translation", first = default, "Make default"), pump operator, sarpanch and secretary (optional), username + optional password. Success shows username + temporary password with [Copy login details].
- **More → Settings** (`POST /api/villages/{vid}/settings`): call languages (same picker; "Families can choose their language on their first call") and the daily call time (09:00-21:00).
- **Families → Add families:** three tabs. *Paste numbers*; *Photo of a register* (resized in the browser to 1600 px, JPEG 0.8, `POST …/register-photo`; an editable review list of name / mobile / area with an Add tick, bad numbers start unticked and are never sent; [Add N families] → `households/bulk` with `families[]`); *Missed call* (080 6426 0325, families say their name and mohalla on the first call; link to the poster).
- **Area everywhere:** Families grouped by area with an Area filter; each row shows name (or "Name not given"), last four digits, language, water source. Complaints list, complaint detail and Home's open complaints show the reporting families' area(s) ("Area not given" when unknown).

# JalSakshi console: v4 "simple" (current)

**This section supersedes everything below it** (the v3 spec is kept only as history). The user: *"make it all real and simple, it's for the Gram Panchayat person: first-time login and onboarding, getting families' numbers in, simple calls, simple tabs, simple info, a summary of complaints and what to do here. No icons; simplicity and working matter most."*

- **Look:** the same warm cream tokens (`styles/tokens.css`) and Inter; plain global classes in `styles/app.css`. **No icons anywhere** (lucide-react removed); text labels only.
- **Sign-in:** product name, one sentence, [Sign in] [Create account] (Cognito Hosted UI `/signup`, same PKCE query as `/login`), language toggle.
- **First login (`/setup`, when `/api/me` says `needs_setup`):** "Step N of 3" — (1) your village: search `/api/places` or "My village is not in the list" (name, GP, block, district); (2) who fixes water problems: pump operator (required), sarpanch (optional) → `POST /api/villages`; (3) add families: paste numbers → `POST …/households/bulk` (added / skipped with reason), or print the missed-call poster (080 6426 0325). [Finish] → Home.
- **Shell:** top bar (village name; a switcher only with more than one village; EN|हिन्दी) and four text tabs **Home · Complaints · Families · More** (bottom on phones, top on desktop). No sidebar.
- **Home:** Today's water (one line per source + "N of M families answered"), Complaints (Open · Being fixed · Closed this week + up to 5 open), What to do now (≤ 3 sentences, one button each), a day-one card until the first answers arrive, and [Call families now] (confirm dialog explains the 9 am–9 pm calling window).
- **Complaints:** Open | Closed rows; detail = problem, place, who reported, status in words, a plain timeline, [Pump operator says it's fixed], [Close complaint] (a refusal is shown as one sentence). [Raise a complaint] = pick family + problem.
- **Families:** "Agreed N · Waiting for their call N · Said no N", [Add families] (same paste box), rows (last four digits, status word, water source), "Download consent record (CSV)".
- **More:** Water sources · Team · Announcements · Reports (weekly summary + printable Gram Sabha sheet) · Missed-call poster · Residents' page · Help · Sign out; admins also get All villages and Test call.
- **Honesty, quietly:** no per-number badges or Demo/Simulated tags. One small grey line per section says where numbers come from and when they were updated. A village whose id starts with `sample-` shows one banner on every page: "Sample village — example data to show how JalSakshi works." (CLAUDE.md requires example data to be labelled.) The residents' page `/v/:id` follows the same rules.
- **Removed:** Activity page, long Guide, multi-step setup checklist, Settings page (now More → Team), source badges, Demo tags.
- **Mock mode:** default user is an admin who sees the sample village (30 days of history, 5 complaints); `?as=new` is a fresh account that goes through setup; `?as=sarpanch` can approve announcements.
- **Budget:** main bundle ≤ 140 KB gzip (about 95 KB now); every page except Home, Complaints and Families is lazy.

---

# JalSakshi console: design spec (v3, clean SaaS)

This is the build contract for the console redesign (`web/`). It **replaces** the "Limewash & Register" watercolour spec entirely (deleted, §10). The user's verdict on v2: *"make it simple, not government like, like SaaS; onboarding guide and UI are non-intuitive; let's do the real loop."*

**Unchanged:** `web/src/api/*` (types, client, mock), Cognito sign-in, English default with a Hindi switch, and the honesty rules (source and freshness on every number, test data labelled, government records never merged with families' answers). No secrets and no real phone numbers in code, mocks, docs or screenshots.

## 0. Decision

| (1–10) | A: Linear inbox | B: Guided setup | C: Mobile-first workspace |
|---|---|---|---|
| Fixes the complaint (simple, SaaS, intuitive) | 7 | 8 | **9** |
| Onboarding | 8 | **9** | 7 |
| Mobile (360px, cheap Android) | 8 | 7 | **9** |
| Buildable in about 6 h on this codebase | 5 | 6 | **8** |
| Honesty rules kept | 8 | **9** | **9** |
| Accessibility | 8 | 8 | **9** |
| **Total** | 44 | 47 | **51** |

- **A** has the best attention rules and token rigour, but Ctrl K, j/k shortcuts, a split pane, a "+ New" FAB and an icon rail are power-user tools a Panchayat secretary will not use, and cost about 2 h. 13px text floor; government-vs-families leaves Home.
- **B** has the best onboarding: steps tick themselves, setup *is* the real loop, a "Waiting for the first answer…" state, plain error mapping, help on every page. But Home leads with four stat cards (a dashboard, not a to-do list), role detection touches auth, "Check village details" is a step with nothing to do, and the mobile spec is thin.
- **C wins.** One primary action per screen, no exotic widgets, 16px text on phones, AWS visible in Settings › About, bundle-aware. Weak spots fixed here: its checklist ended with "close a complaint" (cannot be done on demand), merged "name sources" with "assign operator" (fails with no operator), and duplicated Settings in a `/share` page.

**Synthesis:** C's shell, page skeletons and type floor; B's onboarding mechanics (self-completing steps, waiting state, error mapping, contextual help, test calls only in demo villages); A's attention rules engine, checklist rules (with an honest "needs support" state), complaint routes under the village, and the Cedar callout with its policy id. **Dropped:** command bar, shortcuts, split pane, FAB / "+ New" menu, tablet rail, role detection, `/share`, stat-first Home.

## 1. Principles

1. **One question and one primary action per screen.** Home answers *"Did water come today, and what needs me?"*. Every other page has an H1, a one-sentence description and one primary button.
2. **Plain words, never system words** (§8): "Complaint #7", not "ticket t-nyp-0007"; "Families needed to confirm: 2", not "quorum".
3. **The product teaches itself:** a setup checklist computed from live data, empty states that say what to do next, a "?" on every page linking to the guide. No coach-mark overlays.
4. **Setup is the real loop:** add families → they press 1 → call them → first answer → complaints close only when families confirm. Onboarding a village and demoing the product are the same walk-through.
5. **Quiet honesty, never hidden:** a one-line source footnote with an (i) popover on every number; a visible violet tag on test, replay and demo data; the government record in its own grey card beside families' answers; Cedar refusals that explain the rule; AI output labelled as AI.
6. **Phone first:** 360px, cheap Android, 3G. 44px targets (48px for primary actions), 16px body, no sideways scroll, skeletons, a light bundle. A laptop gets a wider version of the same screens.
7. **Warm surfaces, one accent:** warm-white cards on a sand page, one deep water-teal accent, 1px warm borders, standard `lucide-react` icons, no decoration. Colour carries status only.
8. **UI logic that decides anything is pure and tested** (`lib/setup.ts`, `lib/attention.ts`). The UI never decides a water status; it shows what the API returns.

## 2. Information architecture and routes

The console works on one village at a time; the last one used is kept in localStorage `jalsakshi.village` (try/catch). Tabs are `?tab=` values and sheets open from query flags, so the Android back button closes them and every view has a link.

| Path | Page | Chrome | Package |
|---|---|---|---|
| `/` | Redirect: last village if it still exists → the only non-inbound village → `/villages` | – | WP0 |
| `/villages` | All villages (block officials) | app | WP7 |
| `/villages/:vid` | **Home ("Today")** | app | WP1 |
| `/villages/:vid/complaints` | Complaints · `?status=open\|checking\|closed\|all` · `?source=<wpid>` · `?new=1[&family=<hid>]` | app | WP2 |
| `/villages/:vid/complaints/:tid` | Complaint detail | app | WP2 |
| `/villages/:vid/families` | Families · `?tab=consent` · `?add=1` · `?filter=waiting\|agreed\|stopped` · `?family=<hid>` | app | WP3 |
| `/villages/:vid/sources` | Water sources · `?tab=tests` · `?add=1` · `?source=<wpid>` · `?test=<wpid>` | app | WP4 |
| `/villages/:vid/announcements` | Announcements · `?new=1` | app | WP5 |
| `/villages/:vid/reports` | Reports · `?tab=overview\|weekly\|sheet` · `?days=7\|30` | app | WP5 |
| `/villages/:vid/activity` | Activity · `?all=1` (every village) | app | WP7 |
| `/villages/:vid/settings` | Settings (anchor sections) | app | WP6 |
| `/villages/:vid/setup` | Setup flow | focus, no nav | WP1 |
| `/villages/:vid/poster` | Missed-call poster (A4) | print, no shell | WP6 |
| `/guide` | Getting-started guide (sidebar uses the last village) | app | WP1 |
| `/test-call` | Test call (was the simulator) · `?vid=&hid=&purpose=` | app | WP7 |
| `/v/:villageId` | Residents' page (no login) | public | WP6 |
| auth callback, `*` | Unchanged / Not found | – | WP0 |

**Legacy redirects** (`lib/routes.ts`, unit-tested), so DEMO_SCRIPT and activity links keep working: `/villages/:vid?tab=` `overview` → Home, `complaints` → `/complaints`, `points` → `/sources`, `families` → `/families`, `consent` → `/families?tab=consent`, `announcements` → `/announcements`, `quality` → `/sources?tab=tests`, `analytics` → `/reports`; `/villages/:vid/brief` → `/reports?tab=sheet`; `/simulator` → `/test-call`; `/activity` → `/villages/{last}/activity`; `/tickets/:tid` → `TicketRedirect` fetches the ticket and replaces the URL with `/villages/{village_id}/complaints/{tid}` (Not found on 404).

**Where the old 8-tab village page went:** Overview → Home (today and what needs attention) plus Reports (14-day history, context, full government-vs-families). Complaints tab and ticket page → Complaints (list + detail page). Water points + Water quality → Water sources (tabs *Sources | Water tests*). Families + Consent ledger → Families (tabs *Families | Consent record*). Analytics + Brief + weekly summary → Reports (3 tabs). Villages home → village switcher + `/villages`. Simulator → Test call, under Tools.

## 3. App shell (`web/src/shell/`)

**Breakpoints:** below 1024px, top bar + bottom tabs (phone and tablet); 1024px and up, fixed sidebar; 1280px and up, Home gets a right rail. Content max 1200px, forms max 640px. Gutter 16px, 24px from 640px, 32px from 1024px.

**Sidebar (desktop):** 248px, `--surface`, 1px right `--border`. Top to bottom:
1. Brand row (56px): droplet-check mark in `--accent`, "JalSakshi" 16/600.
2. **VillageSwitcher** (48px button): village name in the current locale, "Patan · Durg" subline (14px), a Demo tag for demo villages, a chevron. A menu button opening a listbox of villages from `listVillages` (excluding `inbound`), each with a today StatusPill dot and Demo tag; a search field when there are more than 6; "All villages" → `/villages` at the end. Switching keeps the section (`/villages/A/complaints/x` → `/villages/B/complaints`). With one village it is a plain label.
3. Primary nav (40px items, 20px icons): Home · Complaints [open count] · Families [count waiting for their call] · Water sources [amber dot if any provisional] · Announcements [waiting + ready count] · Reports.
4. Group "Tools": Activity · Test call [Demo tag] · Residents' page ↗ (new tab, `/v/:vid`).
5. Pinned at the bottom: Getting started [ProgressRing "3/6"] (becomes "Help & guide" at 6/6) · Settings · LanguageToggle (segmented `English | हिन्दी`) · user row (initial avatar, name; menu: Help & guide, Sign out; mock mode shows "Demo user" with no sign-out).

**Phone and tablet:**
- **TopBar** (56px, sticky, `--surface`, bottom border): VillageSwitcher (name, ▾, Demo tag) · spacer · LanguageToggle (one 44×44 button showing the *target* language, "हिन्दी" / "English"; accessible name "Switch to Hindi" / "अंग्रेज़ी में देखें") · help IconButton → `/guide` · avatar menu.
- **BottomTabs** (64px + `env(safe-area-inset-bottom)`): Home · Complaints [badge] · Families [badge] · Announce [badge] · More. 12px labels, at most 10 characters in both languages (होम, शिकायतें, परिवार, घोषणा, और). `aria-current="page"` on the active tab.
- **MoreSheet** (bottom Sheet): Water sources, Reports, Activity, Test call, Residents' page ↗, Print poster, Getting started 3/6, Settings, Help & guide, Sign out.

**Common parts:**
- **DemoBanner** when `isMock` or `isDemoVillage(village)` (`lib/demo.ts`: `/\(डेमो\)|\(demo\)/i`): a 36px band in `--demo-tint` / `--demo` under the top bar (phone) or above the page header (desktop). "Demo village: sample families. Answers are labelled Test data." + "What's real?" → `/guide#real`. Not dismissible.
- **PageHeader:** H1 (`tabIndex=-1`, focused after each route change), a one-sentence description in `--text-2`, a "?" IconButton → `/guide#<helpId>`, an actions slot (desktop: primary on the right, secondaries to its left; phone: primary is a full-width 48px button under the description), optional Tabs row.
- Skip link "Skip to content" → `<main id="main">`. **Toaster** bottom-right (desktop), bottom-centre above the tabs (phone).
- **`VillageData` provider** (`shell/VillageData.tsx`, wraps every `/villages/:vid/*` route) so the shell, Home and pages share one fetch:

```ts
interface VillageData {
  vid: string;
  detail: AsyncState<VillageDetail>;      // getVillage
  tickets: AsyncState<Ticket[]>;          // listTickets({ village_id })
  days: AsyncState<DayStatus[]>;          // getDays(today-13, today)
  broadcasts: AsyncState<BroadcastList>;  // listBroadcasts (after first paint)
  summary: VillageSummary | undefined;    // this village's row from useVillages()
  reload(part?: 'detail' | 'tickets' | 'days' | 'broadcasts'): void;
  boost(ms?: number): void;               // poll detail+tickets+days every 5 s for ms (default 180 000)
}
```
Polling uses the existing `usePolling` (pauses while the tab is hidden): tickets and days every 30 s, detail every 60 s. `boost()` runs after Call families now, Add family, Operator says it's fixed and Send. `useVillages()` loads `listVillages` once per session and again when the switcher opens.

## 4. Onboarding

### 4.1 One source of truth: `lib/setup.ts` (pure, no strings)

```ts
export type StepId = 'sources' | 'operators' | 'families' | 'consent' | 'answers' | 'residents';
export interface SetupStep { id: StepId; state: 'done' | 'todo' | 'blocked'; progress?: { n: number; of: number } }
export function setupProgress(i: { village: Village; households: HouseholdMasked[]; operators: Operator[];
  points: WaterPoint[]; days: DayStatus[]; tickets: Ticket[] }): SetupStep[]
```

`active` = `points.filter(p => p.active)`; `q` = `village.quorum`.

| # | Step | Done when (existing API data only) | Progress |
|---|---|---|---|
| 1 | `sources` | `active.length ≥ 1` and no active point is `provisional` | named / active |
| 2 | `operators` | `active.length ≥ 1` and every active point has `operator_ids.length ≥ 1`, **or** an operator has role `NAL_JAL_MITRA` and this vid in `village_ids` (the §15.1 routing fallback). `blocked` when `operators.length === 0` | assigned / active |
| 3 | `families` | ≥ `q` households that are `active` with `effectiveConsent` not DECLINED or WITHDRAWN | n / q |
| 4 | `consent` | ≥ `q` households pass `isCallable` | n / q |
| 5 | `answers` | a day in the last 14 has `counts.answered > 0` | – |
| 6 | `residents` | a household has `registered_via === 'ivr'`, or a ticket has `origin` `report` or `voice_note` | – |

Only per-viewer conveniences live in localStorage (try/catch): `jalsakshi.setup.hidden.<vid>`, `.seen.<vid>`, `.celebrated.<vid>`. They never mark a step done. A `blocked` step never blocks later steps. Tests cover: quorum larger than the household count, pre-v2 households (only `consent` set), an operator only through the NAL_JAL_MITRA fallback, zero water points.

### 4.2 Step copy (`i18n/messages/onboarding.ts`)

| Step | Title | Why line | Status examples | CTA → deep link |
|---|---|---|---|---|
| 1 | Name your water sources | Complaints and daily answers are counted per source. | "1 new source needs a name" / "3 sources ready" | [Review sources] → `/sources?source=<first provisional>` |
| 2 | Choose who fixes each source | Each complaint goes straight to that person by phone. | "2 of 3 sources have someone"; blocked: "Needs the JalSakshi team: add your pump operator" | [Assign people] → `/sources?source=<first unassigned>` |
| 3 | Add families | A day counts only when at least {q} families answer. | "1 of 2 added" | [Add a family] → `/families?add=1` |
| 4 | Families agree to calls | Nobody is called about water until they press 1 to agree. | "1 of 2 agreed · 1 waiting for their call" | [See who's waiting] → `/families?filter=waiting` |
| 5 | Get your first answers | This is the call families get every day at {time}. | "Next call: today at 10:30" | `CallFamiliesButton` |
| 6 | Tell residents about the missed-call number | Anyone can report a problem with a free missed call. | "No missed calls yet" | [Print the poster] → `/villages/:vid/poster` |

### 4.3 Persistent checklist (`features/onboarding/SetupChecklist.tsx`, variants `card | page`)

- **Home card** (until 6/6, unless hidden): header "Get {village} ready", "3 of 6 done", ProgressBar. The first step not done is expanded (title, why, status, primary CTA, and in demo villages a secondary [Try it with a test call]). Other steps are 44px link rows with a green check, an empty circle or an amber "Needs support" tag. Footer: "Open setup" · "Hide". On phones it starts collapsed (title, bar, next step and CTA, "See all steps").
- **Sidebar / More sheet:** "Getting started n/6" → `/villages/:vid/setup`.
- **At 6/6:** a one-time toast "{village} is ready." (`celebrated` flag); the card goes and the nav item becomes "Help & guide".

### 4.4 Setup flow (`/villages/:vid/setup`)

Focus layout, no sidebar. Top bar: mark, "Set up {village}", "Step 2 of 5" dots, "Exit setup". Content max 640px. Sticky footer: [Back] ghost, [Continue] primary (always enabled; while the step is not done a line says "You can finish this later from Getting started."). **Opens on its own** on the first visit to the village's Home when `sources` and `families` are both not done and the `seen` flag is unset (set when shown).

0. **Welcome.** "Let's get {village} ready" · "Five short steps, about 10 minutes" · LanguageToggle. Three numbered rows with icons: *Families answer one short Hindi call a day, or give a missed call.* → *Problems become numbered complaints sent to whoever fixes that source.* → *A complaint closes only when the families say water is back.* [Start] · link "I'll do it later".
1. **Water sources and who fixes them** (steps 1–2). One row per active point; provisional or unassigned rows expand into `SourceForm fields="name-and-operator"` (WP4); done rows collapse with a check. [+ Add another source]. With no operators, a Callout: "Nobody is set up to fix things yet. Ask the JalSakshi team to add your pump operator."
2. **Families** (step 3). "Add at least {q} families so a day's answers count." `AddFamilyForm compact` (WP3), repeatable; added families listed below with a live ConsentPill.
3. **Agreement** (step 4). Live list, "1 of 2 agreed". Polls every 5 s while any household is NONE (up to 3 min after the last add), then 30 s. After 3 min with no change: "No answer yet? Calls go out only 9 am–9 pm, and test setups call only numbers on the allowed list. See Activity." Demo villages only: [Try the consent call on a test phone] → `/test-call?vid=&hid=&purpose=REGISTER`. Never blocks.
4. **First answers** (step 5). `CallFamiliesButton` + "Or wait for the automatic call at {time}." After a start, **WaitingForAnswers**: LivePulse "Waiting for the first answer…" and this village's activity lines streaming in (`getActivity` every 5 s for up to 5 min); it turns to a check when `answers` is done.
5. **Residents** (step 6). Poster thumbnail, the missed-call number, [Print the poster], "Open residents' page ↗".

**Done:** "{village} is ready. Families are called every day at {time}. Problems show up in Complaints and close only when families confirm." [Go to Home] · "Read the guide".

### 4.5 Getting-started guide (`/guide`, `features/onboarding/GuidePage.tsx`)

One page in the current language: sticky table of contents on desktop, native `<details>` accordions on phones. Each section ends with one CTA. Anchor ids are fixed (PageHeader "?" links to them).

| Anchor | Section | Content |
|---|---|---|
| `#how` | How it works in 60 seconds | 4-step ordered list with icons (not an image): family answers or gives a missed call → complaint goes to whoever fixes that source → they fix it and press 1 → families confirm by phone, then it closes |
| `#daily` | Your 2-minute daily routine | Open Home, clear "Needs your attention", check complaints waiting over 2 days |
| `#complaints` | How a complaint closes | The 5 states; why it cannot close early (shows the real refusal callout); who presses what |
| `#families` | Adding families and their agreement | Only by pressing 1 on a short Hindi call, nobody agrees for them; calls 9 am–9 pm, once a day; press 9 to stop; test setups call only allowed numbers |
| `#residents` | What residents can do | Keypad table: 1 no water · 2 dirty water · 3 speak a problem · 4 hear today's status · 9 stop calls. Missed calls are free |
| `#announcements` | Announcements | Draft → sarpanch approves → send; at most 2 a week; calls 9–9 |
| `#roles` | Who does what | Secretary: daily work, families. Sarpanch: approves announcements, Monday summary call. Pump operator: a call per complaint, 1 when fixed or 2–5 to say why not. Block official: Reports, All villages |
| `#numbers` | Reading the numbers | Source footnote, Test data, Not enough answers, Government record, AI transcription, "Decided by the counting rule, not by AI" |
| `#real` | What's real here | Demo villages and test data, PHED escalation (simulated), acted roles, the real village (Kutelabhatha) |
| `#faq` | Common questions | Why can't I close a complaint? Why didn't a family get a call? What happens when someone presses 9? Is government data mixed with families' answers? (No.) What does the AI do? (Writes down voice notes and the sheet's prose; the counting rule decides everything else.) |

**Contextual help:** every PageHeader "?" → its guide section; empty states carry "How does this work?"; policy callouts carry "Why?" → `#complaints` or `#announcements`.

### 4.6 The real loop

In the real village, steps 3–5 *are* the pilot: Add family → consent call → "Agreed" (live) → Call families now → first answer → Water today updates → complaint → operator → families confirm → closed.
- The two pilot numbers the user supplied go in **only** through the Add family sheet in the right village, or `.env` (`PILOT_FAMILIES` / `TEST_NUMBERS`) plus the SSM allowlist. Never into code, mocks, docs, commits or screenshots. Team phones belong only in "(डेमो)" villages (ARCHITECTURE §15.13). The console shows only the last 4 digits.
- Failures the UI must name, not hide: outside calling hours; a number not on the allowed list (the time-based hint in §4.4); `409 no_households` → "No family has agreed yet. Finish 'Families agree to calls' first."; `503 not_configured` → "Phone calls aren't switched on in this setup."; a Cedar 403 → PolicyCallout.

## 5. Screens

**Every page:** reads `useVillageData()` where it can; each card has a matching Skeleton (no layout shift) and fails on its own with `ErrorState` ("Couldn't load {thing}. Check your connection and try again." [Try again]); lists are `ListRow` cards below 1024px and `DataTable` at 1024px and up; mutations end in a Toast plus `reload()` or `boost()`.

### 5.1 Home "Today" (`/villages/:vid`, WP1)

**Data:** provider (detail, tickets, days, broadcasts, summary). After first paint: `getAnalytics(vid, today-6, today)`; `getActivity(since now-24h)` filtered to the vid, polled 30 s; `getPublicVillage(vid)` for `missed_call_number`.

**Layout:** at 1280px+, a 12-column grid with blocks 3–4 in the main column (8) and 5–8 in a sticky rail (4). At 1024–1279px, one column with 5–8 in a 2-column grid. Phones: one column in this order.

1. **PageHeader.** H1 "Today". Description "Thu 9 Oct · families are called at 10:30 · 3 sources · 12 families". Actions: secondary `CallFamiliesButton`, primary [Raise a complaint] → `/complaints?new=1` (hidden until setup step 3 is done; until then the checklist is the primary). While boosted: LivePulse chip "Calls in progress".
2. **SetupChecklist** card (§4.3).
3. **Water today** (hero card).
   - Summary sentence (18/600) with the worst StatusPill: "No water at 1 of 3 sources" / "Water came at all 3 sources"; before the call time with no answers, "Calls go out at 10:30. Answers appear here."; an hour after, "No answers yet today".
   - One 56px row per active source: KindIcon in a 40px tinted circle; name; 14px meta (hamlet · "4 of 5 families answered"); DayDots for 7 days (desktop only); StatusPill on the right. Households with no source get a row "Families with no source set". A row opens `/sources?source=<wpid>`.
   - Footer: SourceNote ("Families' phone answers", freshness from `summary.observed_7d.source`; popover rule "Decided by the counting rule (r2), not by AI. A day counts when at least {q} families answer.").
   - Phone, no answers today: a full-width ghost `CallFamiliesButton` inside the card.
   - Empty: "No water sources yet." · "Add the tap, handpump or tanker families use." [Add a water source] → `/sources?add=1`.
4. **Needs your attention.** The first 6 of `attentionItems()`, then "and N more" → Complaints. Row: severity icon, sentence (16/500), 14px meta ("#7 · Main tank · 2 days"), inline small action; on phones the whole row is the link. Empty: check icon, "All clear. Nothing needs you right now." · "Next calls: tomorrow at 10:30."
5. **This week** (2×2 Stat): "Water came · 5 of 7 days" · "Complaints fixed · 2 · usually 18 h" · "Families answering · 10 of 12" · "Announcements · 1 of 2 sent". Footer: SourceNote(`analytics.source`), "Full report" → Reports.
6. **GovVsFamiliesCard** (compact). Hidden when `detail.official` is null.
7. **Recent activity:** 5 rows (3 on phones), tabular time + sentence (`pickField`), "View all".
8. **Share with residents:** missed-call number (24/600 tabular) or "Missed-call number coming soon"; secondary [Print poster]; "Open residents' page ↗".

**`lib/attention.ts`** (pure; sorted danger → warning → info, then oldest first):

```ts
attentionItems(i: { tickets: Ticket[]; households: HouseholdMasked[]; points: WaterPoint[]; broadcasts?: Broadcast[];
  dirtyWithoutTest?: string[] /* wpids from analytics.points[].dirty_without_test */; today?: DayStatus | null;
  checkinTime: string; now: Date }): AttentionItem[]   // {kind, severity, ticketId?, pointId?, broadcastId?, n?, ageHours?}
```

| Kind | Severity | When | Example copy | Action |
|---|---|---|---|---|
| `reopened` | danger | REOPENED | "#7 was reopened: no water at Main tank" | [Open] |
| `escalated` | danger | ESCALATED | "#5 was sent to PHED (simulated) after 2 days without a fix" | [Open] |
| `waiting` | warning | OPEN/ASSIGNED, opened more than 48 h ago | "#5 has waited 3 days. Operator says: parts needed." | [Open] |
| `test_needed` | warning | open DIRTY complaint whose point is in `dirtyWithoutTest` | "Test the water at School handpump (complaint #8)" | [Record a test] → `/sources?tab=tests&test=<wpid>` |
| `approval` | warning | DRAFT announcements | "1 announcement is waiting for the sarpanch" | [Review] |
| `ready_to_send` | warning | APPROVED, not sent | "Ready to send: boil water notice" | [Send] |
| `no_answers` | warning | ≥ 60 min past call time, inside 9–21 IST, `today.counts.answered === 0`, ≥ 1 callable household | "No family has answered today's call yet" | `CallFamiliesButton` |
| `new` | info | OPEN/ASSIGNED, opened 48 h ago or less | "New complaint #8: dirty water at School handpump" | [Open] |
| `checking` | info | OPERATOR_REPORTED_FIXED or VERIFYING | "Operator says #6 is fixed. Families are being asked." | [View] |
| `unnamed_source` | info | active provisional points | "Give the new source a name" | [Name it] |
| `families_waiting` | info | active households with consent NONE | "3 families haven't agreed to calls yet" | [View] |

### 5.2 Complaints (`/villages/:vid/complaints`, WP2)

- **PageHeader** "Complaints" · "Every problem families reported, and who is fixing it." · primary [Raise a complaint] (Sheet, `?new=1`).
- **Toolbar:** SegmentedControl Open (n) · Being checked (n) (= OPERATOR_REPORTED_FIXED or VERIFYING) · Closed (n) · All; a "Source" Select. Sorted with `sortRegister`.
- **Rows.** 1024px+: table # · Problem (icon + reason) · Water source · Families · Open for · Status (TicketStatePill) · Blocker (amber text); the whole row is a link. Phones: ListRow, line 1 "#7 No water" + pill, line 2 "Main tank · 2 days · 3 families", a blocker chip, an "AI note" tag when `issue` is set. Footer: SourceNote "Complaint register · live".
- **Empty:** "No open complaints." · "When a family gives a missed call or the daily call finds a problem, it shows up here." + secondary [Print the missed-call poster]. Filtered: "Nothing matches this filter." [Clear filter].
- **Raise a complaint (Sheet):** FamilyPicker (search by name or last 4 digits above a radio list; families who have not agreed show "won't get a confirmation call"); Problem as 6 icon ChoiceTiles (No water, Dirty water, Low pressure, Leak, Broken pump, Other); read-only "Water source: Main tank (from the family's record)"; [Raise complaint]. Toast "Complaint #9 raised. Ramesh will get a call." or "Added to #7: the same problem is already open." [View]. No families: "Add the family first." [Add a family] → `/families?add=1`.

### 5.3 Complaint detail (`/villages/:vid/complaints/:tid`, WP2)

- **Header:** link "All complaints"; H1 "#7 No water" + StatePill; subline "Main tank · opened 8 Oct, 10:41 · came in by missed call" (ORIGIN).
- **ComplaintProgress:** Reported → With operator → Operator says fixed → Checking with families → Fixed · confirmed. Horizontal at 640px+, vertical below; REOPENED / ESCALATED flag step 2.
- **Action card** (on phones, a sticky bottom bar above the tabs):
  - *OPEN, ASSIGNED, REOPENED, ESCALATED:* "Waiting for {operator} to fix it." + blocker ("Operator says: no electricity"). Secondary [Operator says it's fixed] → ConfirmDialog with an operator Select (default: the point's first operator → NAL_JAL_MITRA → SARPANCH) and "Normally the operator presses 1 on their call. Use this only if they told you in person." → `operatorFixed`, `boost()`.
  - *OPERATOR_REPORTED_FIXED, VERIFYING:* ConfirmationMeter "1 of 2 families have said water is back" (existing verify tally from VERIFY check-ins) with masked rows ("••1234 · Water came · 10:58"). [Close complaint]: primary when yes ≥ needed, else secondary.
  - *Cedar refusal* (`closeTicket` → `denied`): **PolicyCallout** (`role="alert"`, focus to title). Title "Can't close #7 yet"; body `reason_en`/`reason_hi`; why "A complaint closes only when the families who reported it say water is back. A written rule checks this, not a person or AI."; next "We keep calling them. It closes when enough families say water is back."; chip `verify-needs-quorum · checked 14:02 IST`; "Why?" link; [Got it].
  - *`409 verification_failed`:* warning Callout "A family still says there's no water. The complaint stays open and the operator is told again."
  - *CLOSED_VERIFIED:* success Callout "Fixed · confirmed by families on 9 Oct, 14:05", no buttons.
- **Other cards:** a "Test the water at School handpump" warning Callout [Record a test] when a DIRTY complaint needs one; VoiceNoteCard tagged "AI transcription · not confirmed by the operator"; Timeline "History, oldest first" with actor and channel ("Ramesh, pump operator · phone keypad").
- **Details** (right rail on desktop, a section on phones): KeyValueList of Water source, Who fixes it, Reported by ("2 families", ••1234), Families needed to close, Came in by, complaint id (mono, 14px).
- **Polling:** `getTicket` every 5 s while OPERATOR_REPORTED_FIXED or VERIFYING, else 30 s. **404:** "This complaint isn't in this village." [All complaints].

### 5.4 Families (`/villages/:vid/families`, WP3)

- **PageHeader** "Families" · "Families who answer the daily call. Nobody is called until they agree." · primary [Add a family] (`?add=1`) · tabs Families (n) · Consent record.
- **Families tab:** FilterChips with counts (All · Agreed · Waiting · Said no or stopped). Table: Name (`lang` from `langOf`) · Phone ••1234 · Water source · Agreement (ConsentPill) · Joined (Panchayat office / Missed call / First list). Phones: ListRows. A row opens **FamilySheet** (`?family=<hid>`): details, that household's consent events (`getConsents`, lazy, filtered), link "Raise a complaint for this family" → `/complaints?new=1&family=<hid>`.
- **Add a family (Sheet, `AddFamilyForm`):** PhoneInput with a fixed "+91", `inputMode="tel"`, `normaliseMobile` (`lib/phone.ts`), error "Enter a 10-digit mobile number"; Name (optional); "Where do they get water?" ChoiceTiles (optional; "Not sure: ask on the call"); checkbox, on by default, "Call them now to ask if they agree". Help: "They'll get a short Hindi call that explains JalSakshi. They agree by pressing 1; nobody can agree for them. Calls go out only between 9 am and 9 pm."
  - Toasts: "Added. {name} (••1234) will get a short call asking if they agree." / "Added. No call placed." / "Already on the list."
  - After adding: clear the number, `boost()`. The new row reads "Calling…" for 3 min (this session's added ids), then "Waiting for their call" with the §4.4 no-answer hint.
  - API errors in an inline Callout with the API message; `consent_declined` → "This family said no before. They can still join with their own missed call."; `not_configured` → "Calls aren't set up here. Untick 'Call them now' to just add them."
- **Consent record tab:** header card with notice version, `notice_sha256` (shortened, Copy button) and the API `label` (DPDP wording); [Download CSV] (`consentLedgerCsv`, `consentCsvName`). Table newest first: Time (IST) · Phone ••1234 · What happened (Agreed / Said no / Stopped calls / Under 18) · How (Phone keypad / In person / Office) · Key pressed · Notice. Empty: "No consent records yet. They appear when a family answers the consent call."

### 5.5 Water sources (`/villages/:vid/sources`, WP4)

- **PageHeader** "Water sources" · "Taps, handpumps and tankers families use, and who fixes each." · primary [Add a water source] (`?add=1`) · tabs Sources · Water tests.
- **Sources tab:** a Callout when any source is provisional: "1 source was created when a family registered. Give it a proper name." [Name it]. SourceCard grid (1 column, 2 from 640px, 3 from 1280px): KindIcon, name + Hindi name (`lang="hi"`), hamlet, "Water time 06:30–08:00", "Fixed by: Ramesh (pump operator)" or amber "Nobody assigned: complaints go to the pump operator, then the sarpanch", "6 families", today's StatusPill, QualityPill ("Safe · 2 Oct" / "Unsafe · 2 Oct" / amber "Test needed"), amber "Needs a name" tag.
- **SourceSheet** (`?source=`): `SourceForm` (name, Hindi name, kind ChoiceTiles, hamlet, water time, "Who fixes it" Select labelled by role e.g. "Ramesh Sahu, pump operator (Nal Jal Mitra)", "Families needed to confirm a repair" (blank = village default {q}), Active switch) → [Save] calls `saveWaterPoint`; Last 14 days DayDots with "View as table"; last 3 water tests + [Record a test].
- **Water tests tab:** primary [Record a test] (Sheet, `?test=<wpid>`: source, method Test kit / Lab, result Safe / Unsafe, date, readings as `name=value` lines via `parseReadings` from `lib/quality.ts`, note → `addQuality`). List: date, source, method, QualityPill, readings, "Entered by". A warning Callout per dirty complaint without a test. **GovRecordCard** "Government record (JJM WQMIS)": `official_note`, last household values, FTK counts, caption "Shown separately, never combined with your tests." It never calls the water safe.
- **Empty:** "No water sources yet." [Add a water source]; "No tests recorded yet." · "Record a field-kit or lab result for any source."

### 5.6 Announcements (`/villages/:vid/announcements`, WP5)

- **PageHeader** "Announcements" · "Short phone messages to every family. The sarpanch approves each one." · primary [New announcement]. **WeeklyLimitMeter** "1 of 2 sent this week" (bar from `sent_last_7_days` / `weekly_limit`) + "Calls go out only 9 am–9 pm".
- **Sections:** *Waiting for the sarpanch* (DRAFT): [Approve (sarpanch only)] · [Cancel] (Approve shown to everyone; Cedar decides). *Ready to send* (APPROVED): primary [Send now] → ConfirmDialog "Call every family on {target} and play this message?" [Yes, send now]. *Sent*: "Sent 9 Oct · 40 called · 32 picked up · 25 heard it (pressed 1)". *Cancelled*: collapsed `<details>`.
- **Card:** kind pill, Hindi text (16px, `lang="hi"`), audience, "Drafted by Anita · 2 h ago". `broadcast-needs-sarpanch`, `broadcast-weekly-limit` and `calling-hours` refusals render a PolicyCallout inside that card.
- **Draft sheet:** kind ChoiceTiles (Supply time change, Boil water, Repair done, Meeting, Other) that prefill a Hindi template; Textarea "Message in Hindi" with "n of 400 characters" (validation "Write the message (1 to 400 characters)."); audience Select (All families / one source); [Save draft].
- **Empty:** "No announcements yet." · "Tell every family about a supply change or a boil-water notice." [New announcement].

### 5.7 Reports (`/villages/:vid/reports`, WP5)

- **PageHeader** "Reports" · "Numbers to share with the sarpanch, the Gram Sabha and the block." · tabs Overview · Weekly summary · Gram Sabha sheet.
- **Overview** (SegmentedControl Last 7 days / Last 30 days): KPI Stats, each with a SourceNote ("Water came on 9 of 14 days we know about (64%)" with unknown days shown separately; complaints opened · fixed; usual repair time; families answering). "By water source" (port `ReliabilityList`): reliability bar + text, unknown days, no water, dirty, complaints, median repair, open now, "Why it fails" (top blocker). Last 14 days: DayDots + table toggle; a cell opens per-family answers (port `DayDetail`). GovVsFamiliesCard (full). Families: registered, agreed, coverage against Census households, where they got water instead. Announcements: reached and heard. Background card: groundwater, rain, state Har Ghar Jal, each with a SourceNote.
- **Weekly summary:** card "What the sarpanch hears on Monday's 10:00 call": `text_en` or `text_hi` by locale, the numbers, SourceNote, [Copy text].
- **Gram Sabha sheet:** [Make the sheet] (`getBrief`, then [Make it again]) · secondary [Print]. An A4 preview card, **always Hindi** (`lang="hi"`, Markdown); in English mode a note "Printed in Hindi for the Gram Sabha." Byline: `agent` → "Written by AI (Amazon Bedrock · {model_id}). Every number was checked against the data."; `template` → "Filled from the standard template (no AI)." Source footnotes. `stale-data` refusal → PolicyCallout "Can't make the sheet yet" with the reason and `CallFamiliesButton`. Print CSS prints only the sheet (A4, 15mm margins).

### 5.8 Activity, Test call, All villages (WP7)

- **Activity** (`/villages/:vid/activity`): grouped by day, newest first; each row a tabular time, kind icon, `pickField(text)`, and a policy-id chip on `policy_denied`. FilterChips All / Calls / Complaints / Rules; toggle "All villages"; LivePulse "Updates every 5 seconds" + [Pause]. Empty: "Nothing yet today. Calls, answers and complaints appear here as they happen."
- **Test call** (`/test-call`): violet banner "Test call. Answers are saved and labelled Test data." **Only demo villages** are listed (`isDemoVillage`, or all in mock mode), so nothing is recorded against a real village (§15.13); with none, "Test calls work only in demo villages." Setup card: Who answers (Family / Pump operator), Whose phone, Call type (Daily question / Consent call / Report a problem / Confirm a repair / Operator call). PhoneMock: a neutral frame with the Hindi prompt and a keypad (keys 0–9 * # also from the keyboard). Transcript: Hindi line, small English caption, keys pressed. 3 columns at 1024px+, stacked on phones.
- **All villages** (`/villages`): table (cards on phones) of Village (+ Demo tag) · Today · Open complaints · Water came, last 7 days · Last answer · Government record (Har Ghar Jal status). A row opens that village's Home.

### 5.9 Settings (`/villages/:vid/settings`, WP6)

Read-only except Language (no write endpoints exist); locked sections say "To change this, contact the JalSakshi team." Desktop has a left anchor sub-nav; phones stack the sections.
- **Village profile:** KeyValueList of names in both scripts, Gram Panchayat, block, district, LGD and Census codes, Census households and population, each with its source.
- **Daily calls:** call time; "A day counts when at least {q} families answer"; "Calls only between 9 am and 9 pm"; the missed-call number; `CallFamiliesButton`.
- **Team:** operators with name, role, ••1234 and the sources they fix; "Change who fixes a source" → Sources.
- **Residents:** residents' page link + [Copy link], [Print poster]. **Language:** `English | हिन्दी`.
- **About JalSakshi:** "Runs on AWS in Mumbai (ap-south-1): Amazon API Gateway, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge Scheduler, Amazon Bedrock, Amazon Cognito, Amazon S3 and CloudFront. Rules are written in Cedar and checked inside Lambda." Plus the stage, demo or live data, and the DPDP label.

### 5.10 Residents' page, poster, sign-in (WP6, WP0)

- **Residents' page** (`/v/:villageId`, no login, one column max 600px): slim header (wordmark + "जल साक्षी", LanguageToggle; the QR adds `?lang=hi`). In order: village name in both scripts + "Water status shared by families in your village"; the **report card**, the strongest element ("Water problem? Give a missed call", the number as a 56px `tel:` button, "Free. We call you back, 9 am–9 pm." or "Missed-call number coming soon"); today per source; **Open complaints** (number, problem, source, how long, how many families; never names or phones); "Fixed and confirmed by families: 4 · usually 18 h"; announcements (Hindi); last 30 days as DayDots + table; GovRecordCard; sources footer "updated 10:42". **Keep these tested strings:** "Missed-call number coming soon", heading "Open complaints", "This village is not on JalSakshi.", H1 with the village name.
- **Poster** (`/villages/:vid/poster`, A4 portrait, black-and-white safe): "पानी नहीं आया? गंदा पानी? मिस्ड कॉल दें" (40px) with "No water? Dirty water? Give a missed call." beneath; the number in 64px tabular digits; three pictogram steps; keypad legend 1 no water · 2 dirty water · 3 speak · 4 hear status · 9 stop calls; a 40mm QR (`uqr` `renderSVG`, lazy) → `{origin}/v/{vid}?lang=hi`, "Scan to see your village's water status"; footer with village, Gram Panchayat, LGD code, "JalSakshi · free call-back 9 am–9 pm". On screen [Print poster]; with no number, a warning and Print disabled.
- **Sign-in, Splash, ConfigError, Not found** (WP0): a centred card on `--bg`: mark, "JalSakshi", "जल साक्षी"; "Know if water really reached every home."; "For Panchayat secretaries, sarpanches and pump operators."; [Sign in]; LanguageToggle. Not found: "This page doesn't exist." [Go to Home].

## 6. Visual system (`web/src/styles/tokens.css`)

**Warm palette (user direction, 9 Oct: "need clean ui and warm color not white").** Sand/cream page, warm-white cards (never pure `#FFFFFF` as a surface), warm near-black text, one deep water-teal accent. Icons come only from `lucide-react` ("use standard icons from internet, no need to svg all icons"); no hand-drawn SVG icons except the droplet favicon/mark.

```css
:root {
  color-scheme: light;                      /* light only this round; tokens allow dark later */
  --bg: #F6F1E8; --surface: #FFFBF5; --surface-2: #EFE7DA;
  --border: #E5DCCD;                        /* decorative dividers only */
  --border-strong: #8C8071;                 /* inputs, checkboxes, control outlines */
  --text: #1F1A14; --text-2: #574D42; --text-3: #6B5F51;
  --accent: #0E6B73; --accent-hover: #0A545B; --accent-subtle: #E3F1F1; --accent-text: #0A545B; --on-accent: #FFFFFF;
  --focus-ring: 0 0 0 2px #FFFBF5, 0 0 0 4px #0E6B73;
  /* status: fg = text and icon, tint = pill background, solid = dots, day cells, bars */
  --ok: #067647;      --ok-tint: #E9F5EC;      --ok-solid: #079455;
  --warn: #A3470B;    --warn-tint: #FCF1DD;    --warn-solid: #D06A0F;
  --bad: #B42318;     --bad-tint: #FBEAE6;     --bad-solid: #D92D20;
  --dirty: #7A4A1E;   --dirty-tint: #F3E8DA;   --dirty-solid: #A15C1C;
  --unknown: #574D42; --unknown-tint: #EFE7DA; --unknown-solid: #7A6E60;
  --info: #0A545B;    --info-tint: #E3F1F1;
  --demo: #5925DC;    --demo-tint: #F1EDFB;    /* Test data, Replay, Demo, Simulated */
  --policy: #93370D;  --policy-tint: #FCF1DD;  --policy-edge: #D06A0F;
  --danger: #B42318;                         /* destructive buttons, white text */
  --gov-surface: var(--surface-2);
  --font-sans: 'Inter Variable', system-ui, -apple-system, 'Segoe UI', Roboto,
               'Noto Sans Devanagari', 'Nirmala UI', 'Kohinoor Devanagari', 'Mangal', sans-serif;
  --font-mono: ui-monospace, 'SF Mono', Consolas, monospace;
  --fs-xs: .75rem; --fs-sm: .875rem; --fs-base: 1rem; --fs-md: 1.125rem; --fs-lg: 1.25rem;
  --fs-xl: 1.5rem; --fs-2xl: 1.875rem; --fs-stat: 1.75rem;
  --lh-body: 1.5; --lh-head: 1.25;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s7: 32px; --s8: 40px; --s9: 48px; --s10: 64px;
  --gutter: 16px;                           /* 24px from 640px, 32px from 1024px */
  --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-xl: 16px; --r-pill: 999px;
  --shadow-card: 0 1px 2px rgb(60 40 20 / .05);
  --shadow-pop: 0 8px 24px -6px rgb(60 40 20 / .16), 0 2px 6px rgb(60 40 20 / .06);
  --shadow-sheet: 0 24px 48px -12px rgb(60 40 20 / .25);
  --backdrop: rgb(31 26 20 / .45);
  --dur: 150ms; --ease: cubic-bezier(.2, .8, .2, 1);
  --sidebar-w: 248px; --topbar-h: 56px; --tabbar-h: 64px; --content-max: 1200px; --form-max: 640px;
  --z-bar: 20; --z-sheet: 50; --z-toast: 60;
}
```

**Measured contrast (WCAG formula):**

| Pair | Ratio |
|---|---|
| `--text` on bg / surface / surface-2 / accent-subtle | 15.35 / 16.75 / 14.07 / 14.90 |
| `--text-2` on the same | 7.33 / 8.00 / 6.72 / 7.12 |
| `--text-3` on the same | 5.52 / 6.02 / 5.06 / 5.36 |
| `--accent` on bg / surface / surface-2; white on `--accent` | 5.54 / 6.05 / 5.08; 6.23 |
| white on `--accent-hover` | 8.63 |
| `--border-strong` on bg / surface (non-text, 3:1) | 3.43 / 3.74 |
| ok / warn / bad / dirty / unknown fg on their tint | 5.08 / 5.42 / 5.64 / 6.15 / 6.72 |
| ok / warn / bad fg on surface | 5.52 / 5.88 / 6.38 |
| solids on surface (dots, cells; 3:1) | ok 3.79 · warn 3.54 · bad 4.69 · dirty 5.01 · unknown 4.82 |
| demo fg on tint / surface; policy fg on tint | 6.70 / 7.48; 6.72 |

**Day status (always icon + word + colour; icons from `lucide-react`):**

| Value | Word | Tokens | Icon | DayDots cell |
|---|---|---|---|---|
| SUPPLIED | Water came | ok | CircleCheck | solid fill |
| PARTIAL | Some water | warn | Contrast (half circle) | solid fill |
| NO_SUPPLY | No water | bad | CircleX | solid fill |
| DIRTY | Dirty water | dirty | TriangleAlert | solid fill + white dot pattern |
| UNVERIFIED | Not enough answers | unknown | CircleHelp | white with a 1.5px dashed `--unknown-solid` outline |
| (no data) | No call | – | – | empty, 1px `--border` |

**Other pills.**
- *Complaint state* (TicketStatePill): neutral pill (`--surface-2`, `--text-2`) with an 8px coloured dot and a word. New: bad · With operator: warn · Operator says fixed / Checking with families: accent · Fixed · confirmed: ok, with a Check icon instead of the dot · Reopened: bad · Sent to PHED (simulated): warn + DemoTag.
- *Consent:* Agreed: ok · Waiting for their call: warn · Calling…: info + LivePulse · Said no: unknown · Stopped calls: unknown + Ban icon · Under 18: unknown.
- *Announcement:* Waiting for sarpanch: warn · Ready to send: info · Sent: ok · Cancelled: unknown. *Quality:* Safe: ok · Unsafe: bad · Test needed: warn.

**Type.** Inter Variable (`@fontsource-variable/inter`, Latin, wght) is the only webfont. Devanagari uses the system font, so nothing downloads (Android: Noto Sans Devanagari; Windows: Nirmala UI; macOS: Kohinoor). Body 16/24 (15/22 only in dense tables at 1024px+). Floor 14px; the only exception is 12px for tab labels and count badges. H1 24/32 on phones, 30/36 on desktop; card titles 18/600; section titles 20/600; Stat values 28/600 on phones, 32 on desktop, tabular. Weights 400/500/600 only; letter-spacing -0.011em at 20px+. `:lang(hi)`: body line-height 1.7, headings 1.4, labels 500, no italics. Sentence case, no all-caps. Numbers: `tabular-nums`, `Intl.NumberFormat('en-IN')`, Latin digits in both languages.

**Shape, space, motion.**
- Cards: `--surface` (warm white), 1px `--border`, `--r-lg`, `--shadow-card`, 16px padding (20–24px desktop). Interactive cards turn their border `--border-strong` on hover; no lift.
- Controls: `--r-md`, 40px tall on desktop, 44px on touch, 48px for phone primary actions. Inputs 48px with 16px text on phones (no iOS zoom).
- Sheets: a 480px right drawer at 1024px+; below, a bottom sheet (max 92vh, 16px top radius, sticky footer). Popovers, menus, toasts: `--shadow-pop`. Sheets, dialogs: `--shadow-sheet` + `--backdrop`.
- Motion: `--dur` / `--ease` on sheets, popovers, toasts; all off under `prefers-reduced-motion` (LivePulse becomes a static dot).
- Icons: `lucide-react` (exact version pinned), stroke 1.75, 20px in nav, 16px inline; empty-state icons 24px in a 48px tinted circle. Languages use words, never flags.
- Print: chrome marked `data-chrome` is hidden; A4, 15mm margins, black on white. Forced colours: pills and cards keep a 1px `CanvasText` border; focus `outline: 2px solid Highlight`.
- Brand: favicon and mark are a droplet with a check in `--accent`. `<meta name="theme-color" content="#F6F1E8">` and `<meta name="color-scheme" content="only light">` stop Android auto-dark from inverting the UI.

## 7. Component inventory

Rules: one CSS module per component, tokens only; no hex outside `tokens.css`; no text inside components except through props or i18n.

**`web/src/ui/` (generic, WP0)**

| Component | Props / variants | Notes |
|---|---|---|
| `Button` | `variant: primary\|secondary\|ghost\|danger\|link`, `size: sm\|md\|lg`, `icon?`, `loading?`, `fullWidth?`, `as: 'a' \| Link` | `sm` (32px) desktop only; `loading` keeps width, sets `aria-busy` |
| `IconButton` | `label` (required), `icon`, `size` | Tooltip optional, never essential |
| `Card` | `variant: default\|interactive\|muted\|dashed`; `Card.Header{title, description?, actions?}`, `Card.Footer` | Interactive = one link, focus ring on the card |
| `Stat` | `label`, `value`, `sub?`, `source?: SourceTag`, `href?`, `size: md\|lg` | "—" + "No answers yet" when empty |
| `ListRow` | `icon?`, `title`, `meta?`, `trailing?`, `href?`, `selected?`, `height: 44\|56\|64` | Whole row is a link |
| `DataTable<T>` | `caption` (visually hidden), `columns[]`, `rows`, `rowHref?`, `stackBelow=1024` | Renders ListRows below the breakpoint |
| `EmptyState` | `icon`, `title`, `body`, `action?`, `secondary?`, `helpId?`, `variant: page\|section\|inline` | Title "No X yet."; the action matches it |
| `ErrorState` | `what: Bilingual`, `onRetry` | Inline; never blanks the page |
| `Skeleton` | `variant: line\|row\|card\|stat`, `count?` | Shimmer only without reduced motion |
| `Callout` | `tone: info\|success\|warning\|policy`, `title`, children, `actions?`, `focusOnMount?` | `focusOnMount` focuses the title |
| `Toast` / `useToast()` | `toast({text, action?, tone?})` | Polite live region, 5 s, max 3 stacked |
| `Sheet` | `open`, `onClose`, `title`, `footer?`, `queryKey?` | Native `<dialog>` + `showModal()`, Esc, focus returns to trigger; `queryKey` syncs with `?key` |
| `ConfirmDialog` | `title`, `body`, `confirmLabel`, `tone?: danger`, `onConfirm` | Initial focus on Cancel |
| `Popover`, `Menu` | `trigger`, `placement` | Click or Enter, never hover-only; Esc closes |
| `Tabs` | `items[{id,label,count?}]`, synced with `?tab=` | Links with `aria-current` |
| `SegmentedControl`, `FilterChips` | `options[{id,label,count?}]`, `value`, `onChange` | `role=group`, `aria-pressed` |
| `Field` + `TextInput`, `PhoneInput` (+91), `Select`, `Textarea` (`max`, counter), `Checkbox`, `Switch` | `label`, `hint?`, `error?` | `aria-describedby`, `aria-invalid` wired |
| `ChoiceTiles` | `name`, `options[{id,label,icon}]`, `value`, `columns: 2\|3` | Radio group as icon tiles; 2 columns on phones |
| `PickList` | `items`, `searchLabel`, `value`, `onChange`, `render` | Search input + radio list (family picker) |
| `ProgressBar`, `ProgressRing`, `LivePulse`, `Tag`, `CountBadge`, `KeyValueList`, `VisuallyHidden` | – | CountBadge has hidden text ("3 open") |

**`web/src/shared/` (domain-shared, WP0)**

| Component | Props | Notes |
|---|---|---|
| `StatusPill`, `TicketStatePill`, `ConsentPill`, `AnnouncementPill`, `QualityPill` | `value`, `size: sm\|md`, `count?` | Words from `lib/labels.ts` |
| `DemoTag` | `kind: test\|replay\|demo\|simulated` | Violet, always visible |
| `SourceNote` | `source: SourceTag \| SourceTag[]`, `label?`, `rule?` | One line ("Families' phone answers · updated 10:42"), a DemoTag when simulated or replay, and an (i) button (`aria-label` "About this number") opening a Popover: source name, observed and fetched times (IST), freshness, link, rule |
| `DayDots` | `days`, `from`, `to`, `today`, `size: sm\|md`, `onSelect?`, `showTable?` | `<ol>` with visually hidden "Thu 9 Oct: No water"; cells are buttons only with `onSelect` |
| `GovRecordCard` | `title`, `asOn`, `rows`, `source` | Landmark icon, `--gov-surface`, "Government record" label |
| `GovVsFamiliesCard` | `official`, `familiesSay{supplied, observed, days}`, `compact?` | Two fixed columns (stacked on phones), never summed; "Shown side by side, never combined." |
| `PolicyCallout` | `denied: PolicyDenied`, `onDismiss`, `helpId?` | Uses `policyCopy()`: title, reason (`pickField`), why, next, mono rule chip with time; `role=alert`, focus on mount |
| `CallFamiliesButton` | `variant`, `villageId`, `callable: number` | Port of `RunCheckin`: confirm dialog, disabled outside 9–21 IST with the reason, errors mapped (§4.6), `boost()` on success |
| `KindIcon`, `VillageName`, `BarList` | – | Restyled ports |

**`web/src/shell/` (WP0):** `AppShell`, `Sidebar`, `NavItem`, `TopBar`, `BottomTabs`, `MoreSheet`, `VillageSwitcher`, `LanguageToggle` (wraps `locale.tsx` logic), `UserMenu`, `DemoBanner`, `PageHeader`, `VillageData` / `useVillageData`, `useVillages`, `LegacyRedirect`, `FocusOnNavigate`, `AuthScreens`.

**Feature components:** WP1 `HomePage`, `WaterTodayCard`, `AttentionCard`, `ThisWeekCard`, `RecentActivityCard`, `ShareCard`, `SetupChecklist`, `SetupFlow` (+ step screens, `WaitingForAnswers`), `GuidePage` · WP2 `ComplaintsPage`, `ComplaintRow`, `ComplaintDetailPage`, `ComplaintProgress`, `ConfirmationMeter`, `OperatorFixedDialog`, `CloseAction`, `RaiseComplaintSheet`, `FamilyPicker`, `Timeline`, `VoiceNoteCard`, `TicketRedirect` · WP3 `FamiliesPage`, `FamilySheet`, `AddFamilySheet`, **`AddFamilyForm`**, `ConsentRecordTab` · WP4 `SourcesPage`, `SourceCard`, `SourceSheet`, **`SourceForm`**, `WaterTestsTab`, `QualityTestSheet` · WP5 `AnnouncementsPage`, `AnnouncementCard`, `DraftSheet`, `WeeklyLimitMeter`, `ReportsPage`, `OverviewTab`, `ReliabilityList`, `DayDetail`, `WeeklySummaryTab`, `GramSabhaSheet`, `Markdown` · WP6 `PublicLayout`, `PublicVillagePage`, `PosterPage`, `QrCode` (lazy), `SettingsPage` · WP7 `ActivityPage`, `TestCallPage`, `PhoneMock`, `useSimCall` (port), `AllVillagesPage`.

**Cross-package contracts (frozen at kickoff):** `AddFamilyForm({ villageId, onAdded(res: AddHouseholdResponse), compact? })`; `SourceForm({ villageId, point?, operators, onSaved(p: WaterPoint), fields?: 'all' | 'name-and-operator' })`; the URL flags in §2; `useVillageData()`, `setupProgress()`, `attentionItems()`.

## 8. Microcopy

**Tone:** plain, calm, specific, like a helpful colleague. Second person, verb first, one idea per sentence (ideally under 14 words). Numbers say "of how many" ("1 of 2 families"). Always say who, what and when. Sentence case, no exclamation marks. Errors say what failed and what to do; refusals say the rule and what happens next.

**Never on screen:** ticket, quorum, check-in, reconcile, IVR, broadcast, provisional, ledger, analytics, brief, simulator, households (say *families*), water point (say *water source*), UNVERIFIED or other enum names. A policy id appears only in the small mono rule chip. Scheme words are glossed once: "Nal Jal Mitra (pump operator)".

**Hindi:** everyday words (शिकायत, परिवार, पानी का स्रोत, घोषणा, रिपोर्ट, सेटिंग्स, शुरुआत करें), not Sanskritised officialese. The whole UI switches; strings are never stacked in two languages. Shown as written: people's names, village and source names (both scripts where both exist), announcement text, the Gram Sabha sheet (always Hindi), IVR prompts. Vamsi reviews the Hindi before filming.

| Key | English | Hindi |
|---|---|---|
| nav | Home · Complaints · Families · Water sources · Announcements · Reports · Activity · Test call · Residents' page · Settings · Getting started · Help & guide · More | होम · शिकायतें · परिवार · पानी के स्रोत · घोषणाएँ · रिपोर्ट · गतिविधि · टेस्ट कॉल · निवासियों का पेज · सेटिंग्स · शुरुआत करें · मदद और गाइड · और |
| tabs (short) | Home · Complaints · Families · Announce · More | होम · शिकायतें · परिवार · घोषणा · और |
| home | Today · Water today · Needs your attention | आज · आज पानी · आपके ध्यान के लिए |
| all clear | All clear. Nothing needs you right now. | सब ठीक है। अभी आपके लिए कोई काम नहीं। |
| call now | Call families now | अभी परिवारों को कॉल करें |
| call confirm | Call {n} families now? | अभी {n} परिवारों को कॉल करें? |
| hours | Calls go out only between 9 am and 9 pm. | कॉल सिर्फ़ सुबह 9 से रात 9 बजे के बीच जाती हैं। |
| actions | Raise a complaint · Add a family · Add a water source · Record a water test · New announcement | शिकायत दर्ज करें · परिवार जोड़ें · पानी का स्रोत जोड़ें · पानी की जाँच दर्ज करें · नई घोषणा |
| approve / send | Approve (sarpanch only) · Send now · Yes, send now | मंज़ूर करें (सिर्फ़ सरपंच) · अभी भेजें · हाँ, अभी भेजें |
| complaint actions | Close complaint · Operator says it's fixed | शिकायत बंद करें · ऑपरेटर ने ठीक बताया |
| reports | Gram Sabha sheet · Make the sheet · Print the poster · Download CSV | ग्राम सभा पत्र · पत्र बनाएँ · पोस्टर प्रिंट करें · CSV डाउनलोड करें |
| day status | Water came · Some water · No water · Dirty water · Not enough answers | पानी आया · थोड़ा पानी · पानी नहीं आया · गंदा पानी · पूरे जवाब नहीं |
| complaint state | New · With operator · Operator says fixed · Checking with families · Fixed · confirmed · Reopened · Sent to PHED (simulated) | नई · ऑपरेटर के पास · ऑपरेटर के अनुसार ठीक · परिवारों से पूछ रहे हैं · ठीक हुई · पुष्टि हुई · फिर से खुली · PHED को भेजी (सिम्युलेटेड) |
| consent | Agreed · Waiting for their call · Calling… · Said no · Stopped calls · Under 18 | सहमत · कॉल का इंतज़ार · कॉल जा रही है… · मना किया · कॉल बंद करवाए · 18 से कम उम्र |
| announcement state | Waiting for sarpanch · Ready to send · Sent · Cancelled | सरपंच की मंज़ूरी बाकी · भेजने के लिए तैयार · भेजी गई · रद्द |
| tags | Test data · Replay · Demo · AI transcription · not confirmed by the operator | टेस्ट डेटा · रीप्ले · डेमो · AI से लिखा गया · ऑपरेटर ने पुष्टि नहीं की |
| gov | Government record · Shown side by side, never combined. | सरकारी रिकॉर्ड · साथ में दिखाया, कभी जोड़ा नहीं। |
| rule | Decided by the counting rule, not by AI. | गिनती के नियम से तय, AI से नहीं। |
| close refused | Can't close #7 yet · We keep calling them. It closes when enough families say water is back. | शिकायत #7 अभी बंद नहीं हो सकती · हम उन्हें कॉल करते रहेंगे। जब काफ़ी परिवार बताएँगे कि पानी आ गया, शिकायत बंद होगी। |
| family added | Added. {name} (••1234) will get a short call asking if they agree. | जोड़ दिया। {name} (••1234) को सहमति के लिए एक छोटी कॉल जाएगी। |
| empty | No open complaints. · No families yet. · No water sources yet. | कोई खुली शिकायत नहीं। · अभी कोई परिवार नहीं। · अभी कोई पानी का स्रोत नहीं। |
| load error | Couldn't load {thing}. Check your connection and try again. | {thing} लोड नहीं हुआ। इंटरनेट देखें और फिर कोशिश करें। |
| setup | Get {village} ready · 3 of 6 done · Getting started | {village} को तैयार करें · 6 में से 3 पूरे · शुरुआत करें |
| sign-in | Know if water really reached every home. | जानिए, पानी सच में हर घर पहुँचा या नहीं। |

**Where strings live:** `i18n/messages/<area>.ts`, one file per package (§11). Every entry is a `Bilingual` or `BilingualFn` pair with English written first, so a missing translation is a compile error. Plurals use `enCount` with an explicit zero message. Shared enum words live in `lib/labels.ts`; refusal copy in `lib/policy.ts`.

## 9. Accessibility (WCAG 2.2 AA)

1. **Landmarks and focus:** skip link, `<nav aria-label>`, one `<main>`, one H1 per page. On route change focus moves to the H1 (`FocusOnNavigate`) and `document.title` becomes "{Page} · {village} · JalSakshi".
2. **Contrast:** only the §6 token pairs; never `--text-3` on `--accent-subtle`. Status is never colour alone (icon + word); pills never truncate the word.
3. **Targets:** at least 44×44px (48px phone primary actions), 8px between adjacent list targets.
4. **Dialogs:** native `<dialog>` with `showModal()` (focus trap, Esc, inert background, focus returns to the trigger). A query-synced sheet closes on the browser or Android back button.
5. **Popovers and tooltips** open on click or Enter, never hover-only. Essential information never lives only in a popover; simulated and replay data always have a visible tag.
6. **Live regions:** toasts and the language switch are polite. PolicyCallout and form-level errors use `role="alert"` with focus on the callout title. LivePulse is announced once; polling never moves focus or re-announces unchanged content.
7. **Forms:** visible labels (placeholders are not labels), hints and errors via `aria-describedby`, `aria-invalid`, focus to the first invalid field on submit; phone fields use `inputMode="tel"` and `autocomplete="tel-national"`.
8. **Data:** tables have `<caption>` and `scope`; DayDots have visually hidden per-day text plus a table view; bars always print their value as text; badge counts have hidden text.
9. **Language:** `<html lang>` follows the locale; mixed-script data gets `lang` (`langOf`); language options are words, not flags.
10. **Reflow:** works at 200% zoom and 320px CSS width with no horizontal scroll; table cells wrap, never clip. Reduced motion and forced colours as in §6.
11. **Manual check before merge:** each package runs axe DevTools and a keyboard-only pass of its screens at 360px and 1280px, in English and Hindi.

## 10. What to delete (WP8, after every page is ported; nothing new may import these)

| Kind | Delete |
|---|---|
| Styles | `web/src/styles/global.css`, `web/src/styles/watercolour.css`, and with them every `.board`, `.slip`, `.slip-ruled`, `.paint`, `.dry`, `.wall-lettering`, `.wash`, `.has-wash`, `.btn-stamp`, `.seg` class |
| Components | `components/Wash.tsx`, `RegisterSlip.*`, `RecordSlip.tsx`, `Verdict.*`, `TallyTiles.*`, `StatusStrip.*`, `Icons.tsx`, `LangRuns.tsx`, `Bi.tsx`, `Layout.*`, `PublicLayout.tsx`, `PageState.*`, `PolicyDenial.*`, `SourceBadge.*`, `StatusChip.*`, `TicketParts.*`, `Timeline.*`, `FeaturePhone.*`, `Form.module.css`, `BarList.*`, `Markdown.*`, `VillageName.tsx` (the last six are ported first) |
| Pages | all of `web/src/pages/`: `VillagesPage`, `VillageDetailPage`, `TicketPage`, `BriefPage`, `SimulatorPage` + `simulator/`, `ActivityPage`, `PublicVillagePage`, `AuthScreens`, and the 19 files in `village/` |
| Lib, i18n | `lib/verdict.ts`, `lib/reliability.ts` (if unused), `i18n/messages.ts` (replaced by `i18n/messages/*`) |
| Dependencies | `@fontsource-variable/anek-latin`, `@fontsource-variable/anek-devanagari`, `@fontsource/tiro-devanagari-hindi`; `preloadHindiFont` becomes a no-op (system Devanagari) |
| Concepts | wall lettering, washes and paint, register slips and the serif record face, the verified stamp, verdict sentences, the 8-tab village record, the Strip/Table toggle, hero bands |
| Copy | "Repair ticket", "Run check-in now", "Open village record", "Households", "Phone simulator", "Gram Sabha brief", "Consent ledger", "quorum", "Not confirmed" |

## 11. Build plan

`web/` is Varun's module: WP0 posts a heads-up line in `docs/HANDOVER.md` at kickoff and WP8 writes the final status line. One branch per package (`feat/web-<wp>`), merged into `feat/web-v3`, then into `main`.

**Sequence.**
1. **Kickoff (WP0, about 45 min; everyone else reads this spec):** dependencies, tokens and base CSS, an empty shell, the full route table, stubs and the frozen signatures. After the kickoff commit each package owns only its own files.
2. **Parallel (about 4 h):** WP0 builds out `ui/`, `shared/` and `shell/`, landing Button, Card, PageHeader, the pills and Sheet by hour 1.5 and the rest by hour 2.5. WP1–WP7 build their pages, starting from their logic and data.
3. **Integration (WP8, about 75 min, after all merges).**

**P0 (the demo and the real loop):** WP0, WP1 (Home + checklist), WP2, WP3. **Cut order when late:** All villages → Activity filters → Settings detail → Reports day detail → poster QR (fall back to a printed URL) → setup flow screens (the checklist alone is enough).

| WP | Scope | Owns exactly these files (all under `web/` unless noted) |
|---|---|---|
| **WP0 Foundation** | Tokens, shell, primitives, shared domain components, routes and redirects, i18n structure, relabels, auth screens | `package.json`, `pnpm-lock.yaml` (add `@fontsource-variable/inter`, `lucide-react`, `uqr` at exact versions; remove the 3 old fonts), `index.html`, `public/favicon.svg`, `src/main.tsx`, `src/App.tsx`, `src/styles/tokens.css`, `src/styles/base.css`, `src/ui/**`, `src/shared/**`, `src/shell/**`, `src/i18n/locale.tsx`, `src/i18n/messages/common.ts`, `src/lib/labels.ts`, `src/lib/policy.ts`, `src/lib/routes.ts`, `src/lib/demo.ts`, `src/lib/phone.ts` (`normaliseMobile`), `src/lib/quality.ts` (`parseReadings`), `tests/routes.test.ts`, `tests/shell.test.tsx`, `tests/lib.test.ts` (label assertions only), `docs/HANDOVER.md` (heads-up line). **Kickoff stubs, handed over after the kickoff commit:** `src/features/<area>/index.ts` for each of the 10 areas below, `src/i18n/messages/<area>.ts`, `src/lib/setup.ts`, `src/lib/attention.ts` (signatures from §4.1 and §5.1) |
| **WP1 Home + onboarding** | Home, checklist, setup flow, guide | `src/features/home/**`, `src/features/onboarding/**`, `src/lib/setup.ts`, `src/lib/attention.ts`, `src/i18n/messages/home.ts`, `src/i18n/messages/onboarding.ts`, `tests/setup.test.ts`, `tests/attention.test.ts`, `tests/home.test.tsx`; optional P2: an empty "नया गाँव (डेमो) / New village (demo)" in `src/api/mockSeedPanchayat.ts`, only if `mock.test.ts` and `panchayat.test.ts` stay green |
| **WP2 Complaints** | List, detail, raise, operator-fixed, close + refusal, ticket redirect | `src/features/complaints/**`, `src/i18n/messages/complaints.ts`, `tests/complaints.test.tsx` |
| **WP3 Families** | List, family sheet, add family (`AddFamilyForm`), consent record + CSV | `src/features/families/**`, `src/i18n/messages/families.ts`, `tests/families.test.tsx` |
| **WP4 Water sources** | Sources, source sheet (`SourceForm`), water tests, WQMIS government card | `src/features/sources/**`, `src/i18n/messages/sources.ts`, `tests/sources.test.tsx` |
| **WP5 Announcements + reports** | Announcements; reports overview, weekly summary, Gram Sabha sheet + print | `src/features/announcements/**`, `src/features/reports/**`, `src/i18n/messages/announcements.ts`, `src/i18n/messages/reports.ts`, `tests/announcements.test.tsx`, `tests/reports.test.tsx` (port the announcement and analytics cases from `panchayatUi.test.tsx`) |
| **WP6 Residents + poster + settings** | Public page restyle, A4 poster + QR, settings | `src/features/public/**`, `src/features/poster/**`, `src/features/settings/**`, `src/i18n/messages/public.ts`, `src/i18n/messages/poster.ts`, `src/i18n/messages/settings.ts`, `tests/public.test.tsx` (port the residents' page cases) |
| **WP7 Activity + test call + all villages** | Activity feed, test call (demo villages only), all-villages table | `src/features/activity/**`, `src/features/testcall/**`, `src/features/villages/**`, `src/i18n/messages/activity.ts`, `src/i18n/messages/testcall.ts`, `src/i18n/messages/villages.ts`, `tests/testcall.test.tsx` |
| **WP8 Integration** (last, alone) | Deletions, existing tests, docs, full checks | All §10 deletions; `src/i18n/messages.ts`; `tests/panchayatUi.test.tsx`, `tests/i18n.test.ts`, `tests/console.test.ts`, `tests/panchayatLib.test.ts` (imports move to `lib/phone`, `lib/quality`), the verdict cases in `tests/lib.test.ts`; `docs/DEMO_SCRIPT.md` and `docs/FILMING_CHECKLIST.md` (renamed button names only, no new filming content); `docs/HANDOVER.md` (status line + a "Renamed in the console" table) |

**Rules for every package.** Import only from `ui/`, `shared/`, `shell/`, `lib/`, `api/`, `hooks/`, `i18n/locale.tsx`, your own `features/<area>/` and `i18n/messages/<area>.ts`, plus the two frozen cross-package forms. Never import from the old `pages/` or `components/`; port what you need into your own folder. `api/*` is read-only (except WP1's optional mock village). Ask WP0 for a new primitive; do not fork one.

**Package done:** `pnpm typecheck`, `pnpm lint`, `pnpm test` green; screens checked at 360px and 1280px in English and Hindi on mock data; no strings outside your messages file; no hex outside `tokens.css`; every number has a SourceNote and test data is tagged.

**Release done (WP8):** `pnpm lint && pnpm test && pnpm build` clean; main bundle ≤ 140 KB gzip (every route except Home lazy, QR only on the poster); axe + keyboard pass at 360/1280 px in both languages; none of the §10 files remain; the real loop walked once on a deployed stage between 09:00 and 21:00 IST (add a family → they press 1 → Call families now → first answer → close refused with "1 of 2" → families confirm → closed).

# JobFlow Product and Operations Pass — Implementation Plan

> **For Hermes:** Implement this plan in bounded user-visible slices. Preserve the accepted Pencil visual language, mobile viewport-locked shell, white app surface over the cream desktop canvas, and explicit approval before any external application action.

**Goal:** Turn JobFlow’s currently decorative or machine-facing controls into a coherent mobile product: understandable preferences, real daily history, observable and manually triggerable scheduled discovery, configurable source/platform strategy, and an app-owned Reactive Resume connection with a visible canonical reference CV.

**Architecture:** Keep the current React/FastAPI/SQLite single-container application. Make the immediate UX corrections without schema work, then add only the persistent operational state needed for schedules, discovery runs/candidates, enabled source modes, and encrypted integration credentials. JobFlow owns deterministic scheduling/provider calls/state; the external agent reads and acts through API/CLI and never receives stored secrets.

**Tech Stack:** React 19 + TypeScript + Vite, lucide-react, FastAPI, Pydantic, SQLite, existing Docker/Dokploy deployment, Firecrawl v2, Reactive Resume OpenAPI.

---

## Confirmed current-state findings

- `PreferencesView` always renders a wide `.sticky-submit` footer with a white background. It has no dirty baseline or discard action.
- The salary “slider” is only painted CSS; only numeric inputs modify values.
- The production profile contains a target range of €50k–€56k and an acceptable transition floor of €47.5k. `Normally reject below 45000 EUR` was imported from the old profile’s weak floor and is incorrectly shown as a hard rule.
- Current role families are raw YAML identifiers such as `junior_software_developer`.
- `preferredRules()` injects unrelated template defaults (`Remote within EU`, `Senior or lead`, `Product companies`); these are not Toni’s profile and must be removed.
- `External applications stay manual` is a mutable checkbox even though explicit per-opportunity approval is a fixed product boundary.
- Activity’s top-right Settings icon is a non-interactive `<span>`.
- Job source uses an ellipsis icon; decline uses an X even though it means passing/rejecting rather than closing.
- `PulseBars` is a static hard-coded array, not historical data.
- Production `discovery_queries` is empty. `/api/discovery/run` therefore returns `No discovery queries are configured`.
- The current discovery run searches and returns transient candidate URLs but does not persist a run/candidate record or schedule future work.
- The preserved system used Europe/Vienna discovery at 07:00, 13:00, and 19:00; AI scout at +15 minutes; package drafter at +30 minutes. The old automation is paused and should remain historical, not be restarted.
- Historical source strategy: Firecrawl broad web search; AgentMail karriere.at alert links; reviewed direct company/ATS URLs; manual URLs; browser-assisted exploration; AMS manual-only; DEVjobs/DEVworkplaces disabled pending review.
- Reactive Resume base URL is `https://rxresu.me/api/openapi`; the protected historical source is `Hermes Starting Template`; the verified one-page reference is `Hermes Canonical Base CV` using a duplicate-only tailoring workflow.

## Product decisions inferred from Toni’s feedback

No blocking clarification is required before the first implementation slice.

1. Keep the old 07:00 / 13:00 / 19:00 Europe/Vienna schedule as the editable initial default.
2. Remove the €45k rule from the hard-rule UI. Present €50k–€56k as the target range; describe €47.5k only as an exceptional-transition floor rather than a random hard rule.
3. Replace machine role-family values with a human-facing **Roles & keywords** tag editor. Enter, semicolon, and comma create tags; each tag has a remove control.
4. Make submission approval non-configurable in ordinary preferences: “JobFlow prepares; you approve before applying.”
5. Make Activity’s top-right action open the Automation/Search configuration area.
6. Do not pretend unsupported platforms are active. Show platform capability and setup state honestly.
7. Store a Reactive Resume API key only through a write-only secret endpoint; never return or expose it to frontend state, activity, logs, CLI output, or agent prompts.

---

### Task 1: Preferences dirty-state action cluster

**Objective:** Show compact Save and Discard controls only while the form differs from the last successfully loaded/saved preferences.

**Files:**
- Modify: `frontend/src/main.tsx` (`PreferencesView`, `savePreferences` contract)
- Modify: `frontend/src/styles.css` (`.sticky-submit` and new compact action styles)

**Steps:**
1. Keep a persisted baseline and an editable draft in `PreferencesView`.
2. Compare normalized preference objects (not object identity); normalize list order only where order is semantically irrelevant.
3. Render no action cluster while clean.
4. While dirty, render a transparent sticky cluster above the navbar containing:
   - compact Save button;
   - small X button with `aria-label="Discard unsaved preference changes"`.
5. On discard, restore the baseline and hide the cluster.
6. On successful save, replace both baseline and draft with the API response and hide the cluster.
7. Preserve an error state if save fails; do not hide controls while unsaved data remains.

**Verification:**
- Open Me: no Save control initially.
- Change one value: Save + X appear without a white tray.
- X restores the original value and hides both controls.
- Save persists, updates the baseline, and hides both controls.
- At 428×926, both controls remain above the fixed navbar and do not cover the final field.

### Task 2: Real dual-ended salary range

**Objective:** Make both target minimum and maximum directly slideable while preserving exact numeric editing.

**Files:**
- Modify: `frontend/src/main.tsx` (`PreferencesView`, salary helpers)
- Modify: `frontend/src/styles.css` (`.salary-track`, range handles, fill)

**Steps:**
1. Replace the decorative track with two accessible `input[type=range]` controls sharing a 30k–120k track, step €1k.
2. Bind the lower handle to `salary_target_min` and upper handle to `salary_target_max`.
3. Clamp minimum below/equal maximum and maximum above/equal minimum.
4. Draw the orange fill between both handles.
5. Keep compact number inputs or amount labels so exact values remain editable and visible.
6. Add plain copy: “Target range”; optionally one small line “Exceptional transition roles can still be considered from €47.5k.”
7. Remove `Normally reject below 45000 EUR` from visible hard rules and persisted imported hard rules when preferences are next saved.

**Verification:**
- Pointer/touch drag each handle independently.
- Keyboard arrows work on each handle.
- Crossing handles is prevented without jumping unpredictably.
- Persisted GET returns the selected min and max.

### Task 3: Human-facing role and keyword tags

**Objective:** Replace the machine-style multiline role textarea with a mobile-friendly tag editor.

**Files:**
- Modify: `frontend/src/main.tsx` (new `TagEditor`; preferences normalization)
- Modify: `frontend/src/styles.css`

**Steps:**
1. Rename the section to **Roles & keywords**.
2. Humanize imported snake_case entries on load (`junior_software_developer` → `Junior software developer`).
3. Accept Enter, semicolon, and comma as commit delimiters.
4. Trim, deduplicate case-insensitively, and reject empty tags.
5. Render each value as a removable tag with an accessible remove button.
6. Backspace on an empty editor removes/focuses the last tag using conventional tag-input behavior.
7. Persist human-readable strings; do not reintroduce machine identifiers in the UI.
8. Reuse the component for other list fields only where it improves the UI; do not convert long full search phrases into tiny tags if they become unreadable.

**Verification:**
- Enter `internal tools; Python automation` and confirm two tags.
- Reload after save and confirm human-readable persistence.
- Remove a tag and discard; baseline returns.

### Task 4: Make safety language clear and non-misleading

**Objective:** Explain the approval boundary without presenting it as a toggle that can casually disable safety.

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`

**Steps:**
1. Replace `External applications stay manual` checkbox with a locked informational row:
   - title: `Applying requires your approval`;
   - help: `JobFlow may find jobs and prepare CVs and letters, but it never submits or contacts an employer without your approval.`
2. Keep `manual_submission_only=true` in the API and agent contract.
3. Remove fake hard-rule defaults from `preferredRules()` and show only real profile rules with human copy.
4. Map imported machine/policy rules to concise labels rather than dumping policy strings into toggle rows.

**Verification:**
- No UI control can turn automatic external submission on.
- Preferences save preserves `manual_submission_only=true`.

### Task 5: Correct misleading icons and dead actions

**Objective:** Ensure every visible action communicates and performs its actual behavior.

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css` only if sizing changes are needed

**Steps:**
1. Replace job source `Ellipsis` with lucide `ExternalLink` or `Link` and keep the precise `Open original job listing` label.
2. Replace review decline X with lucide `Trash2`; keep the separate X only for closing the decline feedback panel.
3. Convert Activity’s Settings icon into a real button that navigates to Me and focuses/scrolls to **Search automation**.
4. Remove any other decorative control that looks clickable but has no behavior.
5. Make activity rows with `job_id` open the corresponding job; rows without a target should not show a misleading arrow.

**Verification:**
- Click each changed control on mobile and desktop.
- Source link opens the exact source URL in a new tab.
- Trash opens feedback; close X closes it.
- Activity settings opens the correct configuration area.

### Task 6: Real daily pulse history

**Objective:** Make each Inbox pulse bar represent one calendar day’s discovered-job count.

**Files:**
- Modify: `backend/jobflow/models.py`
- Modify: `backend/jobflow/main.py`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_discovery.py` or new `backend/tests/test_dashboard.py`

**Steps:**
1. Add `GET /api/dashboard/pulse?days=20` returning exactly 20 Europe/Vienna dates with zero-filled job counts derived from `jobs.first_seen_at`.
2. Return today’s count separately so “new roles found” is not the current filtered list length.
3. Pass real data into `PulseBars` and scale heights relative to the 20-day maximum, retaining a small minimum for zero days.
4. Add accessible text/labels (`date`, `count`) while keeping the visual subtle.
5. Do not fabricate history for missing dates.

**Verification:**
- Backend test covers zero-fill and timezone date boundaries.
- Inject jobs across three days and verify bar count/relative heights.
- Inbox loaded against production data shows 20 meaningful day bars.

### Task 7: Persisted discovery operations and manual runs

**Objective:** Replace the empty-query error with an observable operation that records what happened.

**Files:**
- Modify: `backend/jobflow/database.py`
- Modify: `backend/jobflow/models.py`
- Refactor: `backend/jobflow/main.py`
- Create: `backend/jobflow/discovery.py` only if extraction materially simplifies `main.py`
- Modify: `backend/jobflow/cli.py`
- Test: `backend/tests/test_discovery.py`

**Minimal persistence:**
- `discovery_runs`: id, trigger (`manual|scheduled`), status, started/completed timestamps, query/source summary, candidate count, error.
- `discovery_candidates`: canonical URL, title/snippet, first/last seen, matched queries/sources, latest run.
- Additive `CREATE TABLE IF NOT EXISTS`; do not introduce a migration framework.

**Steps:**
1. Extract one `run_discovery(trigger)` function used by API and scheduler.
2. Generate useful queries when custom queries are empty from Roles & keywords + target location + work-mode preference; keep optional advanced custom phrases.
3. Seed the three preserved exploration phrases only when no role-derived/custom query exists.
4. Persist run start, success/error, deduplicated candidates, and an activity item.
5. Keep candidates distinct from fully ingested/analyzed jobs; never claim transient links are analyzed inbox jobs.
6. Make `POST /api/discovery/run` return run id, status, candidate count, and summary.
7. Add `GET /api/discovery/runs` and current/last run status.
8. Update the Inbox scan result with honest wording and a link to Activity/run detail.

**Verification:**
- Manual run with empty custom queries uses generated profile queries rather than returning 400.
- Duplicate URLs update candidate observations without duplicating rows.
- Provider failure produces a failed run with visible error.
- No employer contact or submission path is invoked.

### Task 8: App-owned schedule, next run, and platform/source settings

**Objective:** Let Toni understand and configure when/where JobFlow searches.

**Files:**
- Modify: `backend/jobflow/database.py`
- Modify: `backend/jobflow/models.py`
- Modify/Create: `backend/jobflow/scheduler.py`
- Modify: `backend/jobflow/main.py` lifespan
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`
- Test: new `backend/tests/test_scheduler.py`

**Settings:**
- schedule enabled;
- timezone (default `Europe/Vienna`);
- local run times (default `07:00`, `13:00`, `19:00`);
- enabled source modes and setup status;
- computed `next_run_at` and `last_run`.

**Source UI must be honest:**
- Broad web search via Firecrawl — configurable enabled/disabled, live connection state.
- Direct company/ATS discovery — available through reviewed/public web discovery, not represented as a magical universal scraper.
- karriere.at alerts — setup/status surface for AgentMail link ingestion; do not claim active until integrated.
- AMS — manual-only link intake.
- DEVjobs.at / DEVworkplaces — off by default with current policy status.
- Manual URL intake — enabled.

**Steps:**
1. Add the smallest in-process scheduler loop under FastAPI lifespan; one container/one Uvicorn worker is the supported initial deployment.
2. Poll minute boundaries, compute Europe/Vienna due slots, and guard each slot with a unique persisted run key so restarts do not double-run.
3. Expose `GET/PUT /api/automation` with schedule, next/last run, and source capability/status.
4. Build a **Search automation** section in Me and an operational summary in Activity.
5. Display `Next search`, `Last search`, schedule times, and enabled/setup-required platforms.
6. Keep a prominent `Search now` action using the same persisted run path as the scheduler.
7. Do not revive the paused Obsidian timers/crons; JobFlow becomes the owner.

**Verification:**
- Fake-clock tests cover next run before/after each slot and timezone daylight-saving behavior.
- Restart does not duplicate an already completed slot.
- UI always answers “what happens next and when?”
- Manual and scheduled runs appear in Activity with their trigger.

### Task 9: Secure Reactive Resume setup owned by JobFlow

**Objective:** Let a fresh installation connect Reactive Resume, select a reference CV, and expose status to the agent without exposing the API key.

**Files:**
- Modify: `pyproject.toml` only if a small audited encryption dependency is required
- Modify: `compose.yaml` / `.env.example` for `JOBFLOW_SECRET_KEY`
- Modify: `backend/jobflow/database.py`
- Create: `backend/jobflow/integrations.py` and/or `backend/jobflow/reactive_resume.py`
- Modify: `backend/jobflow/models.py`
- Modify: `backend/jobflow/main.py`
- Modify: `backend/jobflow/cli.py`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`
- Test: new `backend/tests/test_reactive_resume.py`

**Security contract:**
- API key is write-only.
- Responses return only connection state and optional masked suffix—not the key.
- Store encrypted credential data using an install-specific `JOBFLOW_SECRET_KEY`; never reuse the browser password and never log request bodies.
- Agent API/CLI can see `configured`, `verified`, base URL, reference resume metadata, and last error—never the credential.

**Steps:**
1. Add integration status/config storage and encryption.
2. Default base URL to `https://rxresu.me/api/openapi` but allow self-hosted Reactive Resume URLs.
3. Add connect/test/disconnect endpoints.
4. On test, list resumes and allow selection of a reference.
5. Auto-suggest `Hermes Canonical Base CV` when present; do not select `Hermes Starting Template` as the tailoring base.
6. Store reference resume ID/name and verify it exists on every explicit refresh.
7. Add read-only reference metadata endpoint and authenticated PDF proxy/download endpoint.
8. Add a Me **Reactive Resume** card with states:
   - Not connected / API key input + Connect;
   - Connected / reference CV selector;
   - Ready / canonical CV summary, last verified time, open/download preview;
   - Error / actionable retry without exposing provider response secrets.
9. Add CLI commands for integration status and reference metadata so the agent knows setup is required on a fresh install.
10. Preserve duplicate-only writes for job-specific resumes; no base mutation and no application submission.

**Verification:**
- Mocked tests verify header use, no key in JSON/errors/log representations, bad-key behavior, reference selection, and PDF proxy.
- Real read-only smoke test confirms `Hermes Canonical Base CV` is visible without printing personal CV payloads or the key.
- Source resume and canonical base remain unchanged.

### Task 10: Reference CV inside the app

**Objective:** Make the selected base CV inspectable from JobFlow.

**Files:**
- Primarily covered by Task 9 frontend/backend files

**Steps:**
1. Show reference name, template, last updated, one-page verification status if known, and connection health.
2. Provide `View reference CV` and `Download PDF` actions through authenticated JobFlow routes.
3. On mobile, open a dedicated white-surface CV view or system PDF viewer rather than embedding an unreadably small page permanently.
4. State explicitly: `Job-specific CVs are created as duplicates; this reference is never edited in place.`

**Verification:**
- Reference CV opens from Me on iPhone viewport.
- API key never appears in URL, DOM, client state, or network response.

### Task 11: End-to-end visual and operational verification

**Files:**
- No new framework unless needed; use current build/tests plus bounded browser scripts.

**Checks:**
1. `npm run build --prefix frontend`
2. `pytest -q backend/tests`
3. `git diff --check`
4. Docker build and one-container happy path.
5. Exact mobile captures at 428×926 and 390×844 for Inbox, Job Review, Me clean/dirty, Activity, Automation, and Reactive Resume setup/ready.
6. Desktop capture at 1440×900.
7. Click every primary action and inspect console/network errors.
8. Verify document remains viewport-locked; internal white surface scrolls; final controls clear the dock.
9. Direct irreversible-boundary checks:
   - no application submission endpoint introduced;
   - canonical Reactive Resume remains unchanged;
   - credential absent from API responses/logs/artifacts.
10. Commit/push and explicitly deploy through Dokploy; confirm production asset hashes before reporting live.

---

## Delivery sequence

To keep the first user-visible loop small and useful:

1. **Slice A — credibility/interaction fixes:** Tasks 1–6. Deploy together after mobile verification.
2. **Checkpoint:** show Toni clean/dirty Me, dual salary range, role tags, corrected icons, and real pulse history.
3. **Slice B — discovery operations:** Tasks 7–8. Deploy only when manual run persistence and next-run display are proven.
4. **Checkpoint:** show next schedule, platform statuses, manual run, and run history with real data.
5. **Slice C — Reactive Resume ownership:** Tasks 9–10. Treat credentials as the high-risk branch; verify key non-disclosure and canonical-CV immutability directly.
6. **Final production verification:** Task 11.

## Risks and trade-offs

- The current discovery endpoint returns links but does not create analyzed jobs. UI copy must distinguish candidates found from jobs fully processed; later agent orchestration must consume persisted candidates.
- An in-process scheduler is intentionally minimal and appropriate for the one-container deployment. If JobFlow later scales to multiple replicas, scheduler ownership must move to a singleton worker or external durable scheduler.
- Platform toggles must not imply adapters that do not exist. Setup-required/manual-only states are first-class states.
- API-key-in-UI is legitimate but security-sensitive. It requires encryption and write-only APIs; this is the only branch that warrants extra direct security checks.
- The preserved Obsidian implementation is a source of domain configuration, not machinery to revive. No dual Obsidian/PWA workflow.

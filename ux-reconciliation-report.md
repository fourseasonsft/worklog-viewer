# Worklog Viewer UX Reconciliation Report

Date: 2026-06-20

Scope:
- `/` dashboard
- `/intake`
- `/assistant`
- navigation
- thought box
- digest flow
- update shipment flow

Source references:
- [`app.py`](/opt/fsftdev/worklog-viewer/app.py)
- [`templates/base.html`](/opt/fsftdev/worklog-viewer/templates/base.html)
- [`templates/dashboard.html`](/opt/fsftdev/worklog-viewer/templates/dashboard.html)
- [`templates/intake.html`](/opt/fsftdev/worklog-viewer/templates/intake.html)
- [`templates/assistant.html`](/opt/fsftdev/worklog-viewer/templates/assistant.html)

## 1. Current Screen Inventory

### `/`
Primary command-center dashboard.

Evidence:
- Route: [`dashboard()`](/opt/fsftdev/worklog-viewer/app.py#L1338)
- Screen: [`templates/dashboard.html`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L1)

What it currently shows:
- Hero focus header with greeting, current focus, date, and top priority
- Quick capture form
- Today’s Focus panel with next actions and blockers
- Triage cards for recent inbox items
- Apps in motion cards for active work
- Hidden details area with portfolio status, where-we-left-off, latest daily log, and inbox snapshot

### `/intake`
Dedicated structured intake screen.

Evidence:
- Route: [`intake()`](/opt/fsftdev/worklog-viewer/app.py#L1349)
- Screen: [`templates/intake.html`](/opt/fsftdev/worklog-viewer/templates/intake.html#L1)

What it currently shows:
- Intake counts
- Structured form for title, type, app/project, priority, requested by, source, next action, plain-English summary, and technical notes
- Plain-English mode toggle
- Recent intake item cards

### `/assistant`
Thought capture and digest screen.

Evidence:
- Route: [`assistant()`](/opt/fsftdev/worklog-viewer/app.py#L1371)
- Screen: [`templates/assistant.html`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L1)

What it currently shows:
- Chat input for raw thoughts
- Digest Thought Box button
- Active thought table
- Conversation log
- Digest preview / approval panel
- Shipped/live update bundle panel

### Direct content/detail routes
These remain available as document-style navigation targets:
- `/roadmap`
- `/active-work`
- `/daily-logs`
- `/runbooks`
- `/inbox`
- `/inbox/new`
- `/inbox/bugs`
- `/inbox/features`
- `/inbox/support`
- `/inbox/closed`
- `/view/<path>`
- `/category/<path>` where exposed by the app

Evidence:
- Sidebar nav is defined in [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L138)
- Read-only document view is routed in [`view_file()`](/opt/fsftdev/worklog-viewer/app.py#L1517)

## 2. Current Navigation Map

### Persistent sidebar
Defined in [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L138).

Current sidebar destinations:
- Dashboard
- Assistant
- Portfolio Status
- Engineering Priorities
- Roadmap
- Active Work
- Daily Logs
- Runbooks
- Inbox
- Inbox / New
- Inbox / Bugs
- Inbox / Features
- Inbox / Support
- Inbox / Closed
- Decisions
- Release Notes
- Ideas

### Dashboard secondary navigation
Rendered at the top of [`templates/dashboard.html`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L18).

Current links:
- Dashboard
- Capture
- Today
- Inbox
- Apps
- Archive

### Intake navigation
Rendered in [`templates/intake.html`](/opt/fsftdev/worklog-viewer/templates/intake.html#L11).

Current links:
- Back to dashboard
- Plain-English mode / Technical view toggle
- Open source per item

### Assistant navigation
Rendered in [`templates/assistant.html`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L16).

Current links and actions:
- Back to dashboard
- Digest Thought Box
- Send
- Digest my thought box
- Approve Digest and Route Items
- Cancel / Keep Thoughts Raw
- View / Archive / Mark reviewed per thought

## 3. Duplicate Functionality

### A. Capture exists in three places
Evidence:
- Dashboard quick capture form: [`templates/dashboard.html#L41-L84`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L41)
- `/intake` structured form: [`templates/intake.html#L26-L63`](/opt/fsftdev/worklog-viewer/templates/intake.html#L26)
- `/assistant` raw thought input: [`templates/assistant.html#L24-L35`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L24)

Assessment:
- The dashboard, intake page, and assistant all accept new input.
- They are not identical, but the overlap is large enough that the user has to choose between three first-step capture surfaces.
- This is the most visible command-center redundancy.

### B. Digest preview has multiple triggers
Evidence:
- Button: [`templates/assistant.html#L18`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L18)
- Inline button: [`templates/assistant.html#L31`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L31)
- Chat command: [`assistant_message()`](/opt/fsftdev/worklog-viewer/app.py#L1393)
- Direct preview route: [`assistant_digest_preview()`](/opt/fsftdev/worklog-viewer/app.py#L1424)
- Optional query-param preview on `/assistant`: [`assistant()`](/opt/fsftdev/worklog-viewer/app.py#L1371)

Assessment:
- Four different ways now point to the same preview state.
- That is too many entry points for one conceptual action.

### C. Inbox and thought box are both intake queues
Evidence:
- Traditional inbox folders in the sidebar: [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L138)
- Thought box table on `/assistant`: [`templates/assistant.html#L38-L86`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L38)

Assessment:
- The inbox is the historical structured queue.
- The thought box is the new raw queue.
- Their relationship is still implicit rather than explicit in the UI hierarchy.

### D. Dashboard triage duplicates inbox browsing
Evidence:
- Triage cards: [`templates/dashboard.html#L129-L174`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L129)
- Direct inbox routes in sidebar: [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L138)

Assessment:
- Dashboard triage is a summary view of the same inbox data that the sidebar exposes directly.
- That is acceptable only if the triage cards are clearly read-only summaries, which they mostly are.

### E. Dashboard details duplicate direct document routes
Evidence:
- Hidden detail section on `/`: [`templates/dashboard.html#L212-L249`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L212)
- Sidebar direct routes for the same content: [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L138)

Assessment:
- Portfolio status, where-we-left-off, latest daily log, and inbox snapshot are shown both in the dashboard and as direct routes.
- The duplication is intentional, but the hidden detail block makes the dashboard feel like a second document browser.

### F. Assistant conversation log duplicates the thought table
Evidence:
- Thought table: [`templates/assistant.html#L38-L86`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L38)
- Conversation log: [`templates/assistant.html#L89-L107`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L89)

Assessment:
- Both surfaces render the same raw thoughts.
- One is operationally useful; the other is redundant unless it is explicitly framed as a conversational transcript.

### G. “Updates” and “Release Notes” are adjacent but not unified
Evidence:
- Assistant update shipment panel: [`templates/assistant.html#L147-L166`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L147)
- Sidebar `Release Notes`: [`_nav_items()`](/opt/fsftdev/worklog-viewer/app.py#L154)

Assessment:
- The assistant uses “Updates” for shipped/live bundles.
- The sidebar exposes a general Release Notes area.
- The two are close in meaning but not the same workflow, which creates naming ambiguity.

## 4. Incomplete Workflows

### A. Triage actions are placeholders
Evidence:
- Disabled buttons on the dashboard triage cards: [`templates/dashboard.html#L158-L163`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L158)

Status:
- `Promote`, `Archive`, and `Mark reviewed` are present but inactive.

Impact:
- These buttons imply a curation workflow that does not exist yet.
- They read as unfinished UI rather than intentional read-only affordances.

### B. Thought review actions are only partly real
Evidence:
- Assistant archive button: [`assistant_archive_thought()`](/opt/fsftdev/worklog-viewer/app.py#L1503)
- Assistant reviewed button handler: [`templates/assistant.html#L337-L343`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L337)

Status:
- `Archive` works.
- `Mark reviewed` only changes the on-page status text.

Impact:
- The UI suggests a state transition, but the underlying workflow is not implemented.

### C. Digest approval does not show a durable routing plan before action
Evidence:
- Approval handler: [`assistant_approve_digest()`](/opt/fsftdev/worklog-viewer/app.py#L1437)
- Preview renders proposed items: [`templates/assistant.html#L113-L140`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L113)

Status:
- Preview shows grouped proposals.
- Approval immediately creates routed work items, moves raw thoughts to `digested/`, and writes an update record.

Impact:
- The user can review the proposal, but the UI does not provide a separate preflight screen for “this exact set of files will change.”

### D. Update shipment flow is visible but not connected
Evidence:
- Update records are written here: [`_write_update_shipment_record()`](/opt/fsftdev/worklog-viewer/app.py#L618)
- The assistant displays them here: [`templates/assistant.html#L147-L166`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L147)

Status:
- The system records shipped/live bundles.
- The UI does not expose a path from a shipped update back to the created Worklog item set or source thoughts.

Impact:
- “Update” reads like a lifecycle endpoint, but it is not wired into the rest of the Worklog traceability model.

### E. Thought grouping / Thought Orders are not first-class in navigation
Evidence:
- Digest preview logic groups thoughts in code: [`_digest_groups_from_items()`](/opt/fsftdev/worklog-viewer/app.py#L576)
- UI labels refer to “Thought Order digest” and “Proposed items”: [`templates/assistant.html#L110-L140`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L110)

Status:
- The concept exists in the UI and code.
- There is no separate view or route for Thought Orders.

Impact:
- Thought Orders are a hidden internal construct rather than an explicit user-facing stage.

## 5. Orphaned UI Elements

### Dashboard
- Disabled `Promote` button.
- Disabled `Archive` button.
- Disabled `Mark reviewed` button.
- Hidden `<details>` area that feels like a second dashboard.

Evidence:
- [`templates/dashboard.html#L158-L163`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L158)
- [`templates/dashboard.html#L212-L249`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L212)

### Assistant
- Duplicate `Digest Thought Box` and `Digest my thought box` actions.
- Conversation log duplicates the active thought table.
- `Mark reviewed` does not persist anything.
- Shipped/live update section sits below the main assistant workflow and is easy to miss.

Evidence:
- [`templates/assistant.html#L16-L19`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L16)
- [`templates/assistant.html#L24-L35`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L24)
- [`templates/assistant.html#L38-L107`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L38)
- [`templates/assistant.html#L147-L166`](/opt/fsftdev/worklog-viewer/templates/assistant.html#L147)

### Intake
- The intake page is functionally sound, but it overlaps heavily with dashboard quick capture.
- It does not have the same “command center” role as the dashboard, so it feels like a secondary form rather than a distinct workflow stage.

Evidence:
- [`templates/dashboard.html#L41-L84`](/opt/fsftdev/worklog-viewer/templates/dashboard.html#L41)
- [`templates/intake.html#L26-L63`](/opt/fsftdev/worklog-viewer/templates/intake.html#L26)

## 6. Recommended Final User Flow

### Recommended hierarchy
1. **Dashboard**
   - Primary home screen
   - Answers: “What needs attention now?”
   - Shows focus, next actions, blockers, triage, and concise status summaries
   - Keeps capture available, but secondary

2. **Assistant**
   - Secondary raw-thought capture and digestion surface
   - Answers: “What am I trying to say?”
   - Handles:
     - raw thought capture
     - thought grouping
     - digest preview
     - approval gating
     - update shipment history

3. **Intake**
   - Structured creation screen for deliberate Worklog items
   - Best for:
     - bugs
     - features
     - support items
     - customer requests

4. **Inbox / Active Work / Release Notes**
   - Review surfaces for things already captured or routed
   - Should remain available, but not compete with the dashboard for first-screen attention

### Final flow recommendation

Capture first. Group second. Digest third. Approve fourth. Ship fifth.

That should map to:
- **Dashboard** for attention and status
- **Assistant** for raw thoughts and Thought Orders
- **Intake** for structured item creation
- **Inbox** for routed items
- **Update shipments** for shipped/live history

## 7. Conclusion

The current viewer is directionally right, but it is still carrying three overlapping mental models:
- command center
- intake form
- chat assistant

The main UX risk is not missing capability. The risk is that the UI now shows too many ways to do the same thing before the user has a reason to choose between them.

Before any further development, the Worklog should be reduced to a simpler model:
- dashboard = decide
- assistant = think
- intake = enter structured work
- inbox = review routed work
- updates = record shipped/live outcomes

Anything that does not directly support one of those five roles should be merged, demoted, or removed.

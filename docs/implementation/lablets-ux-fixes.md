# Lablets View — Core UX Fixes

**Status**: 🔧 In Progress
**Started**: 2026-02-09
**Last Updated**: 2026-02-09
**Branch**: (current working branch)

## Overview

Critical UX fixes for the Lablets view — the primary user interaction surface for creating and managing lablet instances and definitions.

## Tasks

### ✅ 1. Fix BaseComponent cleanup error

**File**: `ui/src/scripts/core/BaseComponent.js`
**Issue**: `TypeError: e is not a function` when switching views. `cleanup()` calls subscriptions as functions, but `@neuroglia/ui-core` `EventBus.on()` returns `Subscription` objects with `.unsubscribe()` method.
**Fix**: Handle both callable functions and Subscription objects in `cleanup()`.

### ✅ 2. Make metrics tiles collapsible with localStorage persistence

**File**: `ui/src/scripts/components/pages/LabletsPage.js`
**Changes**:

- Wrap metrics row in collapsible container with toggle header
- Persist collapsed/expanded state in `localStorage` key `lcm.lablets.metricsCollapsed`
- Remove standalone lookup panel entirely

### ✅ 3. Move reservation lookup inline to datatable header

**File**: `ui/src/scripts/components/pages/LabletsPage.js`
**Changes**:

- Add reservation ID search input to the Active and All tab table headers, alongside Region/Status filters
- Remove the old collapsible lookup card

### ✅ 4. Fix modal backdrop transparency

**File**: `ui/src/scripts/components/pages/LabletsPage.js`
**Issue**: `_openCreateModal()` creates a new `bootstrap.Modal(modal)` each time, which can stack backdrops.
**Fix**: Use `Modal.getOrCreateInstance()` instead of `new Modal()`.

### ✅ 5. Wire Definition dropdown in create instance modal

**Files**: `ui/src/templates/components/lablet_instances.jinja`, `ui/src/scripts/ui/lablet-modals.js`
**Changes**:

- Replace text search input with a proper `<select>` dropdown
- Populate dropdown with active lablet definitions on modal show
- Show definition preview card when selection changes
- Add `updateLabletDefinition()` and `deleteLabletDefinition()` to API client

### ✅ 6. Wire Definitions tab actions

**Files**: `ui/src/scripts/components/pages/LabletsPage.js`, `ui/src/scripts/ui/lablet-modals.js`
**Changes**:

- **View**: Click row or eye icon → open details modal with full definition info
- **Edit**: Pencil icon → open edit modal (reuse create modal with prepopulated fields)
- **Create Instance**: Rocket icon → open create instance modal with preselected definition
- **Delete**: Trash icon → open confirmation modal, call delete API on confirm

### ⬜ 7. Build and verify

- Run `make clean build-ui`
- Test in browser: view switching, create instance, create/edit/delete definition
- Verify SSE data flow works correctly

## Files Modified

| File | Changes |
|------|---------|
| `ui/src/scripts/core/BaseComponent.js` | Fix cleanup() to handle Subscription objects |
| `ui/src/scripts/components/pages/LabletsPage.js` | Collapsible metrics, inline lookup, definition actions |
| `ui/src/scripts/ui/lablet-modals.js` | Definition dropdown, edit modal, delete confirmation |
| `ui/src/templates/components/lablet_instances.jinja` | Replace search input with select dropdown |
| `ui/src/scripts/api/lablet-definitions.js` | Add update/delete API functions |

## Design Decisions

- **Metrics collapsible state**: Stored in `localStorage` with key `lcm.lablets.metricsCollapsed`
- **Definition dropdown**: Populated on modal show via `listLabletDefinitions({status: 'active'})` — no search input needed since definitions are a bounded set
- **Edit definition**: Reuse create modal with prepopulated fields and changed title/button text
- **Modal pattern**: Use `Modal.getOrCreateInstance()` to avoid stacking backdrops

## Follow-up Items

- Consider pagination for definitions if list grows beyond 50+
- Add definition version comparison view
- Improve SSE granularity (per-instance updates vs full refresh)

{"name": "wireframes", "description": "Use when the user asks to design, sketch, mock up, or redesign UI screens and the workflows between them, when proposing how an app's screens should look or connect, when the user asks for wireframes/lo-fi mockups, or when revising a wireframe pack after user feedback or inline edits.", "triggers": ["wireframe", "screen design", "mockup", "lo-fi design", "redesign this screen", "how should the screens work", "UI flow"]}

# Wireframes — authoring screen-design packs

## Overview

A wireframe pack is a versioned artifact (screens + flows) the user sees rendered in the Artifacts tab: lo-fi grayscale screen canvases, a clickable flow map, and a per-screen `implement` button. You author packs with `emit_wireframe`; the user revises by chatting or by editing the pack inline. **The pack is the spec** — an implement prompt says "treat that artifact as the spec", so what you emit is what gets built.

## When to propose a pack

- The user asks for new screens, screen redesigns, or screen-to-screen workflows.
- You are about to build a multi-region screen and alignment on layout would be cheap now, expensive later.
- Do NOT emit packs for single trivial components — a pack is for screens and their workflows.

## Authoring rules

1. **Redesigns: read the current screen first.** Before re-emitting a pack for screens that exist, actually read the live implementation (file tools / `reveal_code` / the running DOM), and cite in region `notes` what you kept vs changed and why. Never redesign from imagination.
2. **Lo-fi: structure over polish.** Regions, hierarchy, and flows — no colors, fonts, spacing detail, or brand styling. If a `notes` field talks about visual styling, delete it; that is a later, themed pass.
3. **Name only real mechanisms.** Reference only what exists: the Artifacts tab, the flow map (click a node/edge to focus a screen), the per-screen `implement` button, inline pack edits. Do not invent panels, comparison views, or export paths.
4. **One pack per screen-set.** All screens of one workflow go in one pack so the flow map shows the whole picture.

## DSL v1 reference

```json
{
  "version": 1,
  "screens": [
    {"id": "settings", "title": "Settings",
     "template": "\"header header\" \"nav theme\"",
     "regions": [
       {"name": "header", "widget": "header", "label": "Settings", "notes": "one line, functional only"}]}
  ],
  "flows": [{"from": "settings", "to": "profile", "trigger": "click nav item", "label": "edit profile"}]
}
```

- `template`: CSS grid-template-areas, quoted rows. Every region `name` must appear in its screen's template (a `'.'` filler cell is fine).
- `widget` vocabulary: `nav, header, form, table, list, text, chart, actions, tabs, image, code, placeholder` — unknown values render as a generic box, but prefer the vocabulary.
- `flows` `from`/`to` must reference existing screen ids. `trigger`/`label` optional. A single screen needs no flows.
- Unknown extra keys are tolerated; structural violations come back as ONE error listing every problem — fix all of them, then re-emit the whole pack.

## Revision etiquette

- Any change the user asks for in chat → **re-emit the whole pack** (newest-first in the tab). Never emit a "delta" pack or a partial pack.
- Inline edits the user made to the previous pack are **requirements**: read the pack's feedback (`get_artifact_feedback`) before re-emitting, and incorporate every edit — your re-emission replaces their text, so dropping an edit destroys their work.
- Say in one sentence what changed in the re-emitted pack.

## Handoff format

Per screen, the UI's `implement` button prefills the composer with: `Implement the "<screen title>" screen from wireframe pack "<pack title>" (<artifact id>); treat that artifact as the spec.` When the user asks you to implement a screen yourself, use that same directive shape and actually read the pack artifact before coding.

## Common mistakes

| Mistake | Reality |
| --- | --- |
| Emitting styled/branded mockups | Lo-fi only — the themed pass comes later |
| "Delta" or partial packs on revision | Always re-emit the complete pack |
| Ignoring the user's inline edits | Their edits are requirements; read feedback first |
| Redesigning without reading the current screen | Read first, cite keeps/changes in `notes` |
| Inventing rendering features (comparison views, exports) | Only the Artifacts tab, flow map, implement button exist |
| One region name missing from `template` | Validation fails — check every region against the template before emitting |

## Success Signal

Your pack passed `emit_wireframe` validation on the first try (no violation list came back); for redesigns your region notes cite concrete current-UI facts; after user feedback you re-emitted one complete pack that visibly incorporates every inline edit.

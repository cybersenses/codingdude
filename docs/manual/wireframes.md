# Wireframes

Up: [User Manual](../USER-MANUAL.md) · Back to [Panels](panels.md)
Wireframes are how the agent shows you screen designs and the workflows
between them. Ask for "a wireframe of the config screen" or "redesign the
settings page" and the agent emits a **wireframe pack** — a versioned
artifact rendered right in the [Artifacts tab](panels.md#artifacts).

## What a pack is

A pack is one JSON document (DSL v1) listing:

- **screens** — each a lo-fi canvas: a CSS-grid `template`, optional
  `columns`/`rows` proportions (the agent should always author these —
  relative sizes are what make the drawing read as a layout), and the regions
  on it (`nav`, `form`, `table`, …). Every screen renders in a fixed 16:10
  frame with a title bar, and each known widget draws a small sketch inside
  its region — nav bars, a chart squiggle, form fields — rather than a text
  tag; region notes are hover text, kept out of the drawing.
- **flows** — the edges between screens (`from`, `to`, a trigger, a label).

Structure is validated the moment the agent emits: a broken pack comes back
as one readable error listing every problem, so the agent fixes all of them
and re-emits. Unknown widget names and extra fields are tolerated and render
generically, so a slightly imperfect pack still shows you something.

## Reading the flow map

Below the screen canvases sits the **flow map**: one box per screen (its
title and region count), one arrow per workflow edge, trigger and label
texts on hover. Click a box (or an arrow — it focuses the destination
screen) to focus: the focused screen's canvas is highlighted and scrolled
into view, and the edges touching it light up. Click the focused screen's
title again to clear focus.

## Editing a pack inline

The pack's DSL source is the spec. Edit it right in the Artifacts card and
save — the agent reads your edit back via its feedback tool and treats it as
a **requirement**: its next revision re-emits the *whole* pack (the tab is
newest-first) with your edit incorporated, never a delta.

## Implement handoff

Every screen canvas has an **implement** button. It prefills the composer
with a directive naming the screen, the pack, and the artifact id — "treat
that artifact as the spec" — so a run starts from exactly what you approved.
Sending it stays your call.

## Lo-fi now, styled later

Packs are deliberately lo-fi: grayscale boxes and structure, no colors or
brand styling — structure first, skin later. A `theme` prop already exists
on the renderer (defaulting to `lofi`); wiring real themes into it is a
planned future step, not a shipped one.

## Worked example — "design the config screen and its flow"

Ask: *"Wireframe the config screen — provider settings and appearance — and
the flow to a profile screen."* The agent emits one pack:

```json
{
  "version": 1,
  "screens": [
    {
      "id": "settings", "title": "Settings",
      "template": "\"header header\" \"nav main\"",
      "columns": [28, 72],
      "rows": [1, 3],
      "regions": [
        {"name": "header", "widget": "header", "label": "Settings", "notes": "screen title"},
        {"name": "nav", "widget": "nav", "label": "Sections", "notes": "Appearance · Providers · Profile"},
        {"name": "main", "widget": "form", "label": "Provider settings", "notes": "provider, key (write-only), base URL"}
      ]
    },
    {
      "id": "profile", "title": "Profile",
      "template": "\"header header\" \"avatar details\"",
      "columns": [30, 70],
      "rows": [1, 3],
      "regions": [
        {"name": "header", "widget": "header", "label": "Profile", "notes": "back to Settings"},
        {"name": "avatar", "widget": "image", "label": "Avatar", "notes": "upload control"},
        {"name": "details", "widget": "form", "label": "Details", "notes": "display name, email"}
      ]
    }
  ],
  "flows": [
    {"from": "settings", "to": "profile", "trigger": "click Profile in nav", "label": "edit profile"},
    {"from": "profile", "to": "settings", "trigger": "click back", "label": "return"}
  ]
}
```

The Artifacts tab renders both canvases and the flow map. You click
`Profile` in the map — the profile canvas highlights. You edit the pack
inline: rename `Provider settings` to `Providers (user edit)` and save. You
say *"looks right, but add an appearance section"*. The agent reads your
edit back, re-emits the whole pack — newest-first, your rename kept, the
appearance region added — and you click **implement** on the settings
canvas when it looks right.

# Design System

## Theme Decision
Scene: A government archivist sits at a Windows workstation in a documentation office, fluorescent overhead lights, mid-afternoon. She has 80 PDFs queued. She starts the job and watches progress while annotating a paper form. Dark-but-not-black: reduces eye strain under fluorescent light during long sessions, prevents the bright-white bleed of a light theme on high-contrast monitors, keeps the output text (which will be dense Vietnamese characters) maximally legible. Not pure OLED black — that's too dramatic for a government office tool.

## Color Strategy
Restrained. Background family carries ~90% of the surface. One blue accent for interactive state and primary action feedback. Amber for the one CTA (run). Red for stop/error only.

## Color Tokens (OKLCH)
- `--bg-base`: oklch(9% 0.008 255)         /* near-black, blue tint */
- `--bg-surface`: oklch(11% 0.008 255)      /* panel backgrounds */
- `--bg-elevated`: oklch(14% 0.008 255)     /* cards, inputs */
- `--bg-overlay`: oklch(17% 0.008 255)      /* dropdowns, tooltips */
- `--border-subtle`: oklch(22% 0.010 255)   /* dividers */
- `--border-default`: oklch(28% 0.010 255)  /* input borders */
- `--text-primary`: oklch(94% 0.008 255)    /* main readable text */
- `--text-secondary`: oklch(65% 0.010 255)  /* labels, metadata */
- `--text-disabled`: oklch(38% 0.008 255)   /* disabled states */
- `--accent-blue`: oklch(62% 0.18 255)      /* interactive, selected, progress */
- `--accent-blue-dim`: oklch(30% 0.12 255)  /* active tab underline bg */
- `--cta-amber`: oklch(70% 0.17 60)         /* run button */
- `--cta-amber-hover`: oklch(62% 0.17 60)   
- `--error-red`: oklch(60% 0.20 25)         /* stop, error states */
- `--success-green`: oklch(62% 0.16 155)    /* done, badge-original */

## Typography
- Body: "Be Vietnam Pro", "Noto Sans", "Segoe UI", sans-serif — 10.5pt base, weight 400
- Labels/metadata: 9pt, weight 500–600, letter-spacing 0.02em
- Headings in panel: 11pt, weight 700
- Monospace (OCR output): "Consolas", "Courier New", monospace — 10pt
- Line-height body: 1.55
- Tab labels: 9.5pt, weight 600

## Elevation Model
Three surfaces only. No shadows — elevation via background lightness delta.
1. Base (--bg-base): the window chrome
2. Surface (--bg-surface): panels, sidebar, output area
3. Elevated (--bg-elevated): inputs, list items, field values

## Spacing Scale
4px base unit. Common steps: 4, 8, 12, 16, 24, 32.
Toolbar: 48px fixed height. Sidebar: 280px default.

## Component Notes
- Buttons: 6px radius, 7px 14px padding. CTA (run) is amber, full weight 700.
- Tabs: no pane border on active. Underline-only active indicator, 2px, accent-blue.
- List items: 4px radius, 6px 8px padding. Selected = bg-overlay + blue left-edge 2px.
- Progress bar: 4px height, no text inside, accent-blue fill.
- Badges (loai_ban): pill shape, color-coded: green=gốc, blue=chính, amber=photo, gray=unknown.
- Status bar: 32px height, secondary text, border-top only.
- Field extraction grid: label right-aligned, 90px min-width; value full-width with bg-elevated bg.

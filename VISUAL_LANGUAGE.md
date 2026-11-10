# Raleigh 311 Civic Equity — Visual Language

A single design system for all static charts, maps, and exploratory graphics in this project. Optimized for **transparent PNG exports** that layer cleanly on slides, reports, and light or dark backgrounds.

---

## Typography

| Role | Font | Weight | Size |
|------|------|--------|------|
| Chart title | Open Sans | 600 (Semibold) | 15 pt |
| Panel / subplot title | Open Sans | 600 (Semibold) | 13 pt |
| Axis labels | Open Sans | 400 (Regular) | 12 pt |
| Tick labels | Open Sans | 400 (Regular) | 10 pt |
| Legend | Open Sans | 400 (Regular) | 10 pt |
| Footnotes & captions | Open Sans | 400 (Regular) | 9 pt |
| Data annotations (ZIP labels, etc.) | Open Sans | 600 (Semibold) | 8 pt |

**Rules**
- One family only: **Open Sans** (system install with DejaVu Sans fallback in code).
- Titles are always semibold; all other text is regular weight.
- No italics except for statistical notation in trend-line labels.

---

## Color Palette

### Core neutrals
| Token | Hex | Use |
|-------|-----|-----|
| `ink` | `#1B2838` | Primary text, median reference lines |
| `muted` | `#5A6B7D` | Secondary text, axis ticks, captions |
| `border` | `#C5CDD6` | Spines, gridlines, polygon outlines |
| `fill_subtle` | `#E8EDF2` | Annotation backgrounds (80% opacity) |

### Semantic accents
| Token | Hex | Use |
|-------|-----|-----|
| `wealthy` | `#1F8A7A` | Top 20% income segment, fast / low neglect |
| `low_income` | `#D4624A` | Bottom 20% income segment, slow / high neglect |
| `scatter` | `#4A6073` | Scatter plot points |
| `trend` | `#1F6F5F` | Regression / trend lines |
| `point_edge` | `#FFFFFF` | Point and bar outlines on transparent canvas |

### Sequential scale (neglect rate, choropleth)
Low → high neglect:

1. `#1F8A7A` — Teal (low neglect)
2. `#E3A008` — Amber (moderate)
3. `#C94C4C` — Coral red (high neglect)

### Income choropleth (presentation)
Light → dark green (darker = wealthier):

`#D4EDE6` → `#7FBFB3` → `#1F8A7A` → `#0D5C4D`

### Wait-time choropleth (presentation)
Light → dark red (darker = slower):

`#FCE8E6` → `#E88880` → `#C94C4C` → `#7F1D1D`

Use this same three-stop scale in Folium maps, matplotlib choropleths, and colorbars.

---

## Layout & Structure

- **Background:** Fully transparent on all PNG exports (`savefig.transparent=True`).
- **Spines:** Remove top and right; left and bottom use `border` at 100% opacity.
- **Grid:** Horizontal only where helpful; `border` at 35% opacity, dashed optional.
- **Data-ink ratio:** No chart junk, no heavy borders, no drop shadows on charts.
- **Figure sizes:** 10×6.5 in (standard chart), 12×5.5 in (dual panel), 12×10 in (map).
- **Export:** 300 DPI PNG, `bbox_inches='tight'`.

---

## Chart-Specific Guidance

### Scatter plots
- Point size encodes volume; fill `scatter`, edge `point_edge`.
- Trend line: dashed, `trend`, 2.2 px.
- ZIP annotations in `muted`, 8 pt semibold.

### Grouped bar charts
- Wealthy segment: `wealthy`; low-income segment: `low_income`.
- Bar edge: `point_edge`, 0.8 px.
- Categories ordered by insight (gap magnitude or neglect rank), not alphabetically.

### Distribution plots
- Same segment colors as bar charts.
- Median reference line: `ink`, dashed.
- KDE + histogram at 55% fill opacity.

### Choropleth map (static PNG)
- Transparent canvas; ZIP polygons filled with sequential scale.
- Polygon outline: `border`, 1.6 px.
- ZIP labels: semibold, `ink`, on `fill_subtle` rounded badge.

### Interactive map (Folium HTML)
- Basemap: CartoDB Positron (light, minimal).
- Polygon styling matches sequential scale and `border` outlines.
- UI typeface: Open Sans via inline CSS.

### Request breakdown illustration
- Flat vector buckets with ink outlines; no gradients or shadows.
- Parent bucket: `fill_subtle`; children use task-hint colors (blue-gray, green, rose).
- Export as SVG (primary) and transparent PNG.

### Side-by-side comparison maps (presentation)
- Two **separate** PNGs with identical framing for slide pairing.
- Left: income scale (green). Right: service wait scale (red).
- ZIPs with no service data use `fill_subtle`.

---

## File Map

| Module | Role |
|--------|------|
| `viz_theme.py` | Palette, fonts, `apply_chart_style()`, `save_figure()` |
| `charts.py` | Main analysis charts (`output/`) |
| `deep_dive.py` | EDA charts (`output/eda/`) |
| `zip_choropleth/build_viz.py` | Map + paired bars (`zip_choropleth/output/`) |
| `presentation/build_graphics.py` | Story illustration + dual choropleth maps (`presentation/output/`) |
| `map_builder.py` | Point-level Folium map (`output/`) |

Regenerate all assets:

```bash
python main.py
python deep_dive.py
python zip_choropleth/build_viz.py
python presentation/build_graphics.py
```

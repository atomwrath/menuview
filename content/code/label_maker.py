"""
label_maker.py — anywidget label designer for printing recipe labels.

Turns a recipe (or a selection of its rows) into a printable label:
a live, true-to-size preview plus two zero-dependency export paths —

    PNG      the label SVG rasterized to a canvas at exactly the chosen
             printer DPI (203 dpi covers most thermal label printers,
             300/600 for laser/inkjet label sheets), downloaded via a
             blob URL. No resampling anywhere, so 3in × 1in @ 203 dpi
             is exactly 609 × 203 px.
    Print /  a popup window whose stylesheet sets
    PDF      @page { size: <w>in <h>in; margin: 0 } and repeats the SVG
             once per requested copy — the browser's own print dialog
             then drives the label printer directly, or "Save as PDF"
             produces a correctly-dimensioned PDF. No PDF library.

Everything renders client-side (browser), so it behaves identically in
JupyterLab Desktop and JupyterLite/Pyodide, and both export actions run
inside a click handler (popup blockers and iPad Safari downloads are
both fine with that).

Layout
    The label itself is composed as a standalone SVG (inline presentation
    attributes only — no CSS classes — so the exact same markup previews
    in the DOM and rasterizes on a canvas without a stylesheet). A hidden
    canvas 2D context measures text; the base font size is found by
    binary search: the largest size at which the whole label fits the
    requested dimensions (this "auto-fit" size is always what 100% means
    for the text_scale control below). Title is bold at 1.15×, the date
    sits in the top-right corner at 0.85×. Black on white always —
    labels don't follow the notebook theme.

    Only the title's first line shares a row with the date (see
    wrapFirstLineNarrow), and that line is wrapped -- and separately
    checked for fit -- against the real space actually left once the date
    claims its corner, not a fraction of the label's full width. That
    real space can be small or negative when a wide date badge shares a
    small label with a long title; when it is, "fits" correctly comes
    back false and the binary search backs off to a smaller font (which
    shrinks the date too), rather than letting the two silently overlap.
    This matters most exactly when there's no ingredient body to also
    constrain the font size -- a label with just Title + Date has nothing
    else limiting how large the auto-fit font grows.

    Two independent column selections feed the label: `columns` picks
    which fields appear per ingredient in the body (Table or List
    format); `header_columns` separately picks which fields from the
    recipe's own top row (yield, total cost, etc.) appear as a subtitle
    under the title. 'ingredient' isn't offered for header_columns since
    that's just the recipe name, already shown as the title itself.

    Table format: the first selected column (usually 'ingredient')
    word-wraps; the remaining columns are packed to the right edge,
    right-aligned, never wrapped.

    List format: every selected column from every ingredient is
    concatenated into one continuous, comma-separated paragraph that
    word-wraps across the full label width -- no per-row bullets, no
    columns, just plain running text (the style used on packaged-food
    ingredient declarations).

    An optional free-text note (label_note, e.g. "Keep refrigerated")
    renders as a small italic footer line below the ingredient content,
    in either format, whenever the Note field isn't blank.

    text_scale applies on top of the auto-fit size (0.5–2.0×, ±10% per
    click) so the person printing can trade a smaller, more breathable
    label for the maximum-legibility default, or push past it and accept
    some clipping — the preview's warning banner covers both cases.

Data flow
    The kernel fills title / date_str / all_columns / header_row / rows_all /
    rows_selection once when the widget is created (rows and header_row are
    plain {column: display-string} dicts, pre-formatted by the caller so
    numbers look exactly like they do in the grid; header_row carries
    *every* non-'item' column from the recipe's own top row, not just the
    selected ones -- header_columns, an independent trait, then picks
    which of those actually render). Column choices, size, DPI, format
    style, text scale, and the show/hide toggles are synced traits the
    browser writes back, so the kernel can preset them and they survive
    a re-render. Scope (selection vs whole recipe) is browser-local state,
    normally auto-detected from whether rows_selection is non-empty but
    overridable via initial_scope (see its trait comment) for callers that
    have no row selection of their own to offer, like a sheet-level "Make
    label…" action.

    date_str always arrives as "MM/DD/YYYY"; show_date and show_year are
    independent toggles -- Date controls whether any date text shows at
    all, Year (only relevant when Date is on) controls whether the
    trailing "/YYYY" is included, so a label can show just "07/17" for
    day-to-day use or the full date when the year actually matters.

    Those same options (columns, header_columns, size, dpi, format_style,
    text_scale, toggles, copies) are persisted to SETTINGS_FILE
    (label_settings.json, in the notebook's working directory) on every
    change and reloaded the next time a LabelMakerWidget is constructed —
    "last used" survives across labels and kernel restarts, no separate
    Save button. A fresh install starts at 203 dpi (common thermal-printer
    resolution) and 100% text scale until something else gets saved.
    Content (title, date, header_row, rows) is per-use and never persisted.

Format styles
    'table'  the original layout: first column wraps, remaining columns
             pack right-aligned to the edge — reads like a nutrition
             panel. Best when a couple of the columns are short numbers
             (quantity, cost) that benefit from lining up.
    'list'   every chosen column from every ingredient concatenated into
             one continuous, comma-separated paragraph that wraps across
             the full label width — no bullets, no columns, just running
             text (packaged-food ingredient-declaration style). Column
             headers don't apply in this style.
"""

import json
import os

import anywidget
import traitlets
import sys

SETTINGS_FILE = 'label_settings.json'   # last-used export settings, in cwd

# Traits that are a *preference* (size, columns, dpi, format...) rather
# than content tied to one particular recipe (title, date, rows) — these
# are the ones that get persisted across labels/sessions.
_PERSISTED_TRAITS = (
    'columns', 'header_columns', 'width_in', 'height_in', 'dpi', 'format_style',
    'show_date', 'show_year', 'show_title', 'show_headers', 'copies', 'text_scale',
    'initials',
)

_IS_PYODIDE = (sys.platform == 'emscripten')

# In-memory fallback for Pyodide -- see _on_persisted_change below for why
# disk writes are avoided there. Module-level so "last used" still carries
# from one label to the next within the same kernel session; it just can't
# survive a full page reload the way the on-disk copy does on Desktop.
_session_settings = {}


def _load_settings():
    if _IS_PYODIDE:
        return dict(_session_settings)
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}   # malformed/unreadable file -- fall back to trait defaults


def _save_settings(values):
    if _IS_PYODIDE:
        _session_settings.update(values)
        return
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(values, f, indent=2)
    except Exception:
        pass   # best-effort -- a failed save shouldn't block printing a label


class LabelMakerWidget(anywidget.AnyWidget):
    # ── content (kernel → browser, set once at creation) ─────────────────
    title          = traitlets.Unicode('').tag(sync=True)
    date_str       = traitlets.Unicode('').tag(sync=True)
    all_columns    = traitlets.List(traitlets.Unicode()).tag(sync=True)
    header_row     = traitlets.Dict().tag(sync=True)   # {col: str} -- the
                                                          # recipe's own top
                                                          # row (yield, total
                                                          # cost, etc.), shown
                                                          # as a subtitle when
                                                          # Title is on
    rows_all       = traitlets.List().tag(sync=True)   # list[{col: str}]
    rows_selection = traitlets.List().tag(sync=True)   # list[{col: str}]
    initial_scope  = traitlets.Unicode('').tag(sync=True)
                                    # '' (default) -- auto-detect: start on
                                    # "Selection" if rows_selection is
                                    # non-empty, else "Whole recipe" (the
                                    # original behavior, used by the per-row
                                    # "Make label…" menu).
                                    # 'selection' / 'all' -- force that radio
                                    # regardless of rows_selection's length.
                                    # Used by the sheet-level "Make label…"
                                    # action, which has no row selection of
                                    # its own: it passes rows_selection=[]
                                    # and initial_scope='selection', so the
                                    # label opens showing just the title/
                                    # subtitle (no ingredient body) instead
                                    # of quietly defaulting to the whole
                                    # recipe.

    # ── options (two-way; browser writes back on every control change;
    #    persisted to SETTINGS_FILE -- see __init__ below) ────────────────
    columns        = traitlets.List(traitlets.Unicode(),
                                    default_value=['ingredient', 'quantity']).tag(sync=True)
    header_columns = traitlets.List(traitlets.Unicode(),
                                    default_value=['quantity', 'cost']).tag(sync=True)
                                    # which header_row fields show in the
                                    # title subtitle -- independent of
                                    # `columns` above, which is the
                                    # ingredient body's column selection
    width_in     = traitlets.Float(3.0).tag(sync=True)
    height_in    = traitlets.Float(1.0).tag(sync=True)
    dpi          = traitlets.Int(203).tag(sync=True)          # thermal-label default
    format_style = traitlets.Unicode('table').tag(sync=True)  # 'table' | 'list'
    show_date    = traitlets.Bool(True).tag(sync=True)   # shows the month/day portion
    show_year    = traitlets.Bool(True).tag(sync=True)   # shows the year portion -- independent
                                                          # of show_date, so Year alone (Date off)
                                                          # displays just the year on its own
    show_title   = traitlets.Bool(True).tag(sync=True)
    show_headers = traitlets.Bool(False).tag(sync=True)  # column-name labels: both the table's
                                                          # own header row AND the "field: value"
                                                          # labels in the title-row subtitle
    copies       = traitlets.Int(1).tag(sync=True)
    text_scale   = traitlets.Float(1.0).tag(sync=True)   # manual +/- on top of auto-fit
    initials     = traitlets.Unicode('').tag(sync=True)  # e.g. "JS" -- displays next to the date

    # ── free-text note (two-way, browser-typed) -- deliberately NOT in
    #    _PERSISTED_TRAITS. Unlike the options above, a note is usually
    #    specific to one recipe/print run ("contains nuts", "keep
    #    refrigerated"); carrying it over to the next, unrelated recipe by
    #    default would risk printing the wrong warning on the wrong label.
    #    Starts blank every time; distinct from the per-ingredient 'note'
    #    *column* that may already be offered in columns/header_columns.
    label_note   = traitlets.Unicode('').tag(sync=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Apply last-saved settings (skipping anything the caller already
        # pinned via kwargs), then watch for further changes -- including
        # ones made straight in the browser -- so whatever's on screen
        # when the panel closes is what opens next time.
        self._settings_dirty = False
        saved = _load_settings()
        for name in _PERSISTED_TRAITS:
            if name in saved and name not in kwargs:
                try:
                    setattr(self, name, saved[name])
                except Exception:
                    pass   # stale/malformed value -- keep the trait default
        for name in _PERSISTED_TRAITS:
            self.observe(self._on_persisted_change, names=name)

    def _on_persisted_change(self, change):
        # Just flag dirty here -- cheap, in-memory, can't stall anything.
        # The actual write is deferred to flush_settings(), called once
        # when the panel closes, instead of on every single change (every
        # checkbox click, every Initials keystroke). See the module-level
        # note on _save_settings for why immediate writes are risky here.
        self._settings_dirty = True

    def flush_settings(self):
        """Persist current settings if anything changed since the last
        flush. Called once from the panel's Close button."""
        if not self._settings_dirty:
            return
        _save_settings({name: getattr(self, name) for name in _PERSISTED_TRAITS})
        self._settings_dirty = False

    _esm = r"""
    function render({ model, el }) {
      el.classList.add("lmw-root");

      const PX_PER_IN = 96;                       // CSS reference pixel
      const PRESETS = [[3, 1], [3, 2], [2, 1], [4, 2], [2, 2], [4, 6]];
      const RIGHT_ALIGN = new Set(["quantity", "equ quant", "cost", "menu price"]);
      const FONT_STACK = "Helvetica, Arial, sans-serif";

      // browser-local state (not worth syncing)
      const forcedScope = model.get("initial_scope");
      let scope = (forcedScope === "selection" || forcedScope === "all")
        ? forcedScope
        : ((model.get("rows_selection") || []).length ? "selection" : "all");
      // Which item is currently previewed/exported in "Label per item"
      // mode -- browser-local like scope, paged via the +/- controls,
      // reset to 0 whenever scope or format changes since the underlying
      // row list may be different. Defensively clamped wherever it's read.
      let itemIndex = 0;

      const esc = (s) => String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

      const meas = document.createElement("canvas").getContext("2d");
      const textW = (s, font) => { meas.font = font; return meas.measureText(String(s)).width; };

      // Columns whose displayed value should get a leading "$" -- just
      // 'cost' for now. Centralized here so the table body, the list
      // paragraph, and the title-row subtitle all format it identically
      // rather than three separate call sites drifting apart.
      const DOLLAR_COLS = new Set(["cost"]);
      const fmtVal = (col, val) => {
        const v = String(val ?? "").trim();
        if (!v || !DOLLAR_COLS.has(col) || v.startsWith("$") || v.startsWith("-$")) return v;
        return v.startsWith("-") ? "-$" + v.slice(1) : "$" + v;
      };

      const currentRows = () =>
        scope === "selection" ? (model.get("rows_selection") || [])
                              : (model.get("rows_all") || []);

      function wrapText(text, font, maxW) {
        const words = String(text).split(/\s+/).filter(Boolean);
        if (!words.length) return [""];
        const lines = [];
        let line = words[0];
        for (let i = 1; i < words.length; i++) {
          const t = line + " " + words[i];
          if (textW(t, font) <= maxW) line = t;
          else { lines.push(line); line = words[i]; }
        }
        lines.push(line);
        return lines;
      }

      // Same greedy word-wrap as wrapText, but the first line alone gets
      // `firstMaxW` while every line after it gets `restMaxW`. Used for
      // the title: only its first line shares a row with the date badge,
      // so only that line needs the narrower budget -- constraining every
      // line to it (as a single wrapText call would) wastes width on a
      // multi-line title for no reason.
      function wrapFirstLineNarrow(text, font, firstMaxW, restMaxW) {
        const words = String(text).split(/\s+/).filter(Boolean);
        if (!words.length) return [""];
        const lines = [];
        let line = words[0];
        let maxW = firstMaxW;
        for (let i = 1; i < words.length; i++) {
          const t = line + " " + words[i];
          if (textW(t, font) <= maxW) line = t;
          else { lines.push(line); line = words[i]; maxW = restMaxW; }
        }
        lines.push(line);
        return lines;
      }

      // ── layout: compose the label SVG at a given base font size ──────
      // Returns {svg, fits}. Coordinates are CSS px (96/in); the PNG
      // export rescales the whole thing to the chosen DPI in one step.
      function layout(fontPx) {
        const W = model.get("width_in") * PX_PER_IN;
        const H = model.get("height_in") * PX_PER_IN;
        // Padding scales with the label's smaller dimension (so small
        // labels get proportionally tight margins) but is capped at a
        // fixed 0.125in regardless of how large the label gets -- without
        // this, a big label like 4x6 (smaller dimension = 4in) ends up
        // with a ~0.22in margin, literally double every other preset's,
        // just because its "smaller dimension" is itself already large.
        const pad = Math.min(Math.max(Math.min(W, H) * 0.055, 5), PX_PER_IN * 0.125);
        const innerW = W - 2 * pad;
        const cols = (model.get("columns") || [])
          .filter((c) => (model.get("all_columns") || []).includes(c));
        const headerCols = (model.get("header_columns") || [])
          .filter((c) => (model.get("all_columns") || []).includes(c) && c !== "ingredient");
        const rows = currentRows();

        const bodyFont  = `${fontPx}px ${FONT_STACK}`;
        const boldFont  = `bold ${fontPx}px ${FONT_STACK}`;
        const titleSize = fontPx * 1.15;
        const titleFont = `bold ${titleSize}px ${FONT_STACK}`;
        const dateSize  = Math.max(fontPx * 0.85, 6);
        const dateFont  = `${dateSize}px ${FONT_STACK}`;
        const lh = fontPx * 1.28;

        let fits = true;
        let y = pad;
        const parts = [];
        const text = (x, baseY, s, font, size, anchor, extra) =>
          parts.push(`<text x="${x.toFixed(1)}" y="${baseY.toFixed(1)}" ` +
            `font-family="${FONT_STACK.replace(/"/g, '')}" font-size="${size.toFixed(2)}" ` +
            `${font.startsWith("bold") ? 'font-weight="bold" ' : ""}` +
            `text-anchor="${anchor}" fill="#000"${extra || ""}>${esc(s)}</text>`);
        const NUM = ' style="font-variant-numeric: tabular-nums"';

        const style = model.get("format_style");   // 'table' | 'list' | 'per_item'
        const isPerItem = style === "per_item";
        // The item currently being previewed/exported in "Label per
        // item" mode -- itemIndex is browser-local (like scope), paged
        // via the +/- controls, and defensively clamped here in case the
        // row list is shorter than wherever it was last left pointing.
        const currentItem = isPerItem
          ? (rows[Math.min(itemIndex, Math.max(rows.length - 1, 0))] || {})
          : null;

        // ── header: headline (wrapping) + date/year/initials top-right ──
        // date_str always arrives as "MM/DD/YYYY" (see the Python side).
        // Date and Year are independent toggles: Date shows the "MM/DD"
        // part, Year shows the "YYYY" part, and either can be on without
        // the other -- Year alone (Date off) shows just the year, e.g.
        // for a coarser "packed in 2026" style label. Initials sits in
        // the same corner as the date, appended after whichever date bits
        // are showing (or alone, if neither is). For Table/List, that
        // corner is top-right, inline with the headline. For "Label per
        // item", the corner instead sits on its own line right below the
        // item name (see the isPerItem branch below).
        //
        // In "Label per item" mode the headline is the current item's
        // primary field (cols[0], usually 'ingredient') instead of the
        // recipe title -- the whole point of the mode is that each label
        // is about one item, so it takes the prominent top spot, with the
        // full label width to itself since date/initials moved off its
        // row. The recipe title, if Title is on, moves down into the
        // subtitle instead (plain, no label) alongside the item's other
        // selected columns. Title always shows the headline for the
        // other two formats, same as before.
        const showTitle = model.get("show_title");
        const rawDate = model.get("date_str") || "";
        const dm = rawDate.match(/^(\d{1,2}\/\d{1,2})\/(\d{4})$/);
        const monthDay = dm ? dm[1] : rawDate;
        const yearOnly = dm ? dm[2] : "";
        const dateParts = [];
        if (model.get("show_date") && monthDay) dateParts.push(monthDay);
        if (model.get("show_year") && yearOnly) dateParts.push(yearOnly);
        const dateText = dateParts.join("/");
        const initialsText = (model.get("initials") || "").trim();
        const cornerParts = [];
        if (dateText) cornerParts.push(dateText);
        if (initialsText) cornerParts.push(initialsText);
        const cornerText = cornerParts.join(" \u00B7 ");
        const showCorner = cornerParts.length > 0;

        const headlineText = isPerItem
          ? (cols.length ? fmtVal(cols[0], currentItem[cols[0]]) : "")
          : model.get("title");
        const showHeadline = isPerItem ? rows.length > 0 : showTitle;

        if (showHeadline || showCorner) {
          const titleLh = titleSize * 1.22;

          if (isPerItem) {
            // The item name gets the full label width -- date/initials
            // move to their own line right below it instead of sharing
            // this row, so there's no overlap risk to guard against here
            // (unlike Table/List below, which still shares a row with
            // the corner and needs the narrow-first-line treatment).
            const headlineLines = showHeadline ? wrapText(headlineText, titleFont, innerW) : [];
            headlineLines.forEach((ln, i) => {
              if (textW(ln, titleFont) > innerW) fits = false;
              text(pad, y + titleLh * i + titleSize * 0.85, ln,
                   titleFont, titleSize, "start");
            });
            y += headlineLines.length * titleLh;

            if (showCorner) {
              if (textW(cornerText, dateFont) > innerW) fits = false;
              text(pad, y + dateSize * 0.85, cornerText, dateFont, dateSize, "start", NUM);
              y += dateSize * 1.22;
            }
          } else {
            const cornerW = showCorner ? textW(cornerText, dateFont) : 0;
            // True space left for the headline's first line once the
            // date/initials corner claims its space; can go negative if
            // that corner is very wide relative to the label -- that's
            // fine, the fits-check below catches it and the binary
            // search backs off to a smaller font (which shrinks the
            // corner too, freeing up room) rather than letting the two
            // silently overlap.
            const realFirstMaxW = innerW - (showCorner ? cornerW + fontPx * 0.8 : 0);
            const wrapFirstMaxW = Math.max(realFirstMaxW, fontPx * 3);   // keeps wrapText well-behaved
            const headlineLines = showHeadline
              ? wrapFirstLineNarrow(headlineText, titleFont, wrapFirstMaxW, innerW)
              : [];
            if (showCorner)
              text(W - pad, y + dateSize * 0.85, cornerText,
                   dateFont, dateSize, "end", NUM);
            headlineLines.forEach((ln, i) => {
              const maxForLine = (i === 0 && showCorner) ? realFirstMaxW : innerW;
              if (textW(ln, titleFont) > maxForLine) fits = false;
              text(pad, y + titleLh * i + titleSize * 0.85, ln,
                   titleFont, titleSize, "start");
            });
            y += Math.max(headlineLines.length * titleLh, showCorner ? dateSize * 1.22 : 0);
          }

          // Subtitle: recipe-level info under the headline. For Table/
          // List, that's the recipe's own top-row columns (yield, total
          // cost, etc.) via header_columns -- unchanged from before, only
          // shown when Title is on (this is recipe info, not per-print
          // metadata). For "Label per item", it's the current item's
          // *other* selected columns (cols.slice(1) -- quantity, cost,
          // etc.), plus the recipe title itself (plain, no label) if
          // Title is on. "Column headers" governs "field: value" vs bare
          // value in both cases, same as the table's own header row.
          const showLabels = model.get("show_headers");
          let subtitleParts = [];
          if (isPerItem) {
            if (showTitle) subtitleParts.push(model.get("title"));
            cols.slice(1).forEach((c) => {
              const v = fmtVal(c, currentItem[c]);
              if (v !== "") subtitleParts.push(showLabels ? `${c}: ${v}` : v);
            });
          } else if (showTitle) {
            const headerRow = model.get("header_row") || {};
            subtitleParts = headerCols
              .map((c) => [c, fmtVal(c, headerRow[c])])
              .filter(([, v]) => v !== undefined && v !== null && v !== "")
              .map(([c, v]) => showLabels ? `${c}: ${v}` : v);
          }
          if (subtitleParts.length) {
            const subSize = Math.max(fontPx * 0.85, 6);
            const subFont = `${subSize}px ${FONT_STACK}`;
            const subLh = subSize * 1.22;
            const subLines = wrapText(subtitleParts.join(" \u00B7 "), subFont, innerW);
            subLines.forEach((ln, i) =>
              text(pad, y + subLh * i + subSize * 0.85, ln, subFont, subSize, "start", NUM));
            y += subLines.length * subLh;
          }

          // The divider only earns its place when there's a separate
          // ingredient body below it to separate the header from -- a
          // headline-only label doesn't need a line pointing at empty
          // space, and "Label per item" never has a body section at all
          // (the item's own info already lives in the headline/subtitle
          // above), so it never draws one either.
          if (!isPerItem && cols.length && rows.length) {
            y += fontPx * 0.30;
            parts.push(`<line x1="${pad}" y1="${y.toFixed(1)}" x2="${(W - pad).toFixed(1)}" ` +
                       `y2="${y.toFixed(1)}" stroke="#000" stroke-width="0.75"/>`);
            y += fontPx * 0.42;
          }
        }


        if (cols.length && rows.length && style === "table") {
          const gap = fontPx * 0.9;

          // natural (unwrapped) width of every column but the first
          const otherW = cols.slice(1).map((c) => {
            let w = model.get("show_headers") ? textW(c, boldFont) : 0;
            for (const r of rows) w = Math.max(w, textW(fmtVal(c, r[c]), bodyFont));
            return w;
          });
          const otherTotal = otherW.reduce((a, b) => a + b, 0)
                           + gap * (cols.length - 1);
          const firstMaxW = innerW - otherTotal;
          if (firstMaxW < fontPx * 2.5) fits = false;   // squeeze → smaller font

          // right edges for columns 1..n, packed against the label edge
          const rightX = [];
          let rx = W - pad;
          for (let j = otherW.length - 1; j >= 0; j--) {
            rightX[j] = rx;
            rx -= otherW[j] + gap;
          }

          // optional column-header row
          if (model.get("show_headers")) {
            text(pad, y + fontPx * 0.85, cols[0], boldFont, fontPx, "start");
            cols.slice(1).forEach((c, j) =>
              text(rightX[j], y + fontPx * 0.85, c, boldFont, fontPx, "end"));
            y += lh * 1.05;
          }

          // body rows: first column wraps, the rest sit on its first line
          for (const r of rows) {
            const lines = wrapText(fmtVal(cols[0], r[cols[0]]), bodyFont,
                                   Math.max(firstMaxW, fontPx * 2.5));
            lines.forEach((ln, i) =>
              text(pad, y + lh * i + fontPx * 0.85, ln, bodyFont, fontPx, "start"));
            cols.slice(1).forEach((c, j) =>
              text(rightX[j], y + fontPx * 0.85, fmtVal(c, r[c]), bodyFont, fontPx,
                   "end", RIGHT_ALIGN.has(c) ? NUM : ""));
            y += lh * lines.length + fontPx * 0.12;
          }
        }

        // ── list format: every selected column from every ingredient
        //    concatenated into one continuous, comma-separated paragraph
        //    that wraps across the full label width -- no per-row
        //    bullets, no columns, just plain running text (the style
        //    used on packaged-food ingredient declarations). Column
        //    headers don't apply to this style.
        if (cols.length && rows.length && style === "list") {
          const paragraph = rows.map((r) => cols.map((c) => fmtVal(c, r[c]))
            .filter((v) => v !== "").join(" ")).join(", ");
          const lines = wrapText(paragraph, bodyFont, innerW);
          lines.forEach((ln, i) =>
            text(pad, y + lh * i + fontPx * 0.85, ln, bodyFont, fontPx, "start"));
          y += lh * lines.length;
        }

        // ── optional free-text note (e.g. "Keep refrigerated") -- a small
        // italic footer line below the ingredient content, shown whenever
        // the Note field has text in it. Independent of Title/Date and of
        // any per-ingredient 'note' column offered elsewhere.
        const noteText = (model.get("label_note") || "").trim();
        if (noteText) {
          const noteSize = Math.max(fontPx * 0.78, 6);
          const noteFont = `italic ${noteSize}px ${FONT_STACK}`;
          const noteLh = noteSize * 1.22;
          y += fontPx * 0.25;   // a little breathing room above the note
          const noteLines = wrapText(noteText, noteFont, innerW);
          noteLines.forEach((ln, i) =>
            text(pad, y + noteLh * i + noteSize * 0.85, ln,
                 noteFont, noteSize, "start", ' font-style="italic"'));
          y += noteLines.length * noteLh;
        }

        if (y - fontPx * 0.12 + pad * 0.6 > H) fits = false;

        const svg =
          `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" ` +
          `viewBox="0 0 ${W} ${H}">` +
          `<rect width="${W}" height="${H}" fill="#fff"/>` +
          parts.join("") + `</svg>`;
        return { svg, fits };
      }

      // largest font size that fits; floor of 6px if nothing does
      function bestLayout() {
        let lo = 6, hi = Math.max(model.get("height_in") * PX_PER_IN * 0.6, 8);
        if (!layout(lo).fits) return { ...layout(lo), font: lo, clipped: true };
        for (let i = 0; i < 22; i++) {         // ~0.01px precision
          const mid = (lo + hi) / 2;
          if (layout(mid).fits) lo = mid; else hi = mid;
        }
        return { ...layout(lo), font: lo, clipped: false };
      }

      // The auto-fit size above is always "100%" for the text_scale
      // control -- this applies the person's +/- adjustment on top of it
      // and re-renders at that final size. Scaling down still fits by
      // construction; scaling up is allowed to overflow (clipped=true),
      // same warning banner as any other overflow. Every consumer below
      // (preview, PNG, print) goes through this so they never drift.
      function scaledLayout() {
        const auto = bestLayout();
        const scale = model.get("text_scale") || 1;
        const fontPx = Math.max(4, auto.font * scale);
        const res = layout(fontPx);
        return { svg: res.svg, font: fontPx, clipped: auto.clipped || !res.fits };
      }

      // ── exports ──────────────────────────────────────────────────────
      const fileStem = () => {
        const base = (model.get("title") || "label")
          .replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "_") || "label";
        let stem = `${base}_${model.get("width_in")}x${model.get("height_in")}`;
        if (model.get("format_style") === "per_item") {
          const rows = currentRows();
          const itemCols = (model.get("columns") || [])
            .filter((c) => (model.get("all_columns") || []).includes(c));
          const item = rows[Math.min(itemIndex, Math.max(rows.length - 1, 0))];
          const itemName = item && itemCols.length
            ? String(item[itemCols[0]] ?? "").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "_")
            : "";
          if (itemName) stem += `_${itemName}`;
        }
        return stem;
      };

      // Rasterizes and downloads whatever scaledLayout() currently
      // produces as one PNG file. Callback-based (rather than returning a
      // promise) to match the existing Image/canvas.toBlob callback style
      // throughout this file; onDone is called after the file is saved
      // (or after a failure) so a caller can sequence multiple downloads
      // one after another instead of firing them all at once.
      function downloadOnePNG(onDone) {
        const { svg } = scaledLayout();
        const dpi = model.get("dpi");
        const pw = Math.round(model.get("width_in") * dpi);
        const ph = Math.round(model.get("height_in") * dpi);
        const img = new Image();
        img.onload = () => {
          const canvas = document.createElement("canvas");
          canvas.width = pw; canvas.height = ph;
          const ctx = canvas.getContext("2d");
          ctx.fillStyle = "#fff";
          ctx.fillRect(0, 0, pw, ph);
          ctx.drawImage(img, 0, 0, pw, ph);
          canvas.toBlob((blob) => {
            if (!blob) { setStatus("PNG export failed in this browser.", true); if (onDone) onDone(false); return; }
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${fileStem()}_${dpi}dpi.png`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 4000);
            if (onDone) onDone(true, a.download, pw, ph);
          }, "image/png");
        };
        img.onerror = () => { setStatus("PNG export failed (SVG rasterize).", true); if (onDone) onDone(false); };
        img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      }

      // "Download PNG" always exports just the one currently shown --
      // in Table/List that's the only label there is; in "Label per
      // item" it's whichever item the +/- nav is currently pointed at.
      // Batch-exporting every item is a separate, explicit action (the
      // "Download All PNGs" button, per-item mode only) rather than this
      // button's default behavior, so a single click never surprises
      // someone with a pile of files when they only wanted one.
      function downloadPNG() {
        downloadOnePNG((ok, name, pw, ph) => {
          if (ok) setStatus(`Saved ${name} (${pw} × ${ph} px).`, false);
        });
      }

      // "Download All PNGs" ("Label per item" mode only): exports every
      // item in the current scope as its own PNG file, matching Print's
      // existing batch-all behavior. Downloads are staggered with a
      // short delay between each rather than fired all at once, since
      // browsers can block/prompt for a burst of near-simultaneous
      // downloads; sequencing them makes it read as a normal series of
      // saves instead. itemIndex is restored (and the preview refreshed)
      // once the batch finishes, so it doesn't leave the on-screen
      // preview pointing at the last item exported.
      function downloadAllPNGs() {
        const savedIndex = itemIndex;
        const rows = currentRows();
        if (!rows.length) { setStatus("No items to export in this selection.", true); return; }
        let i = 0;
        const next = () => {
          if (i >= rows.length) {
            itemIndex = savedIndex;
            updatePreview();
            setStatus(`Saved ${rows.length} PNG file${rows.length === 1 ? "" : "s"}.`, false);
            return;
          }
          itemIndex = i;
          setStatus(`Exporting ${i + 1} of ${rows.length}\u2026`, false);
          downloadOnePNG(() => { i += 1; setTimeout(next, 300); });
        };
        next();
      }

      function printLabels() {
        const w = model.get("width_in"), h = model.get("height_in");
        const n = Math.max(1, model.get("copies") | 0);
        const isPerItem = model.get("format_style") === "per_item";

        let pageSvgs;
        if (isPerItem) {
          // Batch-print one page per item in the current scope (each
          // repeated `copies` times) -- not just the one on screen. That's
          // the whole point of this mode: print every item's own label in
          // one go. Each gets independently auto-fit (a single shared size
          // across items of very different length would either overflow
          // the longest or under-use the shortest), by briefly pointing
          // itemIndex at each row in turn and restoring it after so the
          // preview doesn't jump.
          const savedIndex = itemIndex;
          const rows = currentRows();
          pageSvgs = [];
          for (let i = 0; i < rows.length; i++) {
            itemIndex = i;
            const { svg } = scaledLayout();
            for (let c = 0; c < n; c++) pageSvgs.push(svg);
          }
          itemIndex = savedIndex;
          if (!pageSvgs.length) { setStatus("No items to print in this selection.", true); return; }
        } else {
          const { svg } = scaledLayout();
          pageSvgs = Array(n).fill(svg);
        }

        // Some browsers' print dialogs (Chrome's, notably) don't reliably
        // pick "Landscape" for a custom @page size -- left on the default
        // "Portrait" layout, a wide label (width > height, true of most
        // presets here) gets its content clipped to a narrower portrait
        // page even though @page correctly states width > height.
        // Workaround: declare the page using swapped (portrait) dimensions
        // and rotate the actual content 90° to fill it, so the print
        // engine's own default assumption lines up with what's being
        // asked for either way. Only needed for landscape-shaped labels;
        // portrait/square ones already match the default and are left
        // alone.
        const landscape = w > h;
        const pageW = landscape ? h : w;
        const pageH = landscape ? w : h;
        const pgTransform = landscape
          ? `transform: rotate(90deg); transform-origin: top left; position: relative; left: ${h}in;`
          : "";

        const pages = pageSvgs.map((svg) => `<div class="pg">` +
          svg.replace("<svg ", `<svg style="width:${w}in;height:${h}in;display:block" `) +
          `</div>`).join("");
        const html =
          `<!DOCTYPE html><html><head><title>${esc(fileStem())}</title><style>` +
          `@page { size: ${pageW}in ${pageH}in; margin: 0; }` +
          `html, body { margin: 0; padding: 0; }` +
          `.pg { width: ${w}in; height: ${h}in; overflow: hidden; ${pgTransform} ` +
          `page-break-after: always; break-after: page; }` +
          `.pg:last-child { page-break-after: auto; break-after: auto; }` +
          `</style></head><body>${pages}</body></html>`;
        const win = window.open("", "_blank");
        if (!win) { setStatus("Popup blocked — allow popups to print.", true); return; }
        win.document.open();
        win.document.write(html);
        win.document.close();
        win.focus();
        setTimeout(() => { try { win.print(); } catch (e) {} }, 250);
      }

      // ── controls + preview scaffold (built once; preview redraws) ────
      el.innerHTML = `
        <div class="lmw-panel">
          <div class="lmw-row lmw-scope-row">
            <span class="lmw-lbl">Content:</span>
            <label><input type="radio" name="lmw-scope" value="selection"> Selection</label>
            <label><input type="radio" name="lmw-scope" value="all"> Whole recipe</label>
            <span class="lmw-count"></span>
          </div>
          <div class="lmw-row"><span class="lmw-lbl">Ingredient columns:</span>
            <span class="lmw-cols"></span></div>
          <div class="lmw-row"><span class="lmw-lbl">Title row columns:</span>
            <span class="lmw-header-cols"></span></div>
          <div class="lmw-row lmw-format-row">
            <span class="lmw-lbl">Format:</span>
            <label><input type="radio" name="lmw-format" value="table"> Table</label>
            <label><input type="radio" name="lmw-format" value="list"> Ingredient list</label>
            <label><input type="radio" name="lmw-format" value="per_item"> Label per item</label>
          </div>
          <div class="lmw-row">
            <span class="lmw-lbl">Size:</span>
            <select class="lmw-size"></select>
            <span class="lmw-custom" style="display:none">
              <input type="number" class="lmw-w" min="0.5" max="12" step="0.25"> ×
              <input type="number" class="lmw-h" min="0.5" max="12" step="0.25"> in
            </span>
            <button type="button" class="lmw-swap" title="Swap width and height">⇄</button>
            <span class="lmw-lbl" style="margin-left:10px">DPI:</span>
            <select class="lmw-dpi">
              <option value="203">203 (thermal)</option>
              <option value="300">300</option>
              <option value="600">600</option>
            </select>
          </div>
          <div class="lmw-row">
            <label><input type="checkbox" class="lmw-title-cb"> Title</label>
            <label><input type="checkbox" class="lmw-date-cb"> Date</label>
            <label><input type="checkbox" class="lmw-year-cb"> Year</label>
            <span class="lmw-lbl">Initials:</span>
            <input type="text" class="lmw-initials-input" placeholder="e.g. JS" style="width:60px">
            <label><input type="checkbox" class="lmw-head-cb"> Column headers</label>
          </div>
          <div class="lmw-row">
            <span class="lmw-lbl">Text size:</span>
            <button type="button" class="lmw-text-dec" title="Smaller text">−</button>
            <span class="lmw-text-pct">100%</span>
            <button type="button" class="lmw-text-inc" title="Larger text">+</button>
          </div>
          <div class="lmw-row">
            <span class="lmw-lbl">Note:</span>
            <input type="text" class="lmw-note-input" placeholder="e.g. Keep refrigerated">
          </div>
          <div class="lmw-row">
            <span class="lmw-item-nav" style="display:none">
              <button type="button" class="lmw-item-prev" title="Previous item">−</button>
              <span class="lmw-item-count"></span>
              <button type="button" class="lmw-item-next" title="Next item">+</button>
            </span>
            <span class="lmw-lbl">Copies:</span>
            <input type="number" class="lmw-copies" min="1" max="99" step="1">
            <button type="button" class="lmw-png">⬇ Download PNG</button>
            <button type="button" class="lmw-png-all" style="display:none">⬇ Download All PNGs</button>
            <button type="button" class="lmw-print">🖨 Print / Save PDF</button>
            <span class="lmw-status"></span>
          </div>
        </div>
        <div class="lmw-preview-wrap">
          <div class="lmw-preview"></div>
          <div class="lmw-caption"></div>
        </div>`;

      const q = (sel) => el.querySelector(sel);
      const setStatus = (msg, bad) => {
        const s = q(".lmw-status");
        s.textContent = msg;
        s.classList.toggle("lmw-bad", !!bad);
      };

      // populate static controls
      const sizeSel = q(".lmw-size");
      PRESETS.forEach(([w, h]) => {
        const o = document.createElement("option");
        o.value = `${w}x${h}`; o.textContent = `${w} × ${h} in`;
        sizeSel.appendChild(o);
      });
      const custom = document.createElement("option");
      custom.value = "custom"; custom.textContent = "Custom…";
      sizeSel.appendChild(custom);

      function syncControls() {
        const w = model.get("width_in"), h = model.get("height_in");
        const preset = PRESETS.find(([pw, ph]) => pw === w && ph === h);
        sizeSel.value = preset ? `${w}x${h}` : "custom";
        q(".lmw-custom").style.display = preset ? "none" : "inline";
        q(".lmw-w").value = w; q(".lmw-h").value = h;
        q(".lmw-dpi").value = String(model.get("dpi"));
        q(".lmw-title-cb").checked = model.get("show_title");
        q(".lmw-date-cb").checked = model.get("show_date");
        q(".lmw-year-cb").checked = model.get("show_year");
        const initialsVal = model.get("initials") || "";
        if (q(".lmw-initials-input").value !== initialsVal) q(".lmw-initials-input").value = initialsVal;
        q(".lmw-head-cb").checked = model.get("show_headers");
        q(".lmw-copies").value = model.get("copies");
        q(".lmw-text-pct").textContent = Math.round((model.get("text_scale") || 1) * 100) + "%";
        const noteVal = model.get("label_note") || "";
        if (q(".lmw-note-input").value !== noteVal) q(".lmw-note-input").value = noteVal;
        el.querySelector(`input[name="lmw-scope"][value="${scope}"]`).checked = true;
        const fmt = ["table", "list", "per_item"].includes(model.get("format_style"))
          ? model.get("format_style") : "table";
        el.querySelector(`input[name="lmw-format"][value="${fmt}"]`).checked = true;

        const isPerItemNow = fmt === "per_item";
        q(".lmw-item-nav").style.display = isPerItemNow ? "flex" : "none";
        q(".lmw-png-all").style.display = isPerItemNow ? "inline-block" : "none";
        if (isPerItemNow) {
          const itemRows = currentRows();
          const n = itemRows.length;
          const shown = n ? Math.min(itemIndex, n - 1) + 1 : 0;
          q(".lmw-item-count").textContent = n ? `Item ${shown} of ${n}` : "No items";
          q(".lmw-item-prev").disabled = shown <= 1;
          q(".lmw-item-next").disabled = shown >= n;
        }

        const nSel = (model.get("rows_selection") || []).length;
        const titleOnly = !nSel && forcedScope === "selection";
        q(".lmw-count").textContent =
          nSel ? `(${nSel} row${nSel === 1 ? "" : "s"} selected)`
               : (titleOnly ? "(title row only)" : "(no selection)");
        el.querySelector('input[name="lmw-scope"][value="selection"]').disabled = !nSel && !titleOnly;

        // ingredient (body row) column checkboxes
        const chosen = new Set(model.get("columns") || []);
        q(".lmw-cols").innerHTML = (model.get("all_columns") || []).map((c) =>
          `<label><input type="checkbox" class="lmw-col-cb" value="${esc(c)}" ` +
          `${chosen.has(c) ? "checked" : ""}> ${esc(c)}</label>`).join(" ");
        el.querySelectorAll(".lmw-col-cb").forEach((cb) =>
          cb.addEventListener("change", () => {
            const order = model.get("all_columns") || [];
            const picked = Array.from(el.querySelectorAll(".lmw-col-cb:checked"))
              .map((x) => x.value);
            model.set("columns", order.filter((c) => picked.includes(c)));
            model.save_changes();
          }));

        // title-row (header_row) column checkboxes -- independent
        // selection from the ingredient columns above; 'ingredient' isn't
        // offered here since it's just the recipe name, already the title
        const chosenHdr = new Set(model.get("header_columns") || []);
        const hdrDisabled = !model.get("show_title");
        q(".lmw-header-cols").innerHTML = (model.get("all_columns") || [])
          .filter((c) => c !== "ingredient").map((c) =>
            `<label><input type="checkbox" class="lmw-hcol-cb" value="${esc(c)}" ` +
            `${chosenHdr.has(c) ? "checked" : ""} ${hdrDisabled ? "disabled" : ""}>` +
            ` ${esc(c)}</label>`).join(" ");
        el.querySelectorAll(".lmw-hcol-cb").forEach((cb) =>
          cb.addEventListener("change", () => {
            const order = (model.get("all_columns") || []).filter((c) => c !== "ingredient");
            const picked = Array.from(el.querySelectorAll(".lmw-hcol-cb:checked"))
              .map((x) => x.value);
            model.set("header_columns", order.filter((c) => picked.includes(c)));
            model.save_changes();
          }));
      }

      function updatePreview() {
        const res = scaledLayout();
        const wrap = q(".lmw-preview");
        const maxW = Math.min(el.clientWidth - 24 || 460, 460);
        const W = model.get("width_in") * PX_PER_IN;
        const previewScale = Math.min(2, Math.max(maxW / W, 0.5));
        wrap.innerHTML = res.svg;
        const svgEl = wrap.querySelector("svg");
        svgEl.style.width = (W * previewScale) + "px";
        svgEl.style.height = (model.get("height_in") * PX_PER_IN * previewScale) + "px";
        q(".lmw-caption").textContent =
          `${model.get("width_in")} × ${model.get("height_in")} in — preview at ` +
          `${Math.round(previewScale * 100)}% of print size` +
          (res.clipped ? " — ⚠ content may not fit: reduce text size, use a larger " +
                          "label, or fewer columns/rows" : "");
        q(".lmw-caption").classList.toggle("lmw-bad", res.clipped);
      }

      const refresh = () => { syncControls(); updatePreview(); };

      // ── wire events ──────────────────────────────────────────────────
      el.querySelectorAll('input[name="lmw-scope"]').forEach((r) =>
        r.addEventListener("change", () => { scope = r.value; itemIndex = 0; refresh(); }));
      el.querySelectorAll('input[name="lmw-format"]').forEach((r) =>
        r.addEventListener("change", () => {
          itemIndex = 0;
          model.set("format_style", r.value); model.save_changes();
        }));
      q(".lmw-item-prev").addEventListener("click", () => {
        itemIndex = Math.max(0, itemIndex - 1);
        refresh();
      });
      q(".lmw-item-next").addEventListener("click", () => {
        const n = currentRows().length;
        itemIndex = Math.min(Math.max(n - 1, 0), itemIndex + 1);
        refresh();
      });
      sizeSel.addEventListener("change", () => {
        if (sizeSel.value === "custom") {
          q(".lmw-custom").style.display = "inline";
          return;   // wait for the number inputs
        }
        const [w, h] = sizeSel.value.split("x").map(Number);
        model.set("width_in", w); model.set("height_in", h);
        model.save_changes();
      });
      const applyCustom = () => {
        const w = parseFloat(q(".lmw-w").value), h = parseFloat(q(".lmw-h").value);
        if (w > 0 && h > 0) {
          model.set("width_in", w); model.set("height_in", h);
          model.save_changes();
        }
      };
      q(".lmw-w").addEventListener("change", applyCustom);
      q(".lmw-h").addEventListener("change", applyCustom);
      q(".lmw-swap").addEventListener("click", () => {
        const w = model.get("width_in"), h = model.get("height_in");
        model.set("width_in", h); model.set("height_in", w);
        model.save_changes();
      });
      q(".lmw-dpi").addEventListener("change", () => {
        model.set("dpi", parseInt(q(".lmw-dpi").value, 10)); model.save_changes();
      });
      q(".lmw-title-cb").addEventListener("change", () => {
        model.set("show_title", q(".lmw-title-cb").checked); model.save_changes();
      });
      q(".lmw-date-cb").addEventListener("change", () => {
        model.set("show_date", q(".lmw-date-cb").checked); model.save_changes();
      });
      q(".lmw-year-cb").addEventListener("change", () => {
        model.set("show_year", q(".lmw-year-cb").checked); model.save_changes();
      });
      q(".lmw-initials-input").addEventListener("input", () => {
        model.set("initials", q(".lmw-initials-input").value);
        model.save_changes();
      });
      q(".lmw-head-cb").addEventListener("change", () => {
        model.set("show_headers", q(".lmw-head-cb").checked); model.save_changes();
      });
      q(".lmw-copies").addEventListener("change", () => {
        model.set("copies", Math.max(1, parseInt(q(".lmw-copies").value, 10) || 1));
        model.save_changes();
      });
      const stepTextScale = (delta) => {
        const cur = model.get("text_scale") || 1;
        const next = Math.min(2.0, Math.max(0.5, Math.round((cur + delta) * 20) / 20));
        model.set("text_scale", next);
        model.save_changes();
      };
      q(".lmw-text-dec").addEventListener("click", () => stepTextScale(-0.1));
      q(".lmw-text-inc").addEventListener("click", () => stepTextScale(0.1));
      q(".lmw-note-input").addEventListener("input", () => {
        model.set("label_note", q(".lmw-note-input").value);
        model.save_changes();
      });
      q(".lmw-png").addEventListener("click", downloadPNG);
      q(".lmw-png-all").addEventListener("click", downloadAllPNGs);
      q(".lmw-print").addEventListener("click", printLabels);

      // coalesce trait updates into one repaint per message batch
      let pending = false;
      const schedule = () => {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; refresh(); });
      };
      ["title", "date_str", "all_columns", "header_row", "rows_all", "rows_selection",
       "columns", "header_columns", "width_in", "height_in", "dpi", "format_style", "text_scale",
       "show_date", "show_year", "show_title", "show_headers", "copies", "label_note",
       "initials"].forEach((t) => model.on(`change:${t}`, schedule));

      refresh();
    }
    export default { render };
    """

    _css = """
    .lmw-root { --lmw-ink:    var(--jp-ui-font-color1, #1c2733);
                --lmw-muted:  #66727f;
                --lmw-border: #dde3ea;
                --lmw-bg:     var(--jp-layout-color1, #fff);
                --lmw-accent: #2563eb;
                --lmw-bad:    #b91c1c;
                font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
                font-size: 13px; color: var(--lmw-ink); }
    body[data-jp-theme-light="false"] .lmw-root {
        --lmw-muted:  #9aa5af;
        --lmw-border: #3a4149;
        --lmw-bad:    #f87171; }

    .lmw-panel { border: 1px solid var(--lmw-border); border-radius: 6px;
                 padding: 6px 8px; margin: 4px 0; }
    .lmw-row { display: flex; flex-wrap: wrap; align-items: center;
               gap: 6px 10px; padding: 3px 0; }
    .lmw-lbl { color: var(--lmw-muted); }
    .lmw-count { color: var(--lmw-muted); font-size: 12px; }
    .lmw-item-nav { align-items: center; gap: 6px; }
    .lmw-item-count { color: var(--lmw-muted); font-size: 12px; white-space: nowrap; }
    .lmw-root label { display: inline-flex; align-items: center; gap: 3px;
                      cursor: pointer; white-space: nowrap; }
    .lmw-root input[type="number"] { width: 58px; }
    .lmw-note-input { flex: 1 1 220px; min-width: 160px; }
    .lmw-root select, .lmw-root input {
        font-size: 13px; color: var(--lmw-ink);
        background: var(--lmw-bg);
        border: 1px solid var(--lmw-border); border-radius: 4px;
        padding: 2px 4px; }
    .lmw-root button { font-size: 13px; padding: 3px 12px;
        border: 1px solid var(--lmw-border); border-radius: 6px;
        background: var(--lmw-bg); color: var(--lmw-ink); cursor: pointer; }
    .lmw-root button:hover { border-color: var(--lmw-accent); }
    .lmw-status { font-size: 12px; color: var(--lmw-muted); }
    .lmw-bad { color: var(--lmw-bad) !important; }

    .lmw-preview-wrap { margin: 6px 0; }
    .lmw-preview svg { border: 1px dashed var(--lmw-muted);
                       box-shadow: 0 1px 4px rgba(0,0,0,0.18);
                       background: #fff; }
    .lmw-caption { font-size: 12px; color: var(--lmw-muted); margin-top: 3px; }
    """

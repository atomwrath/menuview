"""
order_grid_widget.py — anywidget-based fast grid for the Create Order tab.

Renders the whole order-entry list (one row per ingredient nickname, in
"physical location" order) as a single anywidget model — the same
architecture as recipe_grid_widget.py / guide_grid_widget.py, since one
ipywidgets widget per cell is the known performance ceiling.

Row model (each entry in `rows`)
    {
      "nickname":  str,
      "par":       float|None,      # reference stock level, editable
      "last":      float|None,      # quantity from the most recent created order
      "quant":     float,           # sum of this row's option quantities (informational —
                                     #   the browser recomputes this from `options` itself)
      "options":   [ {               # latest price per (supplier, number)
          "opt_id":   int,           #   uni_g '_guide_index' (stable across redraws)
          "supplier": str, "number": str, "description": str,
          "size": str, "price": float|str,
          "per_quant": str,          #   normalized $/quant display string
          "date": str,
          "low": bool,               #   True on the lowest-$/quant option
          "quant": float             #   order quantity assigned to THIS supplier/item
      } ]
    }

An ingredient's order quantity is the sum of its options' individual
quantities — ordering 3 cases from one supplier and 2 from another for the
same nickname is a normal split, not a conflict. The "order qty" column is
an increment/decrement number box showing that rollup; editing it (typing,
or clicking the native stepper arrows, or the Up/Down arrow keys) computes
the delta and routes it to a specific option rather than storing an
independent value: increments always land on the suggested (lowest-price)
option, and decrements drain the suggested option first, falling through
to any other option that still has quantity on it once the suggested one
hits zero -- so the total shown always matches the sum of the per-option
quantities underneath it. Expanding a row (click its supplier/item cell,
or see below) still exposes each option's own quantity input directly,
for a deliberate multi-supplier split.

Every qty box -- main or option-level -- shares one continuous Enter /
Shift+Enter path through the grid, in on-screen order: a row's main qty
box, then (only if that row happens to be expanded right now) each of its
own option qty boxes, then the next row's main box, and so on. A collapsed
row contributes just its main box to that path; a row with no price
options at all contributes nothing, since there's no input on it to land
on. Reaching either end of the whole sequence simply stops there rather
than wrapping around. This is deliberately one sequence rather than two
separate ones (main boxes chaining only to each other, options chaining
only within a row) -- expanding several rows and then Entering straight
through everything, main quantities and supplier splits alike, shouldn't
require switching between two different keys depending on where you are.

Right/Left on a MAIN qty box expand or collapse that row's price options
(same effect as clicking the supplier/item cell, just without leaving the
keyboard); Left on an OPTION qty box collapses that row and returns focus
to its main box, a quick way back out once you're done with the split.
These take over the arrow keys entirely rather than falling back to
in-field cursor movement -- type="number" inputs don't reliably expose
cursor position across browsers (Chrome in particular doesn't support it
at all), so there's no reliable way to distinguish "move the cursor" from
"nothing to move past" to fall back correctly.

Column order mirrors the recipe grid: ⋯ | ingredient | order qty | par |
last order | supplier/item. The ⋯ menu button sits leftmost (where a
plain remove button used to be), and there's no separate checkbox for
selection -- like the recipe grid, the ingredient cell IS the selection
handle: tap it to toggle that row into a selection, drag across
ingredient cells to add a whole range. Opening ⋯ on a row that's part of
a multi-row selection acts on the whole selection; opening it on a row
outside the current selection acts on just that row. The menu offers:
    Add here…   inline text input (with a nickname datalist) that inserts
                a new ingredient immediately above this row
    Cut         removes the row(s) into an in-widget clipboard
    Paste here  inserts the clipboard's item(s) immediately above this row
                (disabled when the clipboard is empty)
Reordering an item is therefore Cut, then Paste at the new spot. A "+ Add
ingredient" row pinned to the bottom of the table is the equivalent entry
point for appending at the end (and offers "Paste here" too, once
something's been cut) — this replaces the old standalone add-nickname box
that used to sit above the grid.

Messages (browser -> kernel)
    {type:"opt_quant", nickname, opt_id, value}   order qty for one supplier/item
    {type:"par",        nickname, value}          par edited
    {type:"insert",      nickname, before_nickname}         add one ingredient
    {type:"selection_action", action:"cut",   nicknames}    remove into clipboard
    {type:"selection_action", action:"paste", before_nickname}  insert clipboard

The kernel records opt_quant/par silently (no rows push-back — the JS
keeps its local copy in sync, so typing doesn't fight a redraw). Every
other message is structural and gets a fresh `rows` trait back, which
fully redraws the table (this also happens to be what closes any open ⋯
menu or in-progress add-input, since those live in DOM nodes the redraw
discards).

Any number of rows can be selected or expanded at once, and the
`.ocw-scroll` container's scroll position is saved before every redraw
and restored after, so none of this ever jumps the list back to the top.
Quantity inputs specifically re-focus themselves (by the same data-i /
data-opt) after a redraw they triggered, so holding the Up/Down arrow key
on a qty box keeps incrementing instead of losing focus after one step.

A live per-supplier summary (units ordered, estimated cost — suppliers
with nothing on order omitted) is recomputed from `rows` on every draw,
so it updates immediately as quantities are edited, without waiting on a
kernel round-trip. Each card is also a toggle filter: click a supplier's
card to narrow the list to just what's on order from them, click "Total"
to narrow it to everything on order regardless of supplier, and click the
same card again (or the "showing: ... ✕" chip that appears next to the
item count) to go back to the full list. This filter combines with the
free-text filter (AND, not OR) rather than replacing it.

A "go to ingredient" box next to the filter (exact match, then
case-insensitive, then a starts-with match against the current nicknames
in `rows`) scrolls that row into view and flashes it briefly to draw the
eye -- clearing the filter first if it's currently hiding the target, so
it always finds a match that's on the list. Purely client-side; it
doesn't touch the kernel.

Every <button> in this widget sets type="button" explicitly. Without it
the DOM default is type="submit", which is harmless in isolation but can
silently eat the click (or trigger a page-level side effect) if the
widget ever ends up inside a host page's <form> -- cheap insurance,
worth keeping on any new button added here.

The supplier/item cell's collapsed summary always includes the total cost
of what's on order for that ingredient (quantity × price, summed across
however many suppliers it's split across). When exactly one supplier/item
is on order it also names that item -- description and size -- since
there's a single unambiguous thing to describe; a split across suppliers
just totals the cost instead of trying to list every item.

Column widths are fixed via a <colgroup> (table-layout: fixed), not
left to the browser to compute from content -- otherwise toggling the
order-filter or typing in the text filter, which changes which rows (and
therefore which cell contents) are visible, would reflow every column
width along with it. Only the last column (supplier/item) is unconstrained
and absorbs whatever width is left; the rest are deliberately narrow,
fixed-px columns sized to their content type (a number input, a short
date, etc.), not to whatever's currently on screen.

Font size
    Everything scales off --ocw-font-size (default 16px) on .ocw-root,
    mirroring the --ggw-* / --rgw-* pattern.
"""

import anywidget
import traitlets


class OrderGridWidget(anywidget.AnyWidget):
    # ── synced state ──────────────────────────────────────────────────────
    rows  = traitlets.List().tag(sync=True)          # list[rowdict], see module docstring
    title = traitlets.Unicode('').tag(sync=True)
    all_nicknames   = traitlets.List(traitlets.Unicode()).tag(sync=True)  # datalist for "Add here"
    has_clipboard   = traitlets.Bool(False).tag(sync=True)
    clipboard_count = traitlets.Int(0).tag(sync=True)

    _css = """
    /* ── Workbench palette: override any of these on a parent element ── */
    .ocw-root { --ocw-font-size: 16px;
                --ocw-ink:        var(--jp-ui-font-color1, #1c2733);
                --ocw-muted:      #66727f;
                --ocw-border:     #dde3ea;
                --ocw-border-soft:#ebeff3;
                --ocw-head-bg:    #f7f9fb;
                --ocw-accent:     #2563eb;
                --ocw-accent-soft:#eaf1fe;
                --ocw-accent-bord:#bcd3fb;
                --ocw-low:        #0f766e;
                --ocw-low-soft:   #e6f5f2;
                --ocw-danger:     #dc2626;
                --ocw-danger-soft:#fdecec;
                --ocw-hover:      #fafbfc;
                --ocw-sel:        #dcebff;
                font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
                font-size: var(--ocw-font-size);
                color: var(--ocw-ink);
                position: relative; }

    /* ── Dark theme override — same variables, new values ────────────── */
    body[data-jp-theme-light="false"] .ocw-root {
        --ocw-muted:       #9aa5af;
        --ocw-border:      #3a4149;
        --ocw-border-soft: #2e343b;
        --ocw-head-bg:     #262b31;
        --ocw-accent:      #5b9dff;
        --ocw-accent-soft: #1c2a3f;
        --ocw-accent-bord: #2f4b74;
        --ocw-low:         #4fd1b8;
        --ocw-low-soft:    #12312b;
        --ocw-danger:      #f87171;
        --ocw-danger-soft: #3a2020;
        --ocw-hover:       #2a3038;
        --ocw-sel:         #1e3352;
    }

    .ocw-topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
                  margin: 4px 0 6px 0; }
    .ocw-title  { font-weight: 600; }
    .ocw-filter { font-size: 0.85em; padding: 3px 8px; width: 220px;
                  border: 1px solid var(--ocw-border); border-radius: 6px;
                  background: var(--jp-layout-color1, #fff);
                  color: var(--ocw-ink); }
    .ocw-filter:focus { outline: 2px solid var(--ocw-accent-soft);
                        border-color: var(--ocw-accent); }
    .ocw-count  { font-size: 0.8em; color: var(--ocw-muted); }
    .ocw-clear-orderfilter { font-size: 0.75em; padding: 1px 8px;
        border-radius: 999px; border: 1px solid var(--ocw-accent-bord);
        background: var(--ocw-accent-soft); color: var(--ocw-accent); cursor: pointer; }
    .ocw-clear-orderfilter:hover { border-color: var(--ocw-danger);
        background: var(--ocw-danger-soft); color: var(--ocw-danger); }

    .ocw-goto-input { font-size: 0.85em; padding: 3px 8px; width: 170px;
                  border: 1px solid var(--ocw-border); border-radius: 6px;
                  background: var(--jp-layout-color1, #fff);
                  color: var(--ocw-ink); }
    .ocw-goto-input:focus { outline: 2px solid var(--ocw-accent-soft);
                        border-color: var(--ocw-accent); }
    .ocw-goto-input.ocw-goto-error { border-color: var(--ocw-danger);
                        background: var(--ocw-danger-soft); }
    .ocw-goto-btn { font-size: 0.85em; padding: 3px 10px;
        border-radius: 6px; border: 1px solid var(--ocw-border);
        background: var(--jp-layout-color1, #fff); color: var(--ocw-muted);
        cursor: pointer; }
    .ocw-goto-btn:hover { background: var(--ocw-accent-soft);
        border-color: var(--ocw-accent-bord); color: var(--ocw-accent); }

    @keyframes ocw-goto-pulse {
        0%, 100% { background: var(--ocw-accent-soft); }
        50% { background: var(--ocw-sel); }
    }
    .ocw tr.ocw-goto-hit td { animation: ocw-goto-pulse 0.55s ease-in-out 3; }

    /* ── live per-supplier order summary ───────────────────────────────── */
    .ocw-summary { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px 0; }
    .ocw-summary-empty { font-size: 0.85em; color: var(--ocw-muted);
                         margin: 0 0 8px 0; }
    .ocw-sum-card { border: 1px solid var(--ocw-border); border-radius: 8px;
        padding: 5px 12px; background: var(--ocw-head-bg); min-width: 120px;
        font: inherit; color: inherit; text-align: left; cursor: pointer;
        transition: border-color .12s ease, box-shadow .12s ease; }
    .ocw-sum-card:hover { border-color: var(--ocw-accent-bord); }
    .ocw-sum-card.ocw-sum-active { border-color: var(--ocw-accent);
        box-shadow: inset 0 0 0 1px var(--ocw-accent); }
    .ocw-sum-name { font-size: 0.7em; font-weight: 600; text-transform: uppercase;
        letter-spacing: .03em; color: var(--ocw-muted); }
    .ocw-sum-nums { font-size: 0.95em; font-weight: 600; color: var(--ocw-ink); }
    .ocw-sum-card.ocw-sum-total { background: var(--ocw-accent-soft);
        border-color: var(--ocw-accent-bord); }
    .ocw-sum-card.ocw-sum-total .ocw-sum-name { color: var(--ocw-accent); }
    .ocw-sum-card.ocw-sum-total.ocw-sum-active { box-shadow: inset 0 0 0 2px var(--ocw-accent); }

    .ocw-scroll { max-height: 560px; overflow-y: auto;
                  border: 1px solid var(--ocw-border); border-radius: 8px; }

    table.ocw { border-collapse: collapse; width: 100%; table-layout: fixed; }
    .ocw th { position: sticky; top: 0; z-index: 1;
              background: var(--ocw-head-bg);
              border-bottom: 1px solid var(--ocw-border);
              font-size: 0.75em; font-weight: 600; text-align: left;
              color: var(--ocw-muted); padding: 5px 8px;
              text-transform: uppercase; letter-spacing: .03em; }
    .ocw td { border-bottom: 1px solid var(--ocw-border-soft);
              padding: 3px 8px; font-size: 0.9em; vertical-align: middle; }
    .ocw tr.ocw-row:hover td { background: var(--ocw-hover); }
    .ocw tr.ocw-row.ocw-selected td { background: var(--ocw-sel); }
    .ocw tr.ocw-has-qty td.ocw-nick { font-weight: 600; }

    .ocw td.ocw-nick   { cursor: pointer; white-space: nowrap; overflow: hidden;
                         text-overflow: ellipsis; user-select: none; touch-action: none; }
    .ocw td.ocw-sel .ocw-caret { display: inline-block; width: 1em;
                                  color: var(--ocw-muted); font-size: 0.8em; }
    .ocw td.ocw-sel    { color: var(--ocw-muted); font-size: 0.85em;
                         cursor: pointer; }
    .ocw td.ocw-sel .ocw-supplier { font-weight: 600; color: var(--ocw-ink); }
    .ocw td.ocw-sel .ocw-nooption { color: var(--ocw-danger); }
    .ocw td.ocw-sel .ocw-suggested { color: var(--ocw-muted); font-style: italic; }
    .ocw td.ocw-sel .ocw-order-cost { font-weight: 600; color: var(--ocw-ink); }

    .ocw td.ocw-qty-display { font-size: 0.9em; color: var(--ocw-muted); }

    .ocw input.ocw-par, .ocw input.ocw-opt-qty, .ocw input.ocw-qty {
        font-size: 0.9em; padding: 2px 5px; width: 62px;
        border: 1px solid var(--ocw-border); border-radius: 6px;
        background: var(--jp-layout-color1, #fff); color: var(--ocw-ink);
        box-sizing: border-box; }
    .ocw input.ocw-par:focus, .ocw input.ocw-opt-qty:focus, .ocw input.ocw-qty:focus {
        outline: 2px solid var(--ocw-accent-soft);
        border-color: var(--ocw-accent); }
    .ocw input.ocw-opt-qty { width: 70px; }
    .ocw input.ocw-qty.ocw-filled { border-color: var(--ocw-accent-bord);
        background: var(--ocw-accent-soft); font-weight: 600; }

    .ocw button.ocw-menu-btn { font-size: 0.85em; padding: 1px 8px;
        border-radius: 6px; border: 1px solid var(--ocw-border);
        background: var(--jp-layout-color1, #fff); color: var(--ocw-muted);
        cursor: pointer; line-height: 1.4; }
    .ocw button.ocw-menu-btn:hover { background: var(--ocw-accent-soft);
        border-color: var(--ocw-accent-bord); color: var(--ocw-accent); }

    /* ── ⋯ popup menu ───────────────────────────────────────────────── */
    .ocw-menu { position: absolute; z-index: 5; min-width: 140px;
        background: var(--jp-layout-color1, #fff); border: 1px solid var(--ocw-border);
        border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        padding: 4px; display: flex; flex-direction: column; }
    .ocw-menu button { display: block; width: 100%; text-align: left;
        font-size: 0.85em; padding: 5px 10px; border: none; border-radius: 5px;
        background: transparent; color: var(--ocw-ink); cursor: pointer; }
    .ocw-menu button:hover:not(:disabled) { background: var(--ocw-accent-soft);
        color: var(--ocw-accent); }
    .ocw-menu button:disabled { color: var(--ocw-muted); cursor: default; opacity: 0.6; }

    /* ── inline add-row / bottom add-link row ──────────────────────────── */
    .ocw tr.ocw-add-row > td { padding: 4px 8px; }
    .ocw input.ocw-add-input { width: 100%; font-size: 0.9em; padding: 4px 8px;
        border: 1px solid var(--ocw-accent-bord); border-radius: 6px;
        background: var(--ocw-accent-soft); color: var(--ocw-ink);
        box-sizing: border-box; }
    .ocw input.ocw-add-input:focus { outline: 2px solid var(--ocw-accent-soft);
        border-color: var(--ocw-accent); }
    .ocw tr.ocw-addlink-row > td { padding: 6px 8px; }
    .ocw button.ocw-addlink { font-size: 0.85em; padding: 3px 10px;
        border-radius: 6px; border: 1px dashed var(--ocw-border);
        background: transparent; color: var(--ocw-muted); cursor: pointer; }
    .ocw button.ocw-addlink:hover { border-color: var(--ocw-accent);
        color: var(--ocw-accent); }
    .ocw button.ocw-pasteend { font-size: 0.85em; padding: 3px 10px;
        margin-left: 8px; border-radius: 6px; border: 1px solid var(--ocw-accent-bord);
        background: var(--ocw-accent-soft); color: var(--ocw-accent); cursor: pointer; }

    /* ── expanded options sub-table ──────────────────────────────────── */
    .ocw tr.ocw-opts > td { background: var(--ocw-head-bg); padding: 6px 10px 10px 30px; }
    table.ocw-opt-table { border-collapse: collapse; width: 100%; }
    .ocw-opt-table th { font-size: 0.7em; color: var(--ocw-muted);
                        text-align: left; padding: 2px 8px;
                        text-transform: uppercase; letter-spacing: .03em;
                        position: static; background: none; border: none; }
    .ocw-opt-table td { font-size: 0.85em; padding: 3px 8px;
                        border-bottom: 1px solid var(--ocw-border-soft); }
    .ocw-opt-table tr.ocw-opt-active td {
        background: var(--ocw-low-soft); }
    .ocw-badge-low { display: inline-block; margin-left: 6px;
        font-size: 0.7em; font-weight: 600; padding: 0 6px;
        border-radius: 999px; color: var(--ocw-low);
        background: var(--ocw-low-soft); }
    """

    _esm = """
    const esc = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

    const fmtNum = (v) => {
      if (v === null || v === undefined || v === "") return "";
      const n = Number(v);
      if (!isFinite(n)) return esc(v);
      return Number.isInteger(n) ? String(n) : String(+n.toFixed(2));
    };
    const fmtMoney = (v) => {
      const n = Number(String(v ?? "").replace(/^\\$/, ""));
      return isFinite(n) ? "$" + n.toFixed(2) : esc(v ?? "");
    };
    const num0 = (v) => { const n = Number(v); return isFinite(n) ? n : 0; };
    const NCOLS = 6;   // menu, ingredient, order qty, par, last order, supplier/item
    const ORDER_FILTER_ALL = "__all__";   // sentinel for the "Total" summary card's filter

    function render({ model, el }) {
      el.classList.add("ocw-root");

      // Local working copy — quant/par edits mutate this and message the
      // kernel, WITHOUT the kernel pushing `rows` back per keystroke (which
      // would redraw mid-typing). Structural changes reassign the trait and
      // land in the change:rows handler below.
      let rows = JSON.parse(JSON.stringify(model.get("rows") || []));
      let openSet = new Set();       // nicknames whose options are expanded
      let filterText = "";
      let selected = new Set();      // nicknames selected via the handle column
      let pendingAdd = null;         // { beforeNickname: string|null } while the inline add-input shows
      let dragAnchor = null, dragMoved = false, baseSelection = null;
      let gotoNick = null;           // nickname currently highlighted by "Go to"
      let gotoHighlightTimer = null;
      let orderFilter = null;        // null | supplier name | ORDER_FILTER_ALL -- toggled via the summary cards

      const rowTotalQuant = (row) =>
        (row.options || []).reduce((s, o) => s + num0(o.quant), 0);

      const activeOpts = (row) =>
        (row.options || []).filter((o) => num0(o.quant) > 0);

      const visibleRows = () => rows.filter(matchesFilter);
      function matchesFilter(row) {
        if (orderFilter) {
          const ordered = orderFilter === ORDER_FILTER_ALL
            ? rowTotalQuant(row) > 0
            : (row.options || []).some((o) => o.supplier === orderFilter && num0(o.quant) > 0);
          if (!ordered) return false;
        }
        if (!filterText) return true;
        const t = filterText.toLowerCase();
        if (row.nickname.toLowerCase().includes(t)) return true;
        return (row.options || []).some((o) =>
          String(o.description ?? "").toLowerCase().includes(t) ||
          String(o.supplier ?? "").toLowerCase().includes(t));
      }
      const nicksBetween = (a, b) => {
        const vis = visibleRows().map((r) => r.nickname);
        const ia = vis.indexOf(a), ib = vis.indexOf(b);
        if (ia === -1 || ib === -1) return [a, b].filter(Boolean);
        const [lo, hi] = ia < ib ? [ia, ib] : [ib, ia];
        return vis.slice(lo, hi + 1);
      };

      const optCost = (o) => {
        const casePrice = Number(String(o.case_price ?? o.price ?? "").replace(/^\\$/, ""));
        return isFinite(casePrice) ? num0(o.quant) * casePrice : 0;
      };

      const collapsedSummary = (row) => {
        const active = activeOpts(row);
        if (active.length) {
          const parts = active.map((o) =>
            `<span class="ocw-supplier">${esc(o.supplier)}</span> × ${fmtNum(o.quant)}`
          ).join(" + ");
          const totalCost = active.reduce((s, o) => s + optCost(o), 0);
          if (active.length === 1) {
            // exactly one supplier/item on order -- show what it actually is
            const o = active[0];
            return `${parts} · ${esc(o.description)} · ${esc(o.size)} · ` +
              `<span class="ocw-order-cost">${fmtMoney(totalCost)}</span>`;
          }
          // split across suppliers -- descriptions would be cluttered, just total it
          return `${parts} · <span class="ocw-order-cost">${fmtMoney(totalCost)}</span>`;
        }
        const opts = row.options || [];
        if (!opts.length)
          return `<span class="ocw-nooption">no price entries</span>`;
        const low = opts.find((o) => o.low) || opts[0];
        const per = low.per_quant ? ` · ${esc(low.per_quant)}` : "";
        return `<span class="ocw-suggested">suggest: ` +
          `<span class="ocw-supplier">${esc(low.supplier)}</span> · ` +
          `${esc(low.description)} · ${esc(low.size)} · ${fmtMoney(low.price)}${per}</span>`;
      };

      // ── live per-supplier summary — recomputed from `rows` every draw ──
      const supplierTotals = () => {
        const totals = {};    // supplier -> {units, cost}
        for (const row of rows) {
          for (const o of (row.options || [])) {
            const q = num0(o.quant);
            if (q <= 0) continue;
            const t = totals[o.supplier] || (totals[o.supplier] = { units: 0, cost: 0 });
            t.units += q;
            const casePrice = Number(String(o.case_price ?? o.price ??
            "").replace(/^\\$/, ""));
            if (isFinite(casePrice)) t.cost += q * casePrice;
          }
        }
        return totals;
      };

      const drawSummary = () => {
        const totals = supplierTotals();
        const suppliers = Object.keys(totals).sort();
        if (!suppliers.length)
          return `<div class="ocw-summary-empty">No quantities entered yet.</div>`;
        let gUnits = 0, gCost = 0;
        let html = `<div class="ocw-summary">`;
        for (const s of suppliers) {
          const t = totals[s];
          gUnits += t.units; gCost += t.cost;
          const active = orderFilter === s;
          html += `<button type="button" class="ocw-sum-card${active ? " ocw-sum-active" : ""}" ` +
            `data-filter="${esc(s)}" title="Click to filter the list to ${esc(s)}'s order">` +
            `<div class="ocw-sum-name">${esc(s)}</div>` +
            `<div class="ocw-sum-nums">${fmtNum(t.units)} units · ${fmtMoney(t.cost)}</div></button>`;
        }
        if (suppliers.length > 1) {
          const activeTotal = orderFilter === ORDER_FILTER_ALL;
          html += `<button type="button" class="ocw-sum-card ocw-sum-total` +
            `${activeTotal ? " ocw-sum-active" : ""}" data-filter="${ORDER_FILTER_ALL}" ` +
            `title="Click to filter the list to everything on order">` +
            `<div class="ocw-sum-name">Total</div>` +
            `<div class="ocw-sum-nums">${fmtNum(gUnits)} units · ${fmtMoney(gCost)}</div></button>`;
        }
        html += `</div>`;
        return html;
      };

      const datalistHtml = () => {
        const nicks = model.get("all_nicknames") || [];
        return `<datalist id="ocw-add-datalist">` +
          nicks.map((n) => `<option value="${esc(n)}"></option>`).join("") +
          `</datalist>`;
      };

      const addInputRow = () => {
        return `<tr class="ocw-add-row"><td colspan="${NCOLS}">` +
          `<input class="ocw-add-input" type="text" list="ocw-add-datalist" ` +
          `placeholder="type an ingredient nickname, then Enter…"></td></tr>`;
      };

      const addLinkRow = () => {
        const hasClip = model.get("has_clipboard");
        const n = model.get("clipboard_count") || 0;
        return `<tr class="ocw-addlink-row"><td colspan="${NCOLS}">` +
          `<button type="button" class="ocw-addlink">+ Add ingredient</button>` +
          (hasClip ? `<button type="button" class="ocw-pasteend">Paste here (${n})</button>` : ``) +
          `</td></tr>`;
      };

      const draw = () => {
        // Preserve scroll position — replacing el.innerHTML replaces the
        // .ocw-scroll node itself, which would otherwise reset to the top
        // on every expand/collapse or quantity edit.
        const oldScrollBox = el.querySelector(".ocw-scroll");
        const savedScroll = oldScrollBox ? oldScrollBox.scrollTop : 0;

        let html = `<div class="ocw-topbar">`;
        const title = model.get("title") || "";
        if (title) html += `<span class="ocw-title">${esc(title)}</span>`;
        html += `<input class="ocw-filter" type="text" ` +
                `placeholder="filter ingredients…" value="${esc(filterText)}">`;
        html += `<input class="ocw-goto-input" type="text" list="ocw-add-datalist" ` +
                `placeholder="go to ingredient…" value="">` +
                `<button type="button" class="ocw-goto-btn">Go to</button>`;
        const nQty = rows.filter((r) => rowTotalQuant(r) > 0).length;
        html += `<span class="ocw-count">${rows.length} items` +
                (nQty ? ` · ${nQty} to order` : "") + `</span>`;
        if (orderFilter) {
          const label = orderFilter === ORDER_FILTER_ALL ? "on order" : orderFilter;
          html += `<button type="button" class="ocw-clear-orderfilter">` +
                  `showing: ${esc(label)} ✕</button>`;
        }
        html += `</div>`;

        html += drawSummary();
        html += datalistHtml();

        html += `<div class="ocw-scroll"><table class="ocw"><colgroup>` +
          `<col style="width:34px"><col style="width:130px"><col style="width:100px">` +
          `<col style="width:70px"><col style="width:80px"><col></colgroup>` +
          `<thead><tr><th></th><th>ingredient</th><th>order qty</th><th>par</th>` +
          `<th>last order</th><th>supplier / item</th></tr></thead><tbody>`;

        rows.forEach((row, i) => {
          if (!matchesFilter(row)) return;

          if (pendingAdd && pendingAdd.beforeNickname === row.nickname) {
            html += addInputRow();
          }

          const total = rowTotalQuant(row);
          const hasQty = total > 0;
          const isOpen = openSet.has(row.nickname);
          const isSel = selected.has(row.nickname);
          const isGotoHit = gotoNick === row.nickname;
          const caret = isOpen ? "▾" : "▸";
          html += `<tr class="ocw-row${hasQty ? " ocw-has-qty" : ""}` +
                  `${isSel ? " ocw-selected" : ""}${isGotoHit ? " ocw-goto-hit" : ""}" data-i="${i}">`;
          html += `<td><button type="button" class="ocw-menu-btn" data-nick="${esc(row.nickname)}" ` +
                  `title="add / cut / paste">⋯</button></td>`;
          html += `<td class="ocw-nick" data-i="${i}" data-nick="${esc(row.nickname)}">` +
                  `${esc(row.nickname)}</td>`;
          const opts0 = row.options || [];
          if (opts0.length) {
            html += `<td><input class="ocw-qty${hasQty ? " ocw-filled" : ""}" ` +
                    `type="number" min="0" step="any" data-i="${i}" ` +
                    `value="${hasQty ? total : ""}"></td>`;
          } else {
            html += `<td class="ocw-qty-display">—</td>`;
          }
          html += `<td><input class="ocw-par" type="number" min="0" step="any" ` +
                  `data-i="${i}" value="${row.par ?? ""}"></td>`;
          html += `<td>${fmtNum(row.last)}</td>`;
          html += `<td class="ocw-sel" data-i="${i}"><span class="ocw-caret">${caret}</span>` +
                  `${collapsedSummary(row)}</td></tr>`;

          if (isOpen) {
            html += `<tr class="ocw-opts"><td colspan="${NCOLS}">`;
            const opts = row.options || [];
            if (!opts.length) {
              html += `<span class="ocw-nooption">No price entries for this ` +
                      `ingredient — load current prices or add it to the guide.</span>`;
            } else {
              html += `<table class="ocw-opt-table"><thead><tr><th>order qty</th>` +
                `<th>supplier</th><th>number</th><th>description</th>` +
                `<th>size</th><th>price</th><th>$/quant</th><th>date</th>` +
                `</tr></thead><tbody>`;
              for (const o of opts) {
                const q = num0(o.quant);
                html += `<tr class="${q > 0 ? "ocw-opt-active" : ""}">` +
                  `<td><input class="ocw-opt-qty" type="number" min="0" step="any" ` +
                  `data-i="${i}" data-opt="${o.opt_id}" value="${q > 0 ? o.quant : ""}"></td>` +
                  `<td>${esc(o.supplier)}</td><td>${esc(o.number)}</td>` +
                  `<td>${esc(o.description)}</td><td>${esc(o.size)}</td>` +
                  `<td>${fmtMoney(o.price)}</td>` +
                  `<td>${esc(o.per_quant)}${o.low
                      ? '<span class="ocw-badge-low">low</span>' : ""}</td>` +
                  `<td>${esc(o.date)}</td></tr>`;
              }
              html += `</tbody></table>`;
            }
            html += `</td></tr>`;
          }
        });

        if (pendingAdd && pendingAdd.beforeNickname === null) {
          html += addInputRow();
        } else {
          html += addLinkRow();
        }

        html += `</tbody></table></div>`;
        el.innerHTML = html;

        const newScrollBox = el.querySelector(".ocw-scroll");
        if (newScrollBox) newScrollBox.scrollTop = savedScroll;

        wire();
      };

      const refocusMainQty = (i) => {
        const again = el.querySelector(`input.ocw-qty[data-i="${i}"]`);
        if (again) again.focus();
      };

      // The full Enter/Shift+Enter path through the grid, in on-screen
      // order: each row with any price options contributes its main qty
      // box, immediately followed -- if that row happens to be expanded
      // right now -- by each of its own option qty boxes, before moving
      // on to the next row's main box. A collapsed row only contributes
      // its main box; a row with no price options at all contributes
      // nothing (there's no input to land on).
      const flatQtySequence = () => {
        const flat = [];
        rows.forEach((row, i) => {
          if (!matchesFilter(row)) return;
          const opts = row.options || [];
          if (!opts.length) return;
          flat.push({ type: "main", i });
          if (openSet.has(row.nickname)) {
            for (const o of opts) flat.push({ type: "opt", i, optId: o.opt_id });
          }
        });
        return flat;
      };
      const findFlatIndex = (flat, entry) => flat.findIndex((e) =>
        e.type === entry.type && e.i === entry.i &&
        (e.type !== "opt" || e.optId === entry.optId));
      const focusFlatEntry = (entry) => {
        if (!entry) return;
        const sel = entry.type === "main"
          ? `input.ocw-qty[data-i="${entry.i}"]`
          : `input.ocw-opt-qty[data-i="${entry.i}"][data-opt="${entry.optId}"]`;
        const node = el.querySelector(sel);
        if (node) { node.focus(); node.select(); }
      };
      const nextFlatEntry = (entry, shiftKey) => {
        const flat = flatQtySequence();
        const pos = findFlatIndex(flat, entry);
        if (shiftKey) return pos > 0 ? flat[pos - 1] : null;
        return (pos >= 0 && pos + 1 < flat.length) ? flat[pos + 1] : null;
      };

      // ── ⋯ popup menu ────────────────────────────────────────────────
      function closeMenu() {
        el.querySelector(".ocw-menu")?.remove();
        document.removeEventListener("pointerdown", onOutsideClick, true);
      }
      function onOutsideClick(e) {
        if (!e.target.closest(".ocw-menu") && !e.target.closest(".ocw-menu-btn")) closeMenu();
      }
      function openMenu(nick, btn) {
        closeMenu();
        const r = btn.getBoundingClientRect(), rootR = el.getBoundingClientRect();
        const menu = document.createElement("div");
        menu.className = "ocw-menu";
        menu.style.left = Math.max(0, r.left - rootR.left) + "px";
        menu.style.top = (r.bottom - rootR.top + 3) + "px";

        const actingOn = (selected.has(nick) && selected.size > 1)
          ? Array.from(selected) : [nick];
        const hasClip = model.get("has_clipboard");

        menu.innerHTML =
          `<button type="button" data-action="add">Add here…</button>` +
          `<button type="button" data-action="cut">Cut${actingOn.length > 1 ? ` (${actingOn.length})` : ""}</button>` +
          `<button type="button" data-action="paste" ${hasClip ? "" : "disabled"}>Paste here</button>`;

        menu.querySelectorAll("button[data-action]").forEach((b) => {
          b.addEventListener("click", (ev) => {
            ev.stopPropagation();
            const action = b.dataset.action;
            closeMenu();
            if (action === "add") {
              pendingAdd = { beforeNickname: nick };
              draw();
              const inp = el.querySelector(".ocw-add-input");
              if (inp) inp.focus();
            } else if (action === "cut") {
              selected = new Set();
              model.send({ type: "selection_action", action: "cut", nicknames: actingOn });
            } else if (action === "paste") {
              model.send({ type: "selection_action", action: "paste", before_nickname: nick });
            }
          });
        });

        el.appendChild(menu);
        document.addEventListener("pointerdown", onOutsideClick, true);
      }

      const wire = () => {
        const filter = el.querySelector(".ocw-filter");
        filter.addEventListener("input", () => {
          filterText = filter.value;
          draw();
          const f = el.querySelector(".ocw-filter");
          f.focus();
          f.setSelectionRange(f.value.length, f.value.length);
        });

        const gotoInput = el.querySelector(".ocw-goto-input");
        const gotoBtn = el.querySelector(".ocw-goto-btn");
        const doGoto = () => {
          const val = gotoInput.value.trim();
          if (!val) return;
          const lower = val.toLowerCase();
          const target = rows.find((r) => r.nickname === val)
            || rows.find((r) => r.nickname.toLowerCase() === lower)
            || rows.find((r) => r.nickname.toLowerCase().startsWith(lower));
          if (!target) {
            gotoInput.classList.add("ocw-goto-error");
            setTimeout(() => gotoInput.classList.remove("ocw-goto-error"), 1200);
            return;
          }
          // the target might be hidden by the current filter -- clear it
          // so "go to" always works regardless of what's currently typed
          if (filterText && !matchesFilter(target)) filterText = "";
          gotoInput.value = "";
          gotoNick = target.nickname;
          draw();
          const rowEl = el.querySelector(`tr.ocw-row[data-i="${rows.indexOf(target)}"]`);
          if (rowEl) rowEl.scrollIntoView({ block: "center", behavior: "smooth" });
          clearTimeout(gotoHighlightTimer);
          gotoHighlightTimer = setTimeout(() => { gotoNick = null; draw(); }, 2000);
        };
        gotoBtn.addEventListener("click", doGoto);
        gotoInput.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); doGoto(); }
        });

        el.querySelectorAll("button.ocw-sum-card").forEach((btn) => {
          btn.addEventListener("click", () => {
            const f = btn.dataset.filter;
            orderFilter = (orderFilter === f) ? null : f;   // click again to toggle off
            draw();
          });
        });
        const clearBtn = el.querySelector(".ocw-clear-orderfilter");
        if (clearBtn) {
          clearBtn.addEventListener("click", () => { orderFilter = null; draw(); });
        }

        el.querySelectorAll("td.ocw-sel").forEach((td) => {
          td.addEventListener("click", () => {
            const row = rows[Number(td.dataset.i)];
            if (openSet.has(row.nickname)) openSet.delete(row.nickname);
            else openSet.add(row.nickname);
            draw();
          });
        });

        // Main "order qty" box. Refocuses itself after every redraw it
        // triggers (not just on Enter) so holding an arrow key -- which
        // fires a native `change` on every step -- keeps incrementing
        // instead of the input losing focus after the first press.
        el.querySelectorAll("input.ocw-qty").forEach((inp) => {
          const commit = () => {
            const i = Number(inp.dataset.i);
            const row = rows[i];
            const opts = row.options || [];
            if (!opts.length) return;
            const raw = inp.value === "" ? 0 : Number(inp.value);
            const newTotal = (isFinite(raw) && raw > 0) ? raw : 0;
            const oldTotal = rowTotalQuant(row);
            const delta = newTotal - oldTotal;
            if (delta === 0) return;

            const suggested = opts.find((o) => o.low) || opts[0];
            if (delta > 0) {
              suggested.quant = num0(suggested.quant) + delta;
              model.send({ type: "opt_quant", nickname: row.nickname,
                           opt_id: suggested.opt_id, value: suggested.quant });
            } else {
              let remaining = -delta;
              const order = [suggested, ...opts.filter((o) => o !== suggested)];
              for (const o of order) {
                if (remaining <= 0) break;
                const cur = num0(o.quant);
                if (cur <= 0) continue;
                const take = Math.min(cur, remaining);
                o.quant = cur - take;
                remaining -= take;
                model.send({ type: "opt_quant", nickname: row.nickname,
                             opt_id: o.opt_id, value: o.quant });
              }
            }
          };
          inp.addEventListener("change", () => {
            const i = Number(inp.dataset.i);
            commit();
            draw();
            const again = el.querySelector(`input.ocw-qty[data-i="${i}"]`);
            if (again) again.focus();
          });
          inp.addEventListener("keydown", (ev) => {
            const i = Number(inp.dataset.i);
            if (ev.key === "Enter") {
              ev.preventDefault();
              const target = nextFlatEntry({ type: "main", i }, ev.shiftKey);
              inp.blur();                 // triggers the `change` handler above
              focusFlatEntry(target);
              return;
            }
            // Right/Left expand or collapse this row's price options --
            // takes over the arrow keys entirely while a qty box has
            // focus (type="number" inputs don't reliably support checking
            // cursor position across browsers, so there's no reliable way
            // to fall back to normal in-field cursor movement here).
            if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
              ev.preventDefault();
              const row = rows[i];
              const isOpen = openSet.has(row.nickname);
              if (ev.key === "ArrowRight" && !isOpen) {
                openSet.add(row.nickname);
                draw();
                refocusMainQty(i);
              } else if (ev.key === "ArrowLeft" && isOpen) {
                openSet.delete(row.nickname);
                draw();
                refocusMainQty(i);
              }
            }
          });
        });

        el.querySelectorAll("input.ocw-par").forEach((inp) => {
          const commit = () => {
            const row = rows[Number(inp.dataset.i)];
            const v = inp.value === "" ? null : Number(inp.value);
            row.par = (v !== null && isFinite(v)) ? v : null;
            model.send({ type: "par", nickname: row.nickname, value: row.par });
          };
          inp.addEventListener("change", commit);
          inp.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") { ev.preventDefault(); inp.blur(); }
          });
        });

        // Per-option qty inputs — same refocus-after-change fix as the
        // main qty box above.
        el.querySelectorAll("input.ocw-opt-qty").forEach((inp) => {
          const commit = () => {
            const i = Number(inp.dataset.i);
            const optId = Number(inp.dataset.opt);
            const row = rows[i];
            const opt = (row.options || []).find((o) => o.opt_id === optId);
            if (!opt) return;
            const v = inp.value === "" ? 0 : Number(inp.value);
            opt.quant = (isFinite(v) && v > 0) ? v : 0;
            model.send({ type: "opt_quant", nickname: row.nickname,
                         opt_id: optId, value: opt.quant });
          };
          inp.addEventListener("change", () => {
            const i = Number(inp.dataset.i);
            const optId = Number(inp.dataset.opt);
            commit();
            draw();
            const again = el.querySelector(
              `input.ocw-opt-qty[data-i="${i}"][data-opt="${optId}"]`);
            if (again) again.focus();
          });
          inp.addEventListener("keydown", (ev) => {
            const i = Number(inp.dataset.i);
            const optId = Number(inp.dataset.opt);
            if (ev.key === "Enter") {
              ev.preventDefault();
              const target = nextFlatEntry({ type: "opt", i, optId }, ev.shiftKey);
              inp.blur();                 // triggers the `change` handler above
              focusFlatEntry(target);
              return;
            }
            if (ev.key === "ArrowLeft") {
              ev.preventDefault();
              const row = rows[i];
              openSet.delete(row.nickname);
              draw();
              refocusMainQty(i);
            }
          });
        });

        el.querySelectorAll("button.ocw-menu-btn").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            if (el.querySelector(".ocw-menu")) { closeMenu(); return; }
            openMenu(btn.dataset.nick, btn);
          });
        });

        el.querySelectorAll("button.ocw-addlink").forEach((btn) => {
          btn.addEventListener("click", () => {
            pendingAdd = { beforeNickname: null };
            draw();
            const inp = el.querySelector(".ocw-add-input");
            if (inp) inp.focus();
          });
        });
        el.querySelectorAll("button.ocw-pasteend").forEach((btn) => {
          btn.addEventListener("click", () => {
            model.send({ type: "selection_action", action: "paste", before_nickname: null });
          });
        });

        const addInp = el.querySelector(".ocw-add-input");
        if (addInp) {
          const cancel = () => { pendingAdd = null; draw(); };
          const commitAdd = () => {
            const val = addInp.value.trim();
            const before = pendingAdd ? pendingAdd.beforeNickname : null;
            pendingAdd = null;
            if (val) model.send({ type: "insert", nickname: val, before_nickname: before });
            else draw();
          };
          addInp.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") { ev.preventDefault(); commitAdd(); }
            else if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
          });
          addInp.addEventListener("blur", () => { if (pendingAdd) cancel(); });
        }
      };

      // ── selection: tap the nickname cell to toggle, drag across
      // nickname cells to extend a range -- same gesture as the recipe
      // grid's row selection. Delegated on `el` itself (not re-wired every
      // draw, since `el` survives the innerHTML replacement that redraws
      // everything inside it). Uses elementFromPoint so it tracks touch
      // drags too, which don't retarget the way mousemove does. ──
      el.addEventListener("pointerdown", (e) => {
        const handle = e.target.closest(".ocw-nick");
        if (handle) {
          dragAnchor = handle.dataset.nick;
          dragMoved = false;
          baseSelection = new Set(selected);
          selected = new Set(baseSelection);
          selected.add(dragAnchor);
          draw();
          return;
        }
        if (e.target.closest(".ocw-menu") || e.target.closest(".ocw-menu-btn")
            || e.target.closest("input") || e.target.closest("button")
            || e.target.closest(".ocw-sel")) return;
        if (selected.size) { selected = new Set(); draw(); }
        closeMenu();
      });
      el.addEventListener("pointermove", (e) => {
        if (dragAnchor === null) return;
        const target = document.elementFromPoint(e.clientX, e.clientY);
        const handle = target && target.closest && target.closest(".ocw-nick");
        if (!handle) return;
        const nick = handle.dataset.nick;
        if (nick !== dragAnchor) dragMoved = true;
        const merged = new Set(baseSelection);
        for (const n of nicksBetween(dragAnchor, nick)) merged.add(n);
        selected = merged;
        draw();
      });
      el.addEventListener("pointerup", () => {
        if (dragAnchor === null) return;
        if (!dragMoved && baseSelection.has(dragAnchor)) {
          const merged = new Set(baseSelection);
          merged.delete(dragAnchor);
          selected = merged;
          draw();
        }
        dragAnchor = null; dragMoved = false; baseSelection = null;
      });

      model.on("change:rows", () => {
        rows = JSON.parse(JSON.stringify(model.get("rows") || []));
        draw();
      });
      model.on("change:title", draw);
      model.on("change:all_nicknames", draw);
      model.on("change:has_clipboard", draw);
      model.on("change:clipboard_count", draw);

      draw();
    }

    export default { render };
    """

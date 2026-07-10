"""
guide_grid_widget.py — anywidget-based fast grid for DataFrameWidget's
guide (price-entry) display.

Renders a nickname's guide entries (one row per supplier/price/date entry)
as a single anywidget model instead of one ipywidgets widget per cell —
the guide-display equivalent of recipe_grid_widget.py's RecipeGridWidget.
See DataFrameWidget's _update_display_fast_guide / _on_fast_guide_grid_msg
for the Python-side integration.

Cell model
    Each cell is a dict: {"v": display value, "e": editable bool, "k": kind}
    kinds: "t" text input (when editable), "l" label. Unlike the recipe
    grid there's no header row, add-row, ingredient-combobox cell, or
    scale input — every row is a peer price entry, and editability is
    driven entirely by column membership in DataFrameWidget.enabled_columns
    (exactly mirroring create_row's is_disabled check for df_type=='guide').

    row_used is a flat list of bools parallel to rows: True highlights that
    row as one cost_picker is currently using for cost calculation.

Messages (browser -> kernel)
    {type:"edit",      row, col, old, new}
    {type:"duplicate", row}
    {type:"delete",    row}
    {type:"mode",      value}

Messages (kernel -> browser)
    {type:"cell_invalid", row, col}   red-border a cell

Font size
    Everything scales off one CSS variable, --ggw-font-size (default 16px),
    set on .ggw-root; button/select/input font-sizes are expressed in `em`
    so they stay proportional. Override by setting the variable on a parent
    element, or edit the default in _css below.
"""

import anywidget
import traitlets


class GuideGridWidget(anywidget.AnyWidget):
    # ── synced state ──────────────────────────────────────────────────────
    columns    = traitlets.List(traitlets.Unicode()).tag(sync=True)
    rows       = traitlets.List().tag(sync=True)   # list[list[celldict]]
    row_used   = traitlets.List(traitlets.Bool()).tag(sync=True)  # parallel to rows: True
                                                                    # if cost_picker is using
                                                                    # that entry right now
    title      = traitlets.Unicode('').tag(sync=True)
    mode       = traitlets.Unicode('Edit').tag(sync=True)
    modes      = traitlets.List(traitlets.Unicode(),
                                default_value=['Edit', 'View']).tag(sync=True)

    _css = """
    /* ── Workbench palette: override any of these on a parent element ── */
    .ggw-root { --ggw-font-size: 16px;
                --ggw-ink:        var(--jp-ui-font-color1, #1c2733);
                --ggw-muted:      #66727f;
                --ggw-border:     #dde3ea;
                --ggw-border-soft:#ebeff3;
                --ggw-head-bg:    #f7f9fb;
                --ggw-accent:     #2563eb;
                --ggw-accent-soft:#eaf1fe;
                --ggw-accent-bord:#bcd3fb;
                --ggw-danger:     #dc2626;
                --ggw-danger-soft:#fdecec;
                --ggw-danger-bord:#f6bcbc;
                --ggw-hover:      #fafbfc;
                font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
                font-size: var(--ggw-font-size);
                color: var(--ggw-ink);
                position: relative; }

    /* ── Dark theme override — same variables, new values ────────────── */
    body[data-jp-theme-light="false"] .ggw-root {
        --ggw-muted:       #9aa5af;
        --ggw-border:      #3a4149;
        --ggw-border-soft: #2e343b;
        --ggw-head-bg:     #262b31;
        --ggw-accent:      #5b9dff;
        --ggw-accent-soft: #1c2a3f;
        --ggw-accent-bord: #2f4b74;
        --ggw-danger:      #f87171;
        --ggw-danger-soft: #3a2020;
        --ggw-danger-bord: #6b3232;
        --ggw-hover:       #2a3038;
    }

    /* Fallback if something ever renders the widget outside a Jupyter
       shell (no data-jp-theme-light attribute present) — defer to the OS. */
    @media (prefers-color-scheme: dark) {
        body:not([data-jp-theme-light]) .ggw-root {
            --ggw-muted:       #9aa5af;
            --ggw-border:      #3a4149;
            --ggw-border-soft: #2e343b;
            --ggw-head-bg:     #262b31;
            --ggw-accent:      #5b9dff;
            --ggw-accent-soft: #1c2a3f;
            --ggw-accent-bord: #2f4b74;
            --ggw-danger:      #f87171;
            --ggw-danger-soft: #3a2020;
            --ggw-danger-bord: #6b3232;
            --ggw-hover:       #2a3038;
        }
    }

    .ggw-topbar { display: flex; align-items: center; gap: 6px;
                  padding: 2px 2px 5px; }
    .ggw-title  { font-size: 0.7em; font-weight: 700; letter-spacing: 0.07em;
                  text-transform: uppercase; color: var(--ggw-muted); }
    .ggw-topbar label { font-size: 0.72em; color: var(--ggw-muted); }

    table.ggw { border-collapse: collapse; margin: 2px 0; table-layout: fixed;
                width: 0;   /* stops the table stretching to fill its container —
                               without this, table-layout:fixed still treats col
                               widths as ratios to expand, not exact pixel sizes */
                background: var(--jp-layout-color1, #fff); }
    table.ggw th { text-align: left; font-size: 0.68em; font-weight: 700;
                   letter-spacing: 0.06em; text-transform: uppercase;
                   color: var(--ggw-muted);
                   padding: 5px 8px 5px 4px;
                   border-bottom: 1px solid var(--ggw-border-soft);
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    table.ggw td { padding: 4px 8px 4px 4px;
                   border-bottom: 1px solid var(--ggw-border-soft);
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                   color: var(--ggw-ink); }

    tr.ggw-row:hover td { background: var(--ggw-hover); }
    tr.ggw-row.ggw-used td { background: var(--ggw-accent-soft);
                             border-bottom-color: var(--ggw-accent-bord); }
    tr.ggw-row.ggw-used:hover td { background: var(--ggw-accent-soft); filter: brightness(0.97); }
    tr.ggw-row.ggw-used td:first-child { box-shadow: inset 3px 0 0 var(--ggw-accent); }

    .ggw-btns { white-space: nowrap; overflow: visible; }
    .ggw button { font-size: 0.75em; padding: 2px 8px; margin-right: 3px;
                  border: 1px solid var(--ggw-border); border-radius: 6px;
                  background: var(--jp-layout-color1, #fff);
                  color: var(--ggw-muted); cursor: pointer; }
    .ggw button:hover:not(:disabled) { background: var(--ggw-accent-soft);
                                       border-color: var(--ggw-accent-bord);
                                       color: var(--ggw-accent); }
    .ggw button.ggw-delete:hover:not(:disabled) { background: var(--ggw-danger-soft);
                                                  border-color: var(--ggw-danger-bord);
                                                  color: var(--ggw-danger); }
    .ggw button:disabled { opacity: 0.45; cursor: default; }

    .ggw select { font-size: 0.75em; padding: 2px 5px; max-width: 100%;
                  border: 1px solid var(--ggw-border); border-radius: 6px;
                  background: var(--jp-layout-color1, #fff); color: var(--ggw-ink); }
    .ggw input { font-size: 0.9em; padding: 2px 5px;
                 border: 1px solid var(--ggw-border); border-radius: 6px;
                 width: 100%; min-width: 40px; box-sizing: border-box; }
    .ggw input:focus { outline: 2px solid var(--ggw-accent-soft);
                       border-color: var(--ggw-accent); }
    .ggw input.ggw-invalid { border-color: var(--jp-error-color1, red);
                             outline-color: var(--jp-error-color1, red); }
    """

    _esm = """
    const esc = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

    function render({ model, el }) {
      el.classList.add("ggw-root");
      let scheduled = false;

      const draw = () => {
        const cols   = model.get("columns")    || [];
        const rows   = model.get("rows")       || [];
        const used   = model.get("row_used")   || [];
        const mode   = model.get("mode");
        const modes  = model.get("modes")      || [];
        const title  = model.get("title")      || "";
        const editing = mode !== "View";
        // css-safe per-column class, e.g. "$/quant" -> "ggw-c--quant"
        const colCls = (j) => "ggw-c-" +
          String(cols[j]).toLowerCase().replace(/[^a-z0-9]+/g, "-");

        // Size each column off the longest string it's actually about to
        // display (header or cell) — measuring the real rendered text
        // avoids drift from any separately-computed estimate.
        const CHAR_PX      = 9;    // ~avg glyph width at the 0.9em input font
        const LABEL_CHROME = 14;   // breathing room for a plain label cell
        const INPUT_CHROME = 20;   // border + padding for an <input>
        const MIN_W        = 46;
        const widthFor = (j) => {
          let maxLen = String(cols[j]).length;
          let editableCol = false;
          for (const r of rows) {
            const cell = r[j];
            if (!cell) continue;
            const len = String(cell.v ?? "").length;
            if (len > maxLen) maxLen = len;
            if (cell.e) editableCol = true;
          }
          const chrome = editableCol ? INPUT_CHROME : LABEL_CHROME;
          return Math.max(MIN_W, Math.round(maxLen * CHAR_PX) + chrome);
        };

        let modeSel = `<select class="ggw-mode">`;
        for (const m of modes)
          modeSel += `<option ${m === mode ? "selected" : ""}>${esc(m)}</option>`;
        modeSel += `</select>`;

        let html = `<div class="ggw-topbar">`;
        if (title) html += `<span class="ggw-title">${esc(title)}</span>`;
        html += `<label>Mode:</label>${modeSel}</div>`;

        html += `<table class="ggw"><colgroup><col style="width:100px">`;
        cols.forEach((c, j) => { html += `<col style="width:${widthFor(j)}px">`; });
        html += `</colgroup><thead><tr><th></th>`;
        cols.forEach((c, j) => { html += `<th class="${colCls(j)}">${esc(c)}</th>`; });
        html += `</tr></thead><tbody>`;

        rows.forEach((r, i) => {
          const usedCls = used[i] ? " ggw-used" : "";
          const usedTitle = used[i] ? ' title="in use for cost calculation"' : "";
          html += `<tr class="ggw-row${usedCls}"${usedTitle}>`;
          html += `<td class="ggw-btns">` +
            `<button class="ggw-dup" data-row="${i}" title="duplicate" ${editing ? "" : "disabled"}>Dup</button>` +
            `<button class="ggw-delete" data-row="${i}" title="delete" ${editing ? "" : "disabled"}>Del</button>` +
            `</td>`;

          r.forEach((cell, j) => {
            const v = cell.v ?? "";
            if (cell.e && cell.k === "t") {
              const inv = cell.inv ? " ggw-invalid" : "";
              html += `<td class="${colCls(j)}"><input class="ggw-cell${inv}" data-row="${i}" ` +
                 `data-col="${esc(cols[j])}" data-orig="${esc(v)}" value="${esc(v)}"></td>`;
            } else {
              html += `<td class="${colCls(j)}">${esc(v)}</td>`;
            }
          });
          html += `</tr>`;
        });
        html += `</tbody></table>`;
        el.innerHTML = html;

        // ── event wiring ──────────────────────────────────────────────────
        el.querySelectorAll(".ggw-dup").forEach((b) =>
          b.addEventListener("click", () =>
            model.send({ type: "duplicate", row: +b.dataset.row })));
        el.querySelectorAll(".ggw-delete").forEach((b) =>
          b.addEventListener("click", () =>
            model.send({ type: "delete", row: +b.dataset.row })));
        const modeSelEl = el.querySelector(".ggw-mode");
        if (modeSelEl) modeSelEl.addEventListener("change", () =>
          model.send({ type: "mode", value: modeSelEl.value }));

        // editable cells; "change" fires on Enter/blur only, matching
        // ipywidgets continuous_update=False
        el.querySelectorAll("input.ggw-cell").forEach((inp) =>
          inp.addEventListener("change", () => {
            if (inp.value === inp.dataset.orig) return;   // ignore no-op edits
            model.send({
              type: "edit",
              row: +inp.dataset.row,
              col: inp.dataset.col,
              old: inp.dataset.orig,
              new: inp.value,
            });
          }));
      };

      const scheduleDraw = () => {
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; draw(); });
      };

      for (const t of ["columns", "rows", "row_used", "mode", "modes", "title"])
        model.on(`change:${t}`, scheduleDraw);

      model.on("msg:custom", (msg) => {
        if (!msg) return;
        if (msg.type === "cell_invalid") {
          const c = el.querySelector(
            `input.ggw-cell[data-row="${msg.row}"][data-col="${CSS.escape(msg.col)}"]`);
          if (c) c.classList.add("ggw-invalid");
        }
      });

      draw();
    }

    export default { render };
    """

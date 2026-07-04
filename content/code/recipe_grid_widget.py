"""
recipe_grid_widget.py — anywidget-based fast grid for DataFrameWidget (v2).

v2 adds Edit mode on top of the v1 View-mode grid:
  - editable cells (commit on Enter/blur, matching continuous_update=False)
  - ONE shared <datalist> for ingredient autocomplete (the full options list
    is sent once and only re-sent when the ingredient set changes — this is
    what the ipywidgets Combobox couldn't do)
  - per-cell invalid feedback (red border) driven from Python
  - "view below" button highlights while its child is open (▴ + accent)
  - slightly larger base font (14px, was 13px)
  - focus handoff to the blank add-ingredient row after commits

Cell model
    Each cell is a dict: {"v": display value, "e": editable bool, "k": kind}
    kinds: "t" text input (when editable), "i" ingredient input with
    datalist, "s" scale input (View-mode header quantity), "l" label.

Messages (browser -> kernel)
    {type:"edit",  row, col, old, new}
    {type:"lookup", row} / {type:"view_below", row}
    {type:"scale", value} / {type:"mode", value}

Messages (kernel -> browser)
    {type:"cell_invalid", row, col}   red-border a cell
    {type:"scale_invalid"}            red-border the scale input
"""

import anywidget
import traitlets


class RecipeGridWidget(anywidget.AnyWidget):
    # ── synced state ──────────────────────────────────────────────────────
    columns   = traitlets.List(traitlets.Unicode()).tag(sync=True)
    rows      = traitlets.List().tag(sync=True)   # list[list[celldict]]
    row_flags = traitlets.List().tag(sync=True)   # header/lookup/view_below/below_open/add_row
    title     = traitlets.Unicode('').tag(sync=True)
    mode      = traitlets.Unicode('View').tag(sync=True)
    modes     = traitlets.List(traitlets.Unicode(),
                               default_value=['Edit', 'View', 'Flatten']).tag(sync=True)
    ingredients = traitlets.List(traitlets.Unicode()).tag(sync=True)  # shared datalist
    col_widths  = traitlets.Dict().tag(sync=True)   # column name -> pixel width, from
                                                      # DataFrameWidget.update_column_width()
    focus_seq   = traitlets.Int(0).tag(sync=True)  # bump to focus the add-row input

    _css = """
    .rgw-root { font-family: var(--jp-ui-font-family, sans-serif); font-size: 14px; }
    .rgw-title { font-size: 0.95em; color: #888; font-weight: bold; padding: 1px 2px; }
    table.rgw { border-collapse: collapse; margin: 2px 0; table-layout: fixed; }
    table.rgw th { text-align: left; font-weight: normal; color: #555;
                   padding: 2px 8px 2px 4px; border-bottom: 1px solid #ccc;
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    table.rgw td { padding: 2px 8px 2px 4px; border-bottom: 1px solid #eee;
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    tr.rgw-header td { font-weight: bold; border-bottom: 2px solid #bbb; }
    tr.rgw-header td.rgw-item { font-style: italic; font-weight: normal; color: #555; }
    .rgw-btns { white-space: nowrap; overflow: visible; }
    .rgw button { font-size: 14px; padding: 1px 8px; margin-right: 3px;
                  border: 1px solid #bbb; border-radius: 3px; background: #f5f5f5;
                  cursor: pointer; }
    .rgw button:hover:not(:disabled) { background: #e2e2e2; }
    .rgw button:disabled { opacity: 0.35; cursor: default; }
    .rgw button.rgw-below-open { background: #f0ad4e; border-color: #d99b3c;
                                 color: #fff; }
    .rgw button.rgw-below-open:hover { background: #e39b35; }
    .rgw select { font-size: 14px; padding: 1px 3px; max-width: 100%; }
    .rgw input { font-size: 14px; padding: 1px 4px; border: 1px solid #ccc;
                 border-radius: 2px; width: 100%; min-width: 40px;
                 box-sizing: border-box; }
    .rgw input.rgw-invalid { border-color: red; outline-color: red; }
    tr.rgw-row:hover td { background: #fafafa; }
    """

    _esm = """
    const esc = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

    function render({ model, el }) {
      el.classList.add("rgw-root");
      const dlid = "rgw-dl-" + Math.random().toString(36).slice(2);
      let scheduled = false;
      let focusPending = false;

      const draw = () => {
        const cols   = model.get("columns")    || [];
        const rows   = model.get("rows")       || [];
        const flags  = model.get("row_flags")  || [];
        const mode   = model.get("mode");
        const modes  = model.get("modes")      || [];
        const title  = model.get("title")      || "";
        const opts   = model.get("ingredients")|| [];
        const widths = model.get("col_widths") || {};
        const iidx   = cols.indexOf("item");

        // Fallback width mirrors update_column_width's own default
        // (5 + 8*len) for any column it hasn't sized yet.
        const widthFor = (c) => Math.max(widths[c] || (5 + 8 * String(c).length), 40);

        let html = title ? `<div class="rgw-title">${esc(title)}</div>` : "";
        html += `<datalist id="${dlid}">` +
          opts.map((o) => `<option value="${esc(o)}">`).join("") +
          `</datalist>`;
        html += `<table class="rgw"><colgroup><col style="width:64px">`;
        for (const c of cols) html += `<col style="width:${widthFor(c)}px">`;
        html += `</colgroup><thead><tr><th></th>`;
        for (const c of cols) html += `<th>${esc(c)}</th>`;
        html += `</tr></thead><tbody>`;

        rows.forEach((r, i) => {
          const f = flags[i] || {};
          html += `<tr class="${f.header ? "rgw-header" : "rgw-row"}">`;

          // control column
          if (f.header) {
            let sel = `<select class="rgw-mode">`;
            for (const m of modes)
              sel += `<option ${m === mode ? "selected" : ""}>${esc(m)}</option>`;
            sel += `</select>`;
            html += `<td>${sel}</td>`;
          } else {
            const openCls = f.below_open ? " rgw-below-open" : "";
            const arrow   = f.below_open ? "&#9652;" : "&#9662;";
            const belowTip = f.below_open ? "hide below" : "view below";
            html += `<td class="rgw-btns">` +
              `<button class="rgw-lookup" data-row="${i}" ` +
              `${f.lookup ? "" : "disabled"}>lookup</button>` +
              `<button class="rgw-below${openCls}" data-row="${i}" ` +
              `title="${belowTip}" ${f.view_below ? "" : "disabled"}>` +
              `${arrow}</button></td>`;
          }

          // data cells
          r.forEach((cell, j) => {
            const v = cell.v ?? "";
            const cls = (j === iidx) ? ` class="rgw-item"` : "";
            if (cell.k === "s") {
              html += `<td><input class="rgw-scale" value="${esc(v)}"></td>`;
            } else if (cell.e && (cell.k === "t" || cell.k === "i")) {
              const list = cell.k === "i" ? ` list="${dlid}"` : "";
              const addrow = (f.add_row && cell.k === "i") ? ` data-addrow="1"` : "";
              const inv = cell.inv ? " rgw-invalid" : "";
              html += `<td><input class="rgw-cell${inv}" data-row="${i}" ` +
                `data-col="${esc(cols[j])}" data-orig="${esc(v)}" ` +
                `value="${esc(v)}"${list}${addrow}></td>`;
            } else {
              html += `<td${cls}>${esc(v)}</td>`;
            }
          });
          html += `</tr>`;
        });
        html += `</tbody></table>`;
        el.innerHTML = html;

        // ── event wiring ──────────────────────────────────────────────────
        el.querySelectorAll(".rgw-lookup").forEach((b) =>
          b.addEventListener("click", () =>
            model.send({ type: "lookup", row: +b.dataset.row })));
        el.querySelectorAll(".rgw-below").forEach((b) =>
          b.addEventListener("click", () =>
            model.send({ type: "view_below", row: +b.dataset.row })));
        const sel = el.querySelector(".rgw-mode");
        if (sel) sel.addEventListener("change", () =>
          model.send({ type: "mode", value: sel.value }));
        const sc = el.querySelector(".rgw-scale");
        if (sc) sc.addEventListener("change", () =>
          model.send({ type: "scale", value: sc.value }));

        // editable cells; "change" fires on Enter/blur only, matching
        // ipywidgets continuous_update=False
        el.querySelectorAll("input.rgw-cell").forEach((inp) =>
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

        if (focusPending) {
          focusPending = false;
          const add = el.querySelector('input[data-addrow="1"]');
          if (add) add.focus();
        }
      };

      const scheduleDraw = () => {
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; draw(); });
      };

      for (const t of ["columns", "rows", "row_flags", "mode",
                       "modes", "title", "ingredients", "col_widths"])
        model.on(`change:${t}`, scheduleDraw);

      model.on("change:focus_seq", () => { focusPending = true; scheduleDraw(); });

      model.on("msg:custom", (msg) => {
        if (!msg) return;
        if (msg.type === "scale_invalid") {
          const s = el.querySelector(".rgw-scale");
          if (s) s.classList.add("rgw-invalid");
        } else if (msg.type === "cell_invalid") {
          const c = el.querySelector(
            `input.rgw-cell[data-row="${msg.row}"][data-col="${CSS.escape(msg.col)}"]`);
          if (c) c.classList.add("rgw-invalid");
        }
      });

      draw();
    }

    export default { render };
    """

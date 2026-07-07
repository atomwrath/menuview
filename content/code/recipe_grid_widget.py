"""
recipe_grid_widget.py — anywidget-based fast grid for DataFrameWidget.

Renders recipe View, Edit, and Flatten modes as a single anywidget model
instead of one ipywidgets widget per cell. See DataFrameWidget's
_update_display_fast / _on_fast_grid_msg for the Python-side integration.

Cell model
    Each cell is a dict: {"v": display value, "e": editable bool, "k": kind}
    kinds: "t" text input (when editable), "i" ingredient input with shared
    datalist, "s" scale input (View/Flatten header quantity), "l" label.
    The item column is special-cased per row: a label on the header row,
    a selection "handle" cell on every other row (see Selection below).

Messages (browser -> kernel)
    {type:"edit",  row, col, old, new}
    {type:"lookup", row} / {type:"view_below", row}
    {type:"scale", value} / {type:"mode", value}
    {type:"selection_action", action, ...}
        action: "copy" | "cut" | "paste" | "view_below"

Messages (kernel -> browser)
    {type:"cell_invalid", row, col}   red-border a cell
    {type:"scale_invalid"}            red-border the scale input

Selection
    Tapping the item-column "handle" cell of any non-header row toggles that
    row in/out of the selection; dragging across handle cells adds that
    whole range on top of whatever's already selected (selected_rows is an
    arbitrary, possibly non-contiguous, list of row indices — not a [lo,hi]
    range). Tapping blank space clears the selection entirely. Uses Pointer
    Events so it works with touch (iPad) as well as mouse — and tracks the
    row under the finger via elementFromPoint, since touchmove doesn't
    retarget the way mousemove does. The lowest-indexed selected row's item
    cell grows a small menu button (⋮) offering Copy / Cut / Paste / View
    selected below. Creating a new recipe from a selection now happens from
    buttons on the "view selected below" display rather than from this menu.

Font size
    Everything scales off one CSS variable, --rgw-font-size (default 16px),
    set on .rgw-root; button/select/input font-sizes are expressed in `em`
    so they stay proportional. Override by setting the variable on a parent
    element, or edit the default in _css below.
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

    selected_rows = traitlets.List(traitlets.Int()).tag(sync=True)   # arbitrary set of row indices, not necessarily contiguous
    has_clipboard = traitlets.Bool(False).tag(sync=True)

    _css = """
    .rgw-root { font-family: var(--jp-ui-font-family, sans-serif);
                font-size: var(--rgw-font-size, 16px);   /* <- change this one value */
                color: var(--jp-ui-font-color1, #333);
                position: relative; }   /* containing block for the popup menu */
    .rgw-title { font-size: 0.85em; color: var(--jp-ui-font-color2, #888); font-weight: bold;
                 padding: 1px 2px; }
    table.rgw { border-collapse: collapse; margin: 2px 0; table-layout: fixed; }
    table.rgw th { text-align: left; font-weight: normal; color: var(--jp-ui-font-color2, #555);
                   padding: 2px 8px 2px 4px; border-bottom: 1px solid var(--jp-border-color1, #ccc);
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    table.rgw td { padding: 2px 8px 2px 4px; border-bottom: 1px solid var(--jp-border-color2, #eee);
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                   color: var(--jp-ui-font-color1, inherit); }
    tr.rgw-header td { font-weight: bold; border-bottom: 2px solid var(--jp-border-color0, #bbb); }
    tr.rgw-header td.rgw-item { font-style: italic; font-weight: normal;
                                color: var(--jp-ui-font-color2, #555); }
    tr.rgw-selected td { background: var(--jp-brand-color3, #cfe4ff); }
    .rgw-btns { white-space: nowrap; overflow: visible; }
    .rgw button { font-size: 0.85em; padding: 1px 8px; margin-right: 3px;
                  border: 1px solid var(--jp-border-color2, #bbb);
                  border-radius: 3px;
                  background: var(--jp-layout-color2, #f5f5f5);
                  color: var(--jp-ui-font-color1, #333);
                  cursor: pointer; }
    .rgw button:hover:not(:disabled) { background: var(--jp-layout-color3, #e2e2e2); }
    .rgw button:disabled { opacity: 0.45; cursor: default; }
    .rgw button.rgw-below-open { background: var(--jp-warn-color1, #f0ad4e);
                                 border-color: var(--jp-warn-color0, #d99b3c);
                                 color: #fff; }
    .rgw button.rgw-below-open:hover { background: var(--jp-warn-color0, #e39b35); }
    .rgw select { font-size: 0.85em; padding: 1px 3px; max-width: 100%;
                  background: var(--jp-layout-color1, #fff);
                  color: var(--jp-ui-font-color1, #333);
                  border: 1px solid var(--jp-border-color2, #bbb); }
    .rgw input { font-size: 0.9em; padding: 1px 4px; border: 1px solid var(--jp-border-color2, #ccc);
                 border-radius: 2px; width: 100%; min-width: 40px;
                 box-sizing: border-box; }
    .rgw input.rgw-invalid { border-color: var(--jp-error-color1, red);
                             outline-color: var(--jp-error-color1, red); }
    tr.rgw-row:hover td { background: var(--jp-layout-color2, #fafafa); }
    tr.rgw-selected:hover td { background: var(--jp-brand-color3, #cfe4ff); }

    /* selection handle (item column, non-header rows) */
    td.rgw-handle { cursor: grab; text-align: center; position: relative;
                    touch-action: none; }
    td.rgw-handle::before { content: "\\22EE"; opacity: 0.25; }
    .rgw-menu-btn { font-size: 0.8em; padding: 0 5px; margin-left: 4px;
                    border-radius: 3px;
                    border: 1px solid var(--jp-border-color2, #bbb);
                    background: var(--jp-layout-color2, #f5f5f5);
                    color: var(--jp-ui-font-color1, #333); cursor: pointer; }
    .rgw-menu { position: absolute; z-index: 20; display: flex; flex-direction: column;
                background: var(--jp-layout-color1, #fff);
                border: 1px solid var(--jp-border-color1, #999);
                border-radius: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.35); min-width: 160px; }
    .rgw-menu button { text-align: left; padding: 6px 10px; border: none; background: none;
                       color: var(--jp-ui-font-color1, #333); font-size: 0.85em; cursor: pointer;
                       width: 100%; }
    .rgw-menu button:hover:not(:disabled) { background: var(--jp-layout-color2, #eee); }
    .rgw-menu button:disabled { opacity: 0.4; cursor: default; }
    .rgw-menu-form { display: flex; flex-direction: column; padding: 6px 8px; gap: 4px; }
    .rgw-menu-form label { font-size: 0.8em; color: var(--jp-ui-font-color2, #888);
                           display: flex; flex-direction: column; gap: 2px; }
    .rgw-menu-form input { font-size: 0.85em; }
    .rgw-menu-form-btns { display: flex; gap: 4px; margin-top: 4px; }
    .rgw-menu-form-btns button { flex: 1; }
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
      let dragAnchor = null;
      let baseSelection = new Set();   // selection state before the current gesture
      let dragMoved = false;

      // Shared by both the per-draw handle listeners and the once-bound
      // root-level listeners below, so it must live out here rather than
      // inside draw().
      const previewRange = (row) => {
        const merged = new Set(baseSelection);
        const lo = Math.min(dragAnchor, row), hi = Math.max(dragAnchor, row);
        for (let k = lo; k <= hi; k++) merged.add(k);
        model.set("selected_rows", Array.from(merged).sort((a, b) => a - b));
        model.save_changes();
      };

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

        const sel    = model.get("selected_rows") || [];
        const selSet = new Set(sel);
        const selMin = sel.length ? Math.min(...sel) : null;

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
          const inSel = !f.header && selSet.has(i);
          const isFirstSel = inSel && i === selMin;

          html += `<tr class="${f.header ? "rgw-header" : "rgw-row"}${inSel ? " rgw-selected" : ""}">`;

          // control column
          if (f.header) {
            let modeSel = `<select class="rgw-mode">`;
            for (const m of modes)
              modeSel += `<option ${m === mode ? "selected" : ""}>${esc(m)}</option>`;
            modeSel += `</select>`;
            html += `<td>${modeSel}</td>`;
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

            if (j === iidx && !f.header) {
              // selection handle, replaces the (always-blank) item label
              html += `<td class="rgw-item rgw-handle" data-row="${i}">` +
                (isFirstSel ? `<button class="rgw-menu-btn" data-row="${i}">&#8942;</button>` : "") +
                `</td>`;
              return;
            }
            if (j === iidx) {   // header row's item label
              html += `<td class="rgw-item">${esc(v)}</td>`;
              return;
            }

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
              html += `<td>${esc(v)}</td>`;
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
        const modeSelEl = el.querySelector(".rgw-mode");
        if (modeSelEl) modeSelEl.addEventListener("change", () =>
          model.send({ type: "mode", value: modeSelEl.value }));
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

        // ── selection: tap toggles one row, drag adds a range on top of
        // whatever's already selected ────────────────────────────────────
        el.querySelectorAll(".rgw-handle").forEach((td) => {
          td.addEventListener("pointerdown", (e) => {
            dragAnchor = +td.dataset.row;
            dragMoved = false;
            baseSelection = new Set(model.get("selected_rows") || []);
            el.setPointerCapture(e.pointerId);
            closeMenu();
            previewRange(dragAnchor);
          });
        });
        el.querySelectorAll(".rgw-menu-btn").forEach((btn) => {
          // stop the handle's own pointerdown (which would restart a drag
          // and collapse the selection to one row right before we open it)
          btn.addEventListener("pointerdown", (e) => e.stopPropagation());
          btn.addEventListener("click", (e) => { e.stopPropagation(); openMenu(btn); });
        });

        if (focusPending) {
          focusPending = false;
          const add = el.querySelector('input[data-addrow="1"]');
          if (add) add.focus();
        }
      };

      // root-level drag listeners: bind once, survive re-draws
      if (!el._rgwPointerBound) {
        el._rgwPointerBound = true;
        el.addEventListener("pointermove", (e) => {
          if (dragAnchor === null) return;
          const cell = document.elementFromPoint(e.clientX, e.clientY)?.closest(".rgw-handle");
          if (!cell) return;
          const row = +cell.dataset.row;
          if (row !== dragAnchor) dragMoved = true;
          previewRange(row);
        });
        el.addEventListener("pointerup", () => {
          if (dragAnchor === null) return;
          // A plain tap (no movement) on a row that was already selected
          // means "deselect it", not "re-add it".
          if (!dragMoved && baseSelection.has(dragAnchor)) {
            const merged = new Set(baseSelection);
            merged.delete(dragAnchor);
            model.set("selected_rows", Array.from(merged).sort((a, b) => a - b));
            model.save_changes();
          }
          dragAnchor = null;
        });

        // Clicking anywhere that isn't a handle/menu clears the selection.
        el.addEventListener("pointerdown", (e) => {
          if (e.target.closest(".rgw-handle") || e.target.closest(".rgw-menu-btn")
              || e.target.closest(".rgw-menu")) return;
          const cur = model.get("selected_rows") || [];
          if (cur.length) {
            model.set("selected_rows", []);
            model.save_changes();
          }
        });
      }

      function closeMenu() {
        el.querySelector(".rgw-menu")?.remove();
        document.removeEventListener("pointerdown", onOutsideClick, true);
      }
      function onOutsideClick(e) {
        if (!e.target.closest(".rgw-menu") && !e.target.closest(".rgw-menu-btn")) closeMenu();
      }
      function openMenu(btn) {
        closeMenu();
        const r = btn.getBoundingClientRect(), rootR = el.getBoundingClientRect();
        const menu = document.createElement("div");
        menu.className = "rgw-menu";
        menu.style.left = (r.left - rootR.left) + "px";
        menu.style.top  = (r.bottom - rootR.top + 3) + "px";
        const hasClip = model.get("has_clipboard");

        const renderActions = () => {
          const mode = model.get("mode");
          if (mode === "Edit") {
            menu.innerHTML = `
              <button data-action="copy">Copy</button>
              <button data-action="cut">Cut</button>
              <button data-action="paste" ${hasClip ? "" : "disabled"}>Paste</button>
              <button data-action="view_below">View selected below</button>
            `;
          } else {
            // View / Flatten are read-only: no cut/paste
            menu.innerHTML = `
              <button data-action="copy">Copy</button>
              <button data-action="view_below">View selected below</button>
            `;
          }
          menu.querySelectorAll("button[data-action]").forEach((b) =>
            b.addEventListener("click", (ev) => {
              ev.stopPropagation();
              model.send({ type: "selection_action", action: b.dataset.action });
              closeMenu();
            }));
        };

        renderActions();
        el.appendChild(menu);
        document.addEventListener("pointerdown", onOutsideClick, true);
      }

      // Coalesce multi-trait updates into one repaint per message batch.
      const scheduleDraw = () => {
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; draw(); });
      };

      for (const t of ["columns", "rows", "row_flags", "mode",
                       "modes", "title", "ingredients", "col_widths",
                       "selected_rows", "has_clipboard"])
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
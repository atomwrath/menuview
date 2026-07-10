"""
toolbar_widget.py — anywidget-based top toolbar for DataFrameExplorer.

Single-row toolbar replacing the old ipywidgets VBox of database/create/
columns/cost controls. Layout follows "Option 2" (compact toolbar): a joined
database segment (filename + reload/write icon buttons), the cost method +
multiplier chips inline, a spacer, then Columns and + New popovers on the
right.

Styling reads the same --mv-* CSS custom properties menuview_theme.py sets
on .mv-app (with hardcoded fallbacks so this still renders sensibly if ever
shown outside that container) — dark mode is therefore inherited for free
from theme_widget()'s body[data-jp-theme-light="false"] override; no
separate dark handling lives in this file.

Messages (browser -> kernel), via model.send:
    {type:"reload_database"}
    {type:"write_database"}
    {type:"confirm_write"}                 -- "file doesn't exist, save as?" confirmed
    {type:"refresh_database_files"}        -- caret clicked open; rescan cwd for .xlsx files
    {type:"create_recipe", value}
    {type:"create_ingredient", value}

Messages (kernel -> browser), via widget.send:
    {type:"db_error",   message}            -- red banner, no confirm button
    {type:"db_confirm", message}            -- amber banner, Confirm + Cancel
    {type:"create_error", target, message}  -- target: "recipe" | "ingredient"
                                                small red text under that field

Synced traits (two-way, except file_exists, database_files, and
equ_quant_valid, which are kernel-owned and only reflected in the browser):
    database_filename, file_exists, database_files, cost_method, cost_methods,
    cost_multipliers, show_note, show_conversion, show_menu_price,
    equ_quant_unit, equ_quant_valid

database_files is the list of .xlsx filenames found in the working directory
(populated by DataFrameExplorer via utils.get_xlsx_files()); it drives the
suggestions dropdown attached to the database filename field. The field
itself stays a free-text input, so typing a name not in the list still
works for "save as" / new-blank-database.
"""

import anywidget
import traitlets


class ToolbarWidget(anywidget.AnyWidget):
    database_filename = traitlets.Unicode('').tag(sync=True)
    file_exists        = traitlets.Bool(True).tag(sync=True)   # kernel sets this; JS only reads it
    database_files      = traitlets.List(traitlets.Unicode()).tag(sync=True)  # kernel sets this; JS only reads it

    cost_method    = traitlets.Unicode('recent').tag(sync=True)
    cost_methods   = traitlets.List(traitlets.Unicode(),
                                    default_value=['recent', 'maximum', 'minimum', 'all']).tag(sync=True)
    cost_multipliers = traitlets.List(traitlets.Float()).tag(sync=True)

    show_note        = traitlets.Bool(False).tag(sync=True)
    show_conversion   = traitlets.Bool(False).tag(sync=True)
    show_menu_price   = traitlets.Bool(False).tag(sync=True)
    equ_quant_unit    = traitlets.Unicode('').tag(sync=True)
    equ_quant_valid   = traitlets.Bool(True).tag(sync=True)   # kernel sets this; JS only reads it

    _css = """
    .tbw-root {
        font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
        font-size: 13px;
        color: var(--mv-ink, #1c2733);
        position: relative;
    }

    .tbw-bar {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        background: var(--mv-surface, #fff);
        border: 1px solid var(--mv-border, #dde3ea);
        border-radius: 8px;
        padding: 8px 10px;
    }

    /* database segment */
    .tbw-dbseg {
        display: flex; align-items: center;
        border: 1px solid var(--mv-border, #dde3ea);
        border-radius: 6px; overflow: hidden;
    }
    .tbw-dbseg input {
        border: none; padding: 6px 10px; font: inherit; width: 190px;
        background: var(--mv-surface, #fff); color: var(--mv-ink, #1c2733);
    }
    .tbw-dbseg input:focus { outline: none; background: var(--mv-accent-soft, #eaf1fe); }
    .tbw-dbseg input.tbw-invalid { color: var(--mv-danger, #c0392b) !important; }
    .tbw-dbseg button {
        border: none; border-left: 1px solid var(--mv-border, #dde3ea);
        background: var(--mv-page, #f7f9fb); padding: 0 10px; height: 30px;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; color: var(--mv-muted, #66727f);
    }
    .tbw-dbseg button svg { width: 15px; height: 15px; display: block; }
    .tbw-dbseg button:hover { background: var(--mv-accent-soft, #eaf1fe); color: var(--mv-accent, #2563eb); }
    .tbw-dbseg button.tbw-write { color: var(--mv-danger, #c0392b); }
    .tbw-dbseg button.tbw-write:hover { background: var(--mv-danger-soft, #fdecea); color: var(--mv-danger, #c0392b); }

    .tbw-sep { width: 1px; height: 24px; background: var(--mv-border, #dde3ea); }

    /* cost method + multipliers */
    .tbw-costmethod {
        border: 1px solid var(--mv-border, #dde3ea); border-radius: 6px;
        background: var(--mv-surface, #fff); color: var(--mv-ink, #1c2733);
        font: inherit; padding: 6px 8px;
    }
    .tbw-mult { display: flex; align-items: center; gap: 6px; }
    .tbw-mult-chips { display: flex; gap: 4px; flex-wrap: wrap; }
    .tbw-chip {
        display: inline-flex; align-items: center; gap: 4px;
        background: var(--mv-accent-soft, #eaf1fe); color: var(--mv-accent, #2563eb);
        border: 1px solid var(--mv-accent-bord, #bcd3fb);
        border-radius: 999px; padding: 2px 4px 2px 10px; font-size: 12px;
    }
    .tbw-chip button {
        border: none; background: none; color: inherit; cursor: pointer;
        font-size: 13px; line-height: 1; padding: 2px 4px;
    }
    .tbw-mult-add {
        width: 64px; border: 1px solid var(--mv-border, #dde3ea); border-radius: 6px;
        padding: 5px 8px; font: inherit; background: var(--mv-surface, #fff);
        color: var(--mv-ink, #1c2733);
    }
    .tbw-mult-add.tbw-invalid { border-color: var(--mv-danger, #c0392b) !important; }

    .tbw-spacer { flex: 1; }

    /* popover buttons */
    .tbw-pop { position: relative; }
    .tbw-btn {
        border: 1px solid var(--mv-border, #dde3ea); background: var(--mv-page, #f7f9fb);
        border-radius: 6px; padding: 6px 12px; font: inherit; cursor: pointer;
        white-space: nowrap; color: var(--mv-ink, #1c2733);
    }
    .tbw-btn:hover, .tbw-pop.open .tbw-btn {
        background: var(--mv-accent-soft, #eaf1fe); color: var(--mv-accent, #2563eb);
        border-color: var(--mv-accent-bord, #bcd3fb);
    }
    .tbw-btn.primary {
        background: var(--mv-accent, #2563eb); border-color: var(--mv-accent, #2563eb);
        color: #fff; font-weight: 600;
    }
    .tbw-pop-body {
        display: none; position: absolute; top: 100%; right: 0; z-index: 10; min-width: 250px;
        background: var(--mv-surface, #fff); border: 1px solid var(--mv-border, #dde3ea);
        border-radius: 8px; box-shadow: 0 6px 20px rgba(28,39,51,.18);
        padding: 10px; margin-top: 4px;
    }
    .tbw-pop.open .tbw-pop-body { display: block; }
    .tbw-pop-body label {
        display: flex; gap: 8px; align-items: center; padding: 5px 2px; cursor: pointer;
    }
    .tbw-pop-body input[type=checkbox] { accent-color: var(--mv-accent, #2563eb); }
    .tbw-pop-label {
        font-size: 10.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
        color: var(--mv-muted, #66727f); margin: 2px 0 4px;
    }
    .tbw-pop-row { display: flex; gap: 6px; align-items: center; margin-top: 4px; }
    .tbw-pop-row input[type=text] {
        flex: 1; border: 1px solid var(--mv-border, #dde3ea); border-radius: 6px;
        padding: 5px 8px; font: inherit; min-width: 0;
        background: var(--mv-surface, #fff); color: var(--mv-ink, #1c2733);
    }
    .tbw-pop-go {
        border: 1px solid var(--mv-accent-bord, #bcd3fb); background: var(--mv-accent-soft, #eaf1fe);
        color: var(--mv-accent, #2563eb); font-weight: 600; border-radius: 6px;
        padding: 5px 10px; font: inherit; cursor: pointer;
    }
    .tbw-pop-sep { border-top: 1px solid var(--mv-border-soft, #ebeff3); margin: 8px 0; }
    .tbw-pop-row input.tbw-invalid { border-color: var(--mv-danger, #c0392b) !important; }
    .tbw-err {
        color: var(--mv-muted, #66727f); font-size: 11.5px; min-height: 14px; margin-top: 2px;
    }

    /* database filename suggestions dropdown */
    .tbw-pop-body.tbw-dblist {
        min-width: 240px; max-width: 340px; max-height: 220px; overflow-y: auto; padding: 4px;
    }
    .tbw-dbitem {
        padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .tbw-dbitem:hover { background: var(--mv-accent-soft, #eaf1fe); color: var(--mv-accent, #2563eb); }
    .tbw-dbempty {
        padding: 6px 8px; color: var(--mv-muted, #66727f); font-size: 12px; white-space: normal;
    }

    /* save-as / error banner */
    .tbw-banner {
        display: none; align-items: center; gap: 10px;
        border: 1px solid var(--mv-warn-bord, #f0d99a);
        background: var(--mv-warn-soft, #fff7e0);
        color: var(--mv-warn-ink, #8a6415);
        border-radius: 8px; padding: 8px 12px; margin-top: 8px; font-size: 12.5px;
    }
    .tbw-banner.tbw-banner-error {
        border-color: var(--mv-danger-bord, #f0b8b0);
        background: var(--mv-danger-soft, #fdecea);
        color: var(--mv-danger, #c0392b);
    }
    .tbw-banner-msg { flex: 1; }
    .tbw-banner button {
        border: 1px solid currentColor; background: transparent; color: inherit;
        border-radius: 6px; padding: 4px 10px; font: inherit; cursor: pointer;
    }
    .tbw-banner-confirm { font-weight: 600; }
    """

    _esm = """
    const esc = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

    const ICON_RELOAD = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12a9 9 0 1 1-3-6.7"/>
        <polyline points="21 3 21 9 15 9"/>
      </svg>`;
    const ICON_WRITE = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
        <polyline points="17 21 17 13 7 13 7 21"/>
        <polyline points="7 3 7 8 15 8"/>
      </svg>`;

    function render({ model, el }) {
      el.classList.add("tbw-root");
      el.innerHTML = `
        <div class="tbw-bar">
          <div class="tbw-pop tbw-dbpop" data-pop="db">
            <div class="tbw-dbseg">
              <input type="text" class="tbw-dbfile" title="database file" autocomplete="off" spellcheck="false">
              <button type="button" class="tbw-btn tbw-dbcaret" title="choose an existing database file">&#9662;</button>
              <button class="tbw-reload" title="reload database">${ICON_RELOAD}</button>
              <button class="tbw-write" title="write database">${ICON_WRITE}</button>
            </div>
            <div class="tbw-pop-body tbw-dblist"></div>
          </div>

          <div class="tbw-sep"></div>

          <select class="tbw-costmethod" title="cost method"></select>
          <div class="tbw-mult">
            <span class="tbw-mult-chips"></span>
            <input type="text" class="tbw-mult-add" placeholder="+ ×" title="add multiplier, press Enter">
          </div>

          <span class="tbw-spacer"></span>

          <div class="tbw-pop" data-pop="cols">
            <button class="tbw-btn">Columns &#9662;</button>
            <div class="tbw-pop-body">
              <label><input type="checkbox" class="tbw-note"> note</label>
              <label><input type="checkbox" class="tbw-conversion"> conversion</label>
              <label><input type="checkbox" class="tbw-menuprice"> menu price</label>
              <div class="tbw-pop-sep"></div>
              <div class="tbw-pop-label">Equ quant unit</div>
              <div class="tbw-pop-row"><input type="text" class="tbw-equ" placeholder="e.g. 1/4 tsp, 0"></div>
            </div>
          </div>

          <div class="tbw-pop" data-pop="new">
            <button class="tbw-btn primary">&#65291; New &#9662;</button>
            <div class="tbw-pop-body">
              <div class="tbw-pop-label">Recipe</div>
              <div class="tbw-pop-row">
                <input type="text" class="tbw-new-recipe" placeholder="recipe name">
                <button class="tbw-pop-go tbw-go-recipe">create</button>
              </div>
              <div class="tbw-err tbw-err-recipe"></div>
              <div class="tbw-pop-sep"></div>
              <div class="tbw-pop-label">Ingredient</div>
              <div class="tbw-pop-row">
                <input type="text" class="tbw-new-ingredient" placeholder="nickname, size, price">
                <button class="tbw-pop-go tbw-go-ingredient">create</button>
              </div>
              <div class="tbw-err tbw-err-ingredient"></div>
            </div>
          </div>
        </div>

        <div class="tbw-banner">
          <span class="tbw-banner-msg"></span>
          <button class="tbw-banner-confirm">Confirm</button>
          <button class="tbw-banner-cancel">Cancel</button>
        </div>
      `;

      const $ = (sel) => el.querySelector(sel);
      const dbfile        = $(".tbw-dbfile");
      const dbPop          = $(".tbw-dbpop");
      const dbCaret        = $(".tbw-dbcaret");
      const dbList         = $(".tbw-dblist");
      const costSel        = $(".tbw-costmethod");
      const multChips      = $(".tbw-mult-chips");
      const multAdd        = $(".tbw-mult-add");
      const noteCk         = $(".tbw-note");
      const convCk         = $(".tbw-conversion");
      const priceCk        = $(".tbw-menuprice");
      const equInput       = $(".tbw-equ");
      const newRecipe      = $(".tbw-new-recipe");
      const newIngredient  = $(".tbw-new-ingredient");
      const errRecipe      = $(".tbw-err-recipe");
      const errIngredient  = $(".tbw-err-ingredient");
      const banner         = $(".tbw-banner");
      const bannerMsg      = $(".tbw-banner-msg");
      const bannerConfirm  = $(".tbw-banner-confirm");
      const bannerCancel   = $(".tbw-banner-cancel");

      // ── database segment ──────────────────────────────────────────────
      const syncDbFile = () => {
        if (document.activeElement !== dbfile) dbfile.value = model.get("database_filename") || "";
      };
      const syncFileExists = () => {
        dbfile.classList.toggle("tbw-invalid", model.get("file_exists") === false);
      };
      syncDbFile(); syncFileExists();
      model.on("change:database_filename", syncDbFile);
      model.on("change:file_exists", syncFileExists);
      dbfile.addEventListener("input", () => {
        model.set("database_filename", dbfile.value);
        model.save_changes();
      });
      $(".tbw-reload").addEventListener("click", () => model.send({ type: "reload_database" }));
      $(".tbw-write").addEventListener("click", () => model.send({ type: "write_database" }));

      // ── cost method ──────────────────────────────────────────────────
      const renderMethods = () => {
        const methods = model.get("cost_methods") || [];
        const cur = model.get("cost_method");
        costSel.innerHTML = methods
          .map((m) => `<option value="${esc(m)}" ${m === cur ? "selected" : ""}>cost: ${esc(m)}</option>`)
          .join("");
      };
      renderMethods();
      model.on("change:cost_methods", renderMethods);
      model.on("change:cost_method", () => { if (costSel.value !== model.get("cost_method")) renderMethods(); });
      costSel.addEventListener("change", () => {
        model.set("cost_method", costSel.value);
        model.save_changes();
      });

      // ── multipliers ──────────────────────────────────────────────────
      const renderMults = () => {
        const mults = model.get("cost_multipliers") || [];
        multChips.innerHTML = mults
          .map((m, i) => `<span class="tbw-chip">${m.toFixed(2)} &times;<button data-i="${i}">&times;</button></span>`)
          .join("");
        multChips.querySelectorAll("button").forEach((b) =>
          b.addEventListener("click", () => {
            const i = +b.dataset.i;
            const next = (model.get("cost_multipliers") || []).slice();
            next.splice(i, 1);
            model.set("cost_multipliers", next);
            model.save_changes();
          }));
      };
      renderMults();
      model.on("change:cost_multipliers", renderMults);
      const addMultiplierFromInput = () => {
        const raw = multAdd.value.trim();
        if (!raw) { multAdd.classList.remove("tbw-invalid"); return; }
        const v = parseFloat(raw);
        if (isNaN(v) || v <= 0) { multAdd.classList.add("tbw-invalid"); return; }
        multAdd.classList.remove("tbw-invalid");
        const next = (model.get("cost_multipliers") || []).concat([v]);
        model.set("cost_multipliers", next);
        model.save_changes();
        multAdd.value = "";
      };
      multAdd.addEventListener("keydown", (e) => { if (e.key === "Enter") addMultiplierFromInput(); });
      multAdd.addEventListener("change", addMultiplierFromInput);   // fires on blur / clicking off

      // ── columns ──────────────────────────────────────────────────────
      const syncCk = (ck, name) => { ck.checked = !!model.get(name); };
      syncCk(noteCk, "show_note"); syncCk(convCk, "show_conversion"); syncCk(priceCk, "show_menu_price");
      model.on("change:show_note", () => syncCk(noteCk, "show_note"));
      model.on("change:show_conversion", () => syncCk(convCk, "show_conversion"));
      model.on("change:show_menu_price", () => syncCk(priceCk, "show_menu_price"));
      noteCk.addEventListener("change", () => { model.set("show_note", noteCk.checked); model.save_changes(); });
      convCk.addEventListener("change", () => { model.set("show_conversion", convCk.checked); model.save_changes(); });
      priceCk.addEventListener("change", () => { model.set("show_menu_price", priceCk.checked); model.save_changes(); });

      const syncEqu = () => {
        if (document.activeElement !== equInput) equInput.value = model.get("equ_quant_unit") || "";
      };
      const syncEquValid = () => {
        equInput.classList.toggle("tbw-invalid", model.get("equ_quant_valid") === false);
      };
      syncEqu(); syncEquValid();
      model.on("change:equ_quant_unit", syncEqu);
      model.on("change:equ_quant_valid", syncEquValid);
      equInput.addEventListener("change", () => {
        model.set("equ_quant_unit", equInput.value);
        model.save_changes();
      });

      // ── create recipe / ingredient ──────────────────────────────────
      const submitRecipe = () => {
        const v = newRecipe.value.trim();
        if (!v) return;
        errRecipe.textContent = "";
        model.send({ type: "create_recipe", value: v });
        newRecipe.value = "";
      };
      const submitIngredient = () => {
        const v = newIngredient.value.trim();
        if (!v) return;
        errIngredient.textContent = "";
        model.send({ type: "create_ingredient", value: v });
        newIngredient.value = "";
      };
      $(".tbw-go-recipe").addEventListener("click", submitRecipe);
      newRecipe.addEventListener("keydown", (e) => { if (e.key === "Enter") submitRecipe(); });
      $(".tbw-go-ingredient").addEventListener("click", submitIngredient);
      newIngredient.addEventListener("keydown", (e) => { if (e.key === "Enter") submitIngredient(); });

      // ── popovers ─────────────────────────────────────────────────────
      const closePop = (pop) => {
        pop.classList.remove("open");
        if (pop.dataset.pop === "new") {
          errRecipe.textContent = "";
          errIngredient.textContent = "";
        }
      };
      const positionPop = (pop) => {
        const body = pop.querySelector(".tbw-pop-body");
        // Measure against the toolbar's own box, not window.innerWidth --
        // inside Jupyter the widget usually sits in a narrower notebook/
        // output container, so a popover can clip against that edge while
        // still reading as on-screen relative to the full browser viewport.
        const bounds = el.getBoundingClientRect();

        body.style.left = "";
        body.style.right = "0";
        let r = body.getBoundingClientRect();
        if (r.left < bounds.left) {
          body.style.right = "";
          body.style.left = "0";
          r = body.getBoundingClientRect();
        }
        // symmetric guard: if left-anchoring now overflows the right edge,
        // fall back to whichever side clips less
        if (r.right > bounds.right) {
          body.style.left = "";
          body.style.right = "0";
        }
      };
      el.querySelectorAll(".tbw-pop").forEach((pop) => {
        const btn = pop.querySelector(".tbw-btn");
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const wasOpen = pop.classList.contains("open");
          el.querySelectorAll(".tbw-pop.open").forEach(closePop);
          if (!wasOpen) {
            pop.classList.add("open");
            positionPop(pop);
          }
        });
      });
      document.addEventListener("pointerdown", (e) => {
        if (!e.target.closest(".tbw-pop")) el.querySelectorAll(".tbw-pop.open").forEach(closePop);
      });

      // ── database file picker: suggestions dropdown over free-text input ─
      // The list is kept live-rendered even while hidden (cheap, and keeps
      // the caret-click case simple) -- .tbw-pop-body's display:none does
      // the actual hiding.
      const renderDbList = () => {
        const files = model.get("database_files") || [];
        const q = dbfile.value.trim().toLowerCase();
        const filtered = q ? files.filter((f) => f.toLowerCase().includes(q)) : files;
        dbList.innerHTML = filtered.length
          ? filtered.map((f) => `<div class="tbw-dbitem" data-file="${esc(f)}">${esc(f)}</div>`).join("")
          : `<div class="tbw-dbempty">No matching file — keep typing to save as / create a new one</div>`;
      };
      renderDbList();
      model.on("change:database_files", renderDbList);
      dbfile.addEventListener("input", renderDbList);
      dbfile.addEventListener("focus", () => {
        if (!dbPop.classList.contains("open")) {
          el.querySelectorAll(".tbw-pop.open").forEach(closePop);
          dbPop.classList.add("open");
          positionPop(dbPop);
        }
      });
      dbfile.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === "Escape") dbPop.classList.remove("open");
      });
      dbList.addEventListener("click", (e) => {
        const item = e.target.closest(".tbw-dbitem");
        if (!item) return;
        dbfile.value = item.dataset.file;
        model.set("database_filename", dbfile.value);
        model.save_changes();
        dbPop.classList.remove("open");
        dbfile.focus();
      });
      // The generic .tbw-pop click handler above already toggled dbPop's
      // "open" class by the time this fires (listeners on the same element
      // run in registration order) -- only rescan when the caret is the one
      // that just opened it, not on the close click.
      dbCaret.addEventListener("click", () => {
        if (dbPop.classList.contains("open")) model.send({ type: "refresh_database_files" });
      });

      // ── kernel -> browser: errors, save-as confirmation ────────────────
      model.on("msg:custom", (msg) => {
        if (!msg) return;
        if (msg.type === "create_error") {
          const target = msg.target === "recipe" ? errRecipe : errIngredient;
          target.textContent = msg.message || "Error";
        } else if (msg.type === "db_error") {
          bannerMsg.textContent = msg.message || "Error";
          bannerConfirm.style.display = "none";
          banner.classList.add("tbw-banner-error");
          banner.style.display = "flex";
        } else if (msg.type === "db_confirm") {
          bannerMsg.textContent = msg.message || "";
          bannerConfirm.style.display = "";
          banner.classList.remove("tbw-banner-error");
          banner.style.display = "flex";
        }
      });
      bannerConfirm.addEventListener("click", () => {
        model.send({ type: "confirm_write" });
        banner.style.display = "none";
      });
      bannerCancel.addEventListener("click", () => { banner.style.display = "none"; });
    }

    export default { render };
    """

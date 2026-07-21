"""
menu_button_widget.py — tiny anywidget "⋮" (kebab) menu button.

A single small button that opens a floating dropdown list of text actions.
Visually and behaviorally modeled on the per-row "⋮" menu already used in
recipe_grid_widget.py (same vertical-ellipsis icon, same small
floating-list-of-buttons dropdown, same click-outside-to-close), but
generic and reusable anywhere in the app that wants a compact "more
actions" menu instead of a row of always-visible buttons -- e.g.
DataFrameExplorer's top toolbar row.

Positioning
    Unlike recipe_grid_widget.py's per-row menu (a plain descendant of
    that same widget's own root), this button is typically embedded
    alongside *other, separate* widgets/Output areas -- e.g. sitting right
    above a recipe grid rendered in its own Output. A plain
    absolute/fixed-positioned descendant can still be clipped by some
    ancestor's overflow:hidden, or lose a paint/stacking fight against
    that sibling area even with a high z-index (z-index only resolves
    *within* a shared stacking context). So the open dropdown is instead
    appended straight to document.body ("portalled") and positioned from
    the button's actual getBoundingClientRect() -- which sidesteps both
    problems -- flipping upward and clamping horizontally if there isn't
    room to open downward/rightward in its default direction. Because the
    portalled menu is no longer inside .mv-app's subtree, it can't rely on
    the --mv-* variables menuview_theme.py scopes there for free dark-mode
    inheritance (unlike .mbw-btn, which stays put and still can); its
    colors are hardcoded in _css instead, with an explicit dark override.

Usage
    menu = MenuButtonWidget(items=[
        {'action': 'copy_sheet', 'label': 'Copy sheet'},
        {'action': 'create_label', 'label': 'Make label…'},
    ])

    def _on_menu(widget, content, buffers):
        if content.get('type') == 'menu_action':
            action = content.get('action')
            if action == 'copy_sheet':
                ...
            elif action == 'create_label':
                ...
    menu.on_msg(_on_menu)

    # display it (e.g. inside an HBox alongside other controls):
    widgets.HBox([..., menu, ...])

Item dicts
    'action'   required, str -- echoed back in the menu_action message so
               the handler can tell which item was clicked.
    'label'    required, str -- the button text shown in the dropdown.
    'disabled' optional, bool (default False) -- greys the item out and
               makes it unclickable, same as recipe_grid_widget.py's
               disabled Paste entry when there's nothing to paste.

items is a plain kernel -> browser trait (read-only from the browser's
side); update it with widget.items = [...] to change the menu contents,
e.g. to disable an item once some precondition stops holding.

Messages (browser -> kernel), via model.send:
    {type: "menu_action", action: <str>}   -- a non-disabled item was clicked
"""

import anywidget
import traitlets


class MenuButtonWidget(anywidget.AnyWidget):
    items = traitlets.List(traitlets.Dict()).tag(sync=True)

    _esm = r"""
    function render({ model, el }) {
      el.classList.add("mbw-root");

      const esc = (s) => String(s ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

      let menuEl = null;

      function closeMenu() {
        if (menuEl) { menuEl.remove(); menuEl = null; }
        document.removeEventListener("pointerdown", onOutsideClick, true);
        window.removeEventListener("resize", closeMenu);
        window.removeEventListener("scroll", closeMenu, true);
      }
      function onOutsideClick(e) {
        if (menuEl && !menuEl.contains(e.target) && !e.target.closest(".mbw-btn")) closeMenu();
      }

      function openMenu(btn) {
        closeMenu();
        const items = model.get("items") || [];
        menuEl = document.createElement("div");
        menuEl.className = "mbw-menu";
        menuEl.innerHTML = items.map((it, i) =>
          `<button data-i="${i}" ${it.disabled ? "disabled" : ""}>${esc(it.label)}</button>`
        ).join("");
        menuEl.querySelectorAll("button[data-i]").forEach((b) =>
          b.addEventListener("click", (ev) => {
            ev.stopPropagation();
            const it = items[+b.dataset.i];
            if (!it || it.disabled) return;   // true no-op -- menu stays open, matching a disabled control
            model.send({ type: "menu_action", action: it.action });
            closeMenu();
          }));

        // Appended straight to <body> (a "portal"), not as a descendant of
        // el -- a plain descendant positioned with absolute/fixed can
        // still be clipped by an ancestor's overflow:hidden, or lose a
        // paint/stacking fight against a sibling output area (e.g. the
        // recipe grid, rendered in its own separate Output widget) even
        // with a high z-index, since z-index only resolves *within* a
        // shared stacking context. A body-level portal sidesteps both
        // problems entirely. Positioned from the button's actual screen
        // coordinates (getBoundingClientRect is always viewport-relative,
        // regardless of any transformed/scrolled ancestors in between),
        // and rendered invisibly first so its natural size can be
        // measured before deciding where it fits.
        menuEl.style.visibility = "hidden";
        document.body.appendChild(menuEl);
        const r = btn.getBoundingClientRect();
        const mw = menuEl.offsetWidth, mh = menuEl.offsetHeight;
        const vw = window.innerWidth, vh = window.innerHeight;

        let top = r.bottom + 3;
        if (top + mh > vh && r.top - mh - 3 >= 0) top = r.top - mh - 3;   // flip up if it fits better there
        let left = r.left;
        if (left + mw > vw) left = Math.max(0, vw - mw - 4);             // clamp so it doesn't run off the right

        menuEl.style.position = "fixed";
        menuEl.style.top = `${Math.max(0, top)}px`;
        menuEl.style.left = `${Math.max(0, left)}px`;
        menuEl.style.visibility = "visible";

        document.addEventListener("pointerdown", onOutsideClick, true);
        // Repositioning on scroll/resize isn't implemented (matches the
        // simplicity of the rest of the app's popovers) -- just close the
        // menu instead, same as any other outside interaction would.
        window.addEventListener("resize", closeMenu);
        window.addEventListener("scroll", closeMenu, true);
      }

      el.innerHTML = `<button type="button" class="mbw-btn" title="more actions">&#8942;</button>`;
      const btn = el.querySelector(".mbw-btn");
      // stopPropagation so a parent row/handle (if this is ever nested in
      // one, matching the rgw-menu-btn precedent) doesn't also react to
      // the same click.
      btn.addEventListener("pointerdown", (e) => e.stopPropagation());
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (menuEl) closeMenu();
        else openMenu(e.currentTarget);
      });
    }
    export default { render };
    """

    _css = """
    .mbw-root {
        position: relative; display: inline-block;
        font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
    }
    .mbw-btn {
        font-size: 15px; line-height: 1; padding: 5px 10px;
        border-radius: 6px; border: 1px solid var(--mv-border, #dde3ea);
        background: var(--mv-accent-soft, #eaf1fe); color: var(--mv-accent, #2563eb);
        cursor: pointer;
    }
    .mbw-btn:hover { background: var(--mv-accent, #2563eb); color: #fff; }

    /* .mbw-menu is appended straight to <body> when open (see openMenu()
       in the ESM above), so it's no longer inside .mv-app's subtree and
       can't rely on the --mv-* variables menuview_theme.py scopes there
       for free dark-mode inheritance the way .mbw-btn above still can.
       Colors are hardcoded here instead, with an explicit dark override --
       the same self-contained approach recipe_grid_widget.py and
       guide_grid_widget.py already use for their own root-level theming,
       rather than depending on a particular ancestor. */
    .mbw-menu {
        position: fixed; z-index: 99999;
        display: flex; flex-direction: column;
        font-family: var(--jp-ui-font-family, -apple-system, sans-serif);
        background: #fff; border: 1px solid #dde3ea;
        border-radius: 8px; overflow: hidden;
        box-shadow: 0 4px 16px rgba(28,39,51,0.14); min-width: 160px;
    }
    .mbw-menu button {
        text-align: left; padding: 7px 12px; border: none; background: none;
        border-radius: 0; margin: 0; color: #1c2733;
        font-size: 13px; cursor: pointer; width: 100%;
    }
    .mbw-menu button:hover:not(:disabled) { background: #eaf1fe; color: #2563eb; }
    .mbw-menu button:disabled { opacity: 0.4; cursor: default; }

    body[data-jp-theme-light="false"] .mbw-menu { background: #262b31; border-color: #3a4149; }
    body[data-jp-theme-light="false"] .mbw-menu button { color: #d5dbe1; }
    body[data-jp-theme-light="false"] .mbw-menu button:hover:not(:disabled) { background: #1c2a3f; color: #5b9dff; }
    @media (prefers-color-scheme: dark) {
        body:not([data-jp-theme-light]) .mbw-menu { background: #262b31; border-color: #3a4149; }
        body:not([data-jp-theme-light]) .mbw-menu button { color: #d5dbe1; }
        body:not([data-jp-theme-light]) .mbw-menu button:hover:not(:disabled) { background: #1c2a3f; color: #5b9dff; }
    }
    """

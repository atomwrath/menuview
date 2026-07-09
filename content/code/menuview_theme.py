"""
menuview_theme.py — Workbench theme for menuview's ipywidgets layer.

One <style> block injected via a widgets.HTML placed inside the Explorer's
root VBox (so it ships wherever the vbox is displayed — JupyterLab Desktop
and JupyterLite alike, no notebook-level setup). All rules are scoped under
.mv-* classes added with widget.add_class(), so nothing outside menuview's
own UI is affected.

Palette matches RecipeGridWidget's --rgw-* variables (recipe_grid_widget.py),
including the dark-theme override keyed off body[data-jp-theme-light="false"]
with a prefers-color-scheme fallback for non-Jupyter hosts.

Usage:
    from menuview_theme import theme_widget
    self.vbox = widgets.VBox([theme_widget(), ...])
    self.vbox.add_class('mv-app')
"""

import ipywidgets as widgets

_PALETTE_DARK = """
        --mv-ink:         #d5dbe1;
        --mv-muted:       #9aa5af;
        --mv-surface:     #21262c;
        --mv-page:        #191d22;
        --mv-border:      #3a4149;
        --mv-border-soft: #2e343b;
        --mv-accent:      #5b9dff;
        --mv-accent-soft: #1c2a3f;
        --mv-accent-bord: #2f4b74;
        --mv-cost:        #4fd1b8;
        --mv-danger:      #ef6a5b;
        --mv-danger-soft: #3a2323;
        --mv-danger-bord: #6b3630;
        --mv-warn-ink:    #e8c674;
        --mv-warn-soft:   #3a331d;
        --mv-warn-bord:   #6b5a2e;
"""

THEME_CSS = """
<style>
/* ── Workbench palette ─────────────────────────────────────────────── */
.mv-app {
        --mv-ink:         #1c2733;
        --mv-muted:       #66727f;
        --mv-surface:     #ffffff;
        --mv-page:        #f4f6f8;
        --mv-border:      #dde3ea;
        --mv-border-soft: #ebeff3;
        --mv-accent:      #2563eb;
        --mv-accent-soft: #eaf1fe;
        --mv-accent-bord: #bcd3fb;
        --mv-cost:        #0f766e;
        --mv-danger:      #c0392b;
        --mv-danger-soft: #fdecea;
        --mv-danger-bord: #f0b8b0;
        --mv-warn-ink:    #8a6415;
        --mv-warn-soft:   #fff7e0;
        --mv-warn-bord:   #f0d99a;
}
body[data-jp-theme-light="false"] .mv-app {
%(dark)s
}
@media (prefers-color-scheme: dark) {
    body:not([data-jp-theme-light]) .mv-app {
%(dark)s
    }
}

/* ── cards & toolbar ───────────────────────────────────────────────── */
.mv-toolbar {
    background: var(--mv-surface);
    border: 1px solid var(--mv-border);
    border-radius: 8px;
    padding: 14px 16px;
    margin: 6px 0 14px 0;
}
.mv-eyebrow {
    font-size: 10.5px; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; color: var(--mv-muted);
    margin: 0 0 4px 0;
}
.mv-card {
    background: var(--mv-surface);
    border: 1px solid var(--mv-border);
    border-radius: 8px;
    padding: 10px 12px;
    margin: 0 0 14px 0;
}
.mv-mhead { font-weight: 600; color: var(--mv-ink); }

/* create row: two joined pairs side by side, wrap on narrow screens */
.mv-create-row {
    column-gap: 20px;
    row-gap: 8px;
    flex-wrap: wrap;
}
.mv-create-row .mv-pair {
    flex: 1 1 260px;
}

/* columns row: spread checkboxes + equ quant across the full row */
.mv-columns-row {
    column-gap: 20px;
    row-gap: 8px;
    flex-wrap: wrap;
}
.mv-columns-row .widget-label {
    min-width: 0 !important;
    width: auto !important;
}

/* ── buttons ───────────────────────────────────────────────────────── */
.mv-app .jupyter-button {
    background: var(--mv-surface);
    border: 1px solid var(--mv-border);
    border-radius: 6px;
    color: var(--mv-ink);
    box-shadow: none;
}
.mv-app .jupyter-button:hover:enabled,
.mv-app .jupyter-button:focus:enabled {
    background: var(--mv-accent-soft);
    border-color: var(--mv-accent-bord);
    color: var(--mv-accent);
    box-shadow: none;
}
/* button_style='info' (e.g. "Create as new recipe") -> solid accent */
.mv-app .jupyter-button.mod-info {
    background: var(--mv-accent); border-color: var(--mv-accent); color: #fff;
}
.mv-app .jupyter-button.mod-info:hover:enabled { background: #1d4fd8; color: #fff; }
/* button_style='warning'/'danger' (destructive / confirm) -> outline amber/red */
.mv-app .jupyter-button.mod-warning {
    background: var(--mv-surface); border-color: #e0a80c; color: #a97e06;
}
.mv-app .jupyter-button.mod-warning:hover:enabled { background: #fff7e0; color: #a97e06; }
.mv-app .jupyter-button.mod-danger {
    background: var(--mv-surface); border-color: #d64545; color: #c03535;
}
.mv-app .jupyter-button.mod-danger:hover:enabled { background: #fdeaea; color: #c03535; }

/* ── ToggleButtons -> segmented control ────────────────────────────── */
.mv-app .widget-toggle-buttons .jupyter-button {
    border-radius: 0; margin: 0; border-right-width: 0;
    color: var(--mv-muted);
}
.mv-app .widget-toggle-buttons .jupyter-button:first-of-type { border-radius: 6px 0 0 6px; }
.mv-app .widget-toggle-buttons .jupyter-button:last-of-type {
    border-radius: 0 6px 6px 0; border-right-width: 1px;
}
.mv-app .widget-toggle-buttons .jupyter-button.mod-active {
    background: var(--mv-accent-soft); color: var(--mv-accent); font-weight: 600;
    box-shadow: none;
}
.mv-app .widget-checkbox {
    width: auto !important;
    margin-right: 0;
}

/* ── text / number inputs, combobox ────────────────────────────────── */
.mv-app input[type="text"], .mv-app input[type="number"] {
    background: var(--mv-surface);
    border: 1px solid var(--mv-border);
    border-radius: 6px;
    color: var(--mv-ink);
}
.mv-app input[type="text"]:focus, .mv-app input[type="number"]:focus {
    outline: 2px solid var(--mv-accent-soft);
    border-color: var(--mv-accent);
}
.mv-app input[type="checkbox"] { accent-color: var(--mv-accent); }
.mv-app .widget-label, .mv-app .widget-label-basic { color: var(--mv-ink); }

/* FloatsInput tags (cost multipliers "3.00 x") */
.mv-app .jupyter-widget-tag {
    background: var(--mv-accent-soft) !important;
    color: var(--mv-accent) !important;
    border: 1px solid var(--mv-accent-bord);
    border-radius: 999px;
}

/* ── joined input+button pairs (create recipe / ingredient) ────────── */
.mv-pair input[type="text"] { border-radius: 6px 0 0 6px; border-right: none; }
.mv-pair .jupyter-button {
    border-radius: 0 6px 6px 0;
    background: var(--mv-accent-soft);
    border-color: var(--mv-accent-bord);
    color: var(--mv-accent);
    font-weight: 600;
    margin-left: 0;
}

/* ── menu category chips (BREAKFAST / LUNCH / ...) ─────────────────── */
.mv-menu .jupyter-button {
    border-radius: 999px;
    background: var(--mv-accent-soft);
    border: 1px solid var(--mv-accent-bord);
    color: var(--mv-accent);
    font-weight: 600; font-size: 11px; letter-spacing: .04em;
    text-transform: uppercase;
}
.mv-menu .jupyter-button:hover:enabled { background: #dbe8fd; color: var(--mv-accent); }
body[data-jp-theme-light="false"] .mv-menu .jupyter-button:hover:enabled {
    background: #24365a;
}

/* invalid-state helper for widgets that toggle it via add_class/remove_class
   instead of the old style.text_color pattern (more reliable across
   different @jupyter-widgets frontend bundle versions — notably JupyterLite's,
   which doesn't always honor clearing an inline style back to None) */
.mv-app .mv-invalid, .mv-app .mv-invalid input {
    color: var(--mv-danger, #c0392b) !important;
}


/* ── top Tab bar (Menu Explorer / Order Guide Read) ────────────────── */
/* lm- is current Lumino; p- covers older phosphor-based frontends */
.mv-tabs .lm-TabBar-tab, .mv-tabs .p-TabBar-tab {
    border: 1px solid var(--mv-border); border-bottom: none;
    border-radius: 8px 8px 0 0;
    background: var(--mv-page); color: var(--mv-muted);
    padding: 4px 18px;
}
.mv-tabs .lm-TabBar-tab.lm-mod-current, .mv-tabs .p-TabBar-tab.p-mod-current {
    background: var(--mv-surface); color: var(--mv-ink); font-weight: 600;
}
</style>
""" % {"dark": _PALETTE_DARK}


def theme_widget():
    """Return the injectable stylesheet as a zero-height HTML widget."""
    w = widgets.HTML(value=THEME_CSS)
    w.layout = widgets.Layout(height='0px', margin='0', padding='0')
    return w

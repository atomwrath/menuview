import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display, clear_output
from costcalulator import CostCalculator
from utils import *
from label_maker import LabelMakerWidget

try:
    from recipe_grid_widget import RecipeGridWidget
except Exception:          # anywidget not installed — fast view silently off
    RecipeGridWidget = None

try:
    from guide_grid_widget import GuideGridWidget
except Exception:          # anywidget not installed — fast view silently off
    GuideGridWidget = None


class _FastCellShim:
    '''Stands in for an ipywidgets Text/Combobox/Button when edit handlers
    are driven from the fast grid. Records validity feedback the handlers
    would have painted onto the widget (red text / red border) so it can be
    relayed to the browser instead.'''

    class _Style:
        def __init__(self, owner): self._o = owner
        @property
        def text_color(self): return 'red' if self._o.invalid else None
        @text_color.setter
        def text_color(self, v): self._o.invalid = (v == 'red')

    class _Layout:
        def __init__(self, owner): self._o = owner
        @property
        def border(self): return '2px solid red' if self._o.invalid else ''
        @border.setter
        def border(self, v): self._o.invalid = bool(v and 'red' in str(v))

    def __init__(self):
        self.invalid = False
        self.style = _FastCellShim._Style(self)
        self.layout = _FastCellShim._Layout(self)
        self.tag = None


def _strip_trailing_zero(s):
    '''"4.0" -> "4"; leaves "4.5", "0.333", etc. untouched.'''
    if s.endswith('.0'):
        return s[:-2]
    return s


def _format_quantity_full(magf, unit_str):
    '''Full-precision magnitude, for Copy/Cut: Python's shortest round-trip
    decimal repr (the exact digits needed to reconstruct the value — no
    artificial rounding), with a trailing ".0" stripped for whole numbers.
    Always plain decimal, never scientific notation — this is the value
    that ends up on the clipboard and gets pasted elsewhere.
    '''
    if magf == 0:
        return f"0 {unit_str}".strip()
    return f"{_strip_trailing_zero(repr(float(magf)))} {unit_str}".strip()


def _format_quantity_display(magf, unit_str):
    '''Capped-precision magnitude, for on-screen display: up to 3 decimal
    places (trailing zeros/point stripped, so whole numbers show as "4" and
    "0.5" doesn't pad out to "0.500"), switching to scientific notation
    (mantissa capped at 3dp the same way, e.g. "2.222e-3") once the
    magnitude drops under 0.01.
    '''
    if magf == 0:
        return f"0 {unit_str}".strip()
    if abs(magf) < 0.01:
        mantissa, exp = f"{magf:.3e}".split('e')
        mantissa = mantissa.rstrip('0').rstrip('.') or '0'
        sign, exp_digits = exp[0], exp[1:].lstrip('0') or '0'
        s = f"{mantissa}e{sign}{exp_digits}"
    else:
        s = f"{magf:.3f}".rstrip('0').rstrip('.')
        if s in ('', '-'):
            s = '0'
    return f"{s} {unit_str}".strip()


class DataFrameWidget:
    ''' ipywidgets based interactive interface for pandas
    '''
    _clipboard = None   # {'op': 'copy'|'cut', 'recipe': str, 'rows': [dict, ...]}
    _open_grids = []    # every DataFrameWidget currently showing a fast grid (this widget plus
                         # any nested "view below" parents/children) — used to keep only one
                         # selection "live" across all of them, and to keep every open grid's
                         # has_clipboard in sync with the single shared clipboard above.
    def __init__(self, df, width='80px', enabled_columns=None, hide_columns=None,
             cc=CostCalculator(), output=widgets.Output(), trigger=None,
             all_enabled_columns=None, widget_mode='Edit'):
        self.df = df.reset_index(drop=True).copy()
        self.defcolor = widgets.Text().style.text_color
        self.width = width
        self.column_width = {}
        self.df_type = None
        self.enabled_columns = enabled_columns if enabled_columns else []
        self.all_enabled_columns = all_enabled_columns if all_enabled_columns else list(self.enabled_columns)
        self.hide_columns = hide_columns if hide_columns else []
        self.cc = cc
        nicks = set(cc.uni_g['nickname'].dropna().unique())
        ingrs = set(cc.costdf['ingredient'].dropna().unique())
        self.all_ingredients = nicks.union(ingrs)
        self.buttons = {}
        self.output = output
        self.num_cols = 0
        self.trigger = trigger
        self.last_lookup = ''
        self.last_lookup = ''
        self._focus_ingredient_input = False
        self.root_trigger = None   # set on children only: the trigger function that
                            # belongs to the top-level (root) display
        self._guide_row_index_map = {}   # display row position -> real uni_g index, for guide pages
        self._guide_row_used_map = {}    # display row position -> bool, whether cost_picker is
                                  # currently using that entry for cost calculation
        self.equ_quant_precision = None
        self.equ_quant_unit = None              # target unit for "equ quant" column
        self.scale_factor = None                # current display scale ratio (float|None)
        self._scaled_quantity_full = {}         # row idx -> full-precision scaled quantity
                                                 # string, set by _apply_scaling when scaling
                                                 # is active; the displayed 'quantity' cell is
                                                 # rounded for readability, but Copy/Cut read
                                                 # from here so nothing is lost in the clipboard
        self._pending_lookup_quantity = None    # set by on_lookup_click before trigger fires
        self._navigating_back = False           # True while on_back_click is executing;
                                                # tells update_search not to clear scale
        self._pending_insert = None        # (anchor_ingredient, 'before'|'after') awaiting a mid-list slot
        self._pending_insert_name = None   # ingredient name to pre-fill that slot with, or None for a blank slot # row index -> delete Button widget, for direct enable/disable
        self.recipe_changed_callback = None   # fired with the recipe name whenever a recipe's
                                              # ingredient membership changes (add/remove/rename);
                                              # DataFrameExplorer uses it to keep the fullmenu
                                              # shortcut buttons in sync
        self.child_widget = None       # currently-open nested "view below" widget, or None
        self.child_ingredient = None   # name of the ingredient the child is showing
        self.child_output = widgets.Output()   # persistent Output the child renders into
        self.parent_refresh = None     # set when THIS widget is someone else's child;
                                        # called after any edit so the ancestor's own
                                        # cost/quantity cells stay in sync
        
        self.add_ingredient_widget = None  # bottom blank row's ingredient box (focus target)
        self.ingredient_widgets = []       # every ingredient Combobox currently on screen
        
        self.add_ingredient_widget = None 
        self._last_deleted = None   # snapshot of the most recently deleted ingredient row, for reorder-restore
        
        self.search_history = []
        self.scale_stack = []    # parallel to search_history; entry[i] = scale active at level i
        self.search_history = []  # Add this line for tracking history
        self.forward_stack = []        # items undone via Back, redoable via Forward
        self.forward_scale_stack = []  # parallel to forward_stack; entry[i] = scale active at level i
        self.backbutton = widgets.Button(
            description='', icon='arrow-left', tooltip='back',
            disabled=True, layout=widgets.Layout(width='36px'),
        )
        self.backbutton.on_click(self.on_back_click)
        self.forwardbutton = widgets.Button(
            description='', icon='arrow-right', tooltip='forward',
            disabled=True, layout=widgets.Layout(width='36px'),
        )
        self.forwardbutton.on_click(self.on_forward_click)
        self.cost_multipliers = [3.0]
        self.widget_mode = widget_mode                       # 'Edit' | 'View' | 'Flatten' — owned by THIS widget
        self.scale_qty_editable = (widget_mode != 'Edit')
        self.mode_changed_callback = None   
        self.scale_quantity_callback = None  # set by DataFrameExplorer
        self.delete_confirm_callback = None  # set by DataFrameExplorer
        self.guide_changed_callback = None   # set by DataFrameExplorer; called whenever uni_g membership changes
        
        # ── Fast View (anywidget) ─────────────────────────────────────────
        # One-model HTML grid used for recipe View mode. Set use_fast_view to
        # False to force the classic ipywidgets grid everywhere.
        self.use_fast_view   = RecipeGridWidget is not None
        self._fast_grid      = None    # RecipeGridWidget instance (created lazily)
        self._fast_box       = None    # persistent VBox: [grid, child_output]
        self._fast_displayed = False   # True while _fast_box is what's on screen
        self._fast_ingredient_opts = None   # last options list sent to the fast grid
        self._fast_last_recipe = None   # last recipe name shown in the fast grid,
                                         # used to reset selected_rows on navigation
        self._selection_controls = None   # optional extra ipywidgets widget shown above the
                                           # grid (used by the "view selected below" panel for
                                           # its Create/Replace buttons); set before first display

        # One-model HTML grid used for guide (price-entry) display — the
        # guide-display equivalent of the recipe fast-view fields above.
        self._fast_guide_grid      = None    # GuideGridWidget instance (created lazily)
        self._fast_guide_box       = None    # persistent VBox: [delete-confirm row, grid, child_output]
        self._fast_guide_displayed = False   # True while _fast_guide_box is what's on screen
        
        # inline confirmation for deleting an ingredient's LAST guide entry when
        # that ingredient is used in one or more recipes
        self._delete_confirm_msg = widgets.HTML(value='')
        self._delete_confirm_yes = widgets.Button(
            description='✓ Delete anyway', button_style='danger',
            layout=widgets.Layout(width='160px')
        )
        self._delete_confirm_no = widgets.Button(
            description='✗ Cancel', layout=widgets.Layout(width='90px')
        )
        
        self._delete_confirm_yes.on_click(self._on_confirm_delete_ingredient)
        self._delete_confirm_no.on_click(self._on_cancel_delete_ingredient)
        self._delete_confirm_row = widgets.HBox(
            [self._delete_confirm_msg, self._delete_confirm_yes, self._delete_confirm_no],
            layout=widgets.Layout(display='none', align_items='center',
                                border='2px solid orange', padding='5px', margin='0 0 5px 0')
        )
        self._pending_guide_delete = None  # dict awaiting confirmation, or None
        
        # Add progress bar for loading
        self.progress_bar = widgets.IntProgress(
            value=0,
            min=0,
            max=100,
            description='Loading:',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='200px', visibility='hidden')
        )
        # self.findtype()
        if self.df.empty:
            self.df_type = None
        elif 'ingredient' in self.df.columns and len(self.df['ingredient'].dropna().unique()) == 1:
            self.df_type = 'mentions'
        elif 'nickname' in self.df.columns:
            self.df_type = 'guide'
        elif 'ingredient' in self.df.columns:
            self.df_type = 'recipe'
        else:
            self.df_type = None
            
        self.df_types = set(('guide', 'recipe', 'mentions'))
        
        self.grid = self._create_grid()

    def setdf(self, mylookup):
        self.last_lookup = mylookup
        rentry = self.cc.get_recipe_entry(mylookup)
        if rentry is not None and not rentry.empty:
            mydf = self.cc.findframe(
                mylookup,
                equ_quant_unit=self.equ_quant_unit,
                equ_quant_precision=self.equ_quant_precision
            ).reset_index(drop=True).copy()
        else:
            # Guide-only ingredient: show the full price history (not just
            # the subset cost_picker currently selects for cost calc) so
            # editing and the "in use" highlight have the complete picture.
            # cost_picker / get_cost_df / findframe are untouched, so actual
            # cost calculations elsewhere are unaffected by this.
            mydf = self.cc.guide_display_frame(mylookup).reset_index(drop=True).copy()
        self.df = mydf
        self._scaled_quantity_full = {}
        self.findtype()
        if (self.df_type == 'recipe'):
            colorder = ['item', 'ingredient', 'quantity', 'equ quant', 'cost']
            mydf = reorder_columns(mydf, colorder)
            mycolumns = [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            for cm in self.cost_multipliers:
                if cm > 0:
                    add_costx(mydf, cm)
            if 'menu price' in mydf.columns and len(self.cost_multipliers) > 0:
                add_netprofit(mydf, self.cost_multipliers[0])
            # Apply view-mode scaling after all columns are finalised.
            # This is purely cosmetic – cc.costdf is never touched.
            if self.scale_factor is not None:
                mydf = self._apply_scaling(mydf, self.scale_factor)
            # add_costx appends "cost N.Nx" columns at the end -- pull them
            # back to sit right after 'cost', and make sure 'equ quant' is
            # right after 'quantity', regardless of what got added above.
            mydf = order_recipe_columns(mydf)
            self.df = mydf
            self.update_column_width()

        else:
            mycolumns = mydf.columns
            if (self.df_type == 'guide'):
                # Remember each displayed row's underlying uni_g index (added by
                # get_cost_df as '_guide_index') BEFORE stripping internal columns.
                # on_delete_click uses this instead of fragile multi-column value
                # matching, which breaks down with NaNs, string-vs-float prices,
                # or identical rows (e.g. from "duplicate").
                if '_guide_index' in mydf.columns:
                    self._guide_row_index_map = dict(enumerate(mydf['_guide_index']))
                else:
                    self._guide_row_index_map = {}
                # Same idea for '_cost_used' (added by guide_display_frame): a
                # display-row -> bool map, read by _update_display_fast_guide
                # to highlight the rows currently feeding cost calculation.
                if '_cost_used' in mydf.columns:
                    self._guide_row_used_map = dict(enumerate(mydf['_cost_used']))
                else:
                    self._guide_row_used_map = {}
                mycolumns = [x for x in mydf.columns
                             if x not in ('myconversion', 'mycost', '_guide_index', '_cost_used')]
            
            
    def update_column_width(self):
        def carlen(myval):
            myval = f"{myval:0.2f}" if isinstance(myval, float) else myval
            return len(str(myval))

        # Calculate maxlen using map
        try:
            maxlen = self.df.apply(lambda x: x.map(lambda y: 5 + 10 * carlen(y))).max().to_dict()
            
            # Calculate cn_len for column names
            cn_len = {c: 5 + 8 * len(str(c)) for c in self.df.columns}

            # Update column_width using the maximum value between maxlen and cn_len
            self.column_width = {c: max(maxlen[c], cn_len[c]) for c in maxlen}
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
        except:
            # If there's an error, create a default width for each column
            self.column_width = {c: 5 + 8 * len(str(c)) for c in self.df.columns}
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
                
    def _apply_scaling(self, mydf, scale):
        '''Scale quantities and costs in a display copy of a recipe DataFrame.

        This never writes back to self.cc.costdf – it only modifies the copy
        that will be displayed to the user in view mode.

        Columns scaled:
          - quantity    : displayed at up to 3 decimal places (trailing
                          zeros/point stripped), switching to scientific
                          notation under 0.01 — but the full, unrounded
                          value is separately cached in
                          self._scaled_quantity_full for Copy/Cut to use,
                          so nothing is lost off the clipboard.
          - equ quant   : pint-aware string  ("236.5 g"   → "118.2 g"), skips n/a
          - cost        : float
          - cost N.Nx   : float  (any "cost N.Nx" column added by add_costx)
        '''
        # No-op for full batches: avoids reformatting original quantity strings
        # ("1 cup" would otherwise become "1.0000 cup").
        if abs(scale - 1.0) < 1e-9:
            return mydf
        for idx in mydf.index:
            # ── quantity ──────────────────────────────────────────────────────
            q_str = str(mydf.at[idx, 'quantity'])
            try:
                q = parse_quant(q_str)
                if q is not None and hasattr(q, 'm') and q.m > 0:
                    scaled = q * scale
                    unit_str = f"{scaled.units:~}"
                    magf = float(scaled.magnitude)
                    self._scaled_quantity_full[idx] = _format_quantity_full(magf, unit_str)
                    mydf.at[idx, 'quantity'] = _format_quantity_display(magf, unit_str)
            except Exception:
                pass

            # ── equ quant (skip blanks and "n/a") ────────────────────────────
            if 'equ quant' in mydf.columns:
                eq_str = str(mydf.at[idx, 'equ quant'])
                if eq_str not in ('', 'nan', 'n/a', 'None'):
                    try:
                        # equ quant is stored as "value unit_string" (e.g. "120.0 g",
                        # "384 1/8 tsp").  Extract the numeric part, scale it, reformat
                        # using the stored precision (or 4 dp by default).
                        import re as _re
                        m = _re.match(r'^\s*([\d.]+)\s*(.*)', eq_str)
                        if m:
                            num  = float(m.group(1)) * scale
                            unit = m.group(2).strip()
                            prec = self.equ_quant_precision if self.equ_quant_precision is not None else 4
                            mydf.at[idx, 'equ quant'] = f"{num:.{prec}f} {unit}".strip()
                        else:
                            # fallback: pint parse
                            eq = parse_quant(eq_str)
                            if eq is not None and hasattr(eq, 'm') and eq.m > 0:
                                prec = self.equ_quant_precision if self.equ_quant_precision is not None else 4
                                mydf.at[idx, 'equ quant'] = (
                                    f"{(eq * scale).magnitude:.{prec}f} {eq.units:~}"
                                )
                    except Exception:
                        pass
                    
            # ── cost ─────────────────────────────────────────────────────────
            if 'cost' in mydf.columns:
                try:
                    mydf.at[idx, 'cost'] = float(mydf.at[idx, 'cost']) * scale
                except (TypeError, ValueError):
                    pass
 
            # ── cost N.Nx columns (added by add_costx) ───────────────────────
            for col in mydf.columns:
                if col != 'cost' and col.startswith('cost') and col.endswith('x'):
                    try:
                        mydf.at[idx, col] = float(mydf.at[idx, col]) * scale
                    except (TypeError, ValueError):
                        pass
 
        return mydf
        
    def _notify_recipe_changed(self, recipename):
        '''Announce that recipename's ingredient list changed. Call this right
        after the cc mutation, not after update_display -- the listener reads
        cc state, and keeping the call adjacent to the mutation is what makes
        it obvious at each site whether it's been done.
        '''
        if self.recipe_changed_callback is not None:
            try:
                self.recipe_changed_callback(recipename)
            except Exception as exc:
                print(f'[recipe changed] {exc}')

    def _next_committed_anchor(self, recipename, start_index):
        ''' Scan self.df forward from start_index for the next already-
            committed ingredient — used to position a newly-inserted row
            relative to whatever currently follows it on screen.
        '''
        for j in range(start_index, len(self.df)):
            name = self.df.iloc[j]['ingredient']
            if name and not self.cc.get_item_ingredient(recipename, name).empty:
                return name
        return None

    def _commit_restored_ingredient(self, recipename, ingredient_name, anchor):
        ''' Insert ingredient_name before `anchor` (or at the end if None),
            restoring quantity / menu price / note from the last-deleted
            snapshot rather than starting blank. Used for reordering: delete
            an ingredient, then re-add it elsewhere in the same recipe.
        '''
        snap = self._last_deleted
        self.cc.insert_ingredient(recipename, ingredient_name, snap.get('quantity', ''), before=anchor)
        self._notify_recipe_changed(recipename)
        if 'menu price' in self.cc.costdf.columns and snap.get('menu price', '') not in ('', None):
            self.cc.set_item_ingredient(recipename, ingredient_name, 'menu price', snap.get('menu price'))
        if 'note' in self.cc.costdf.columns and snap.get('note', '') not in ('', None):
            self.cc.set_item_ingredient(recipename, ingredient_name, 'note', snap.get('note'))
        self._last_deleted = None
        self._pending_insert = None
        self._pending_insert_name = None
        self.cc.clear_cost(recipename)
        self.cc.recipe_cost(recipename)
        self.setdf(recipename)
        self.update_display()
        
    def set_widget_mode(self, mode, refresh=True):
        '''Switch THIS widget's own Edit/View/Flatten state. Independent of any
        parent display — nothing cascades from here to self.child_widget, and
        nothing cascades down to here from a parent either.
        '''
        self.widget_mode = mode

        if mode == 'Edit':
            self.scale_factor = None
            self.scale_stack   = [None] * len(self.search_history)
            self.enabled_columns = list(self.all_enabled_columns)
            self.scale_qty_editable = False
        else:   # View or Flatten
            self.enabled_columns = []
            self.scale_qty_editable = True

        if self.mode_changed_callback is not None:
            self.mode_changed_callback(mode)

        if not refresh or not self.last_lookup:
            return

        if mode == 'Flatten':
            self._render_flattened()
        else:
            self.lookup_name(self.last_lookup)
            self.update_display()
            
    def _default_scale_quantity_callback(self, new_qty_str, widget):
        item = self.last_lookup
        if not item:
            return
        recipe_entry = self.cc.get_recipe_entry(item)
        if recipe_entry.empty:
            return
        recipe_yield_str = str(recipe_entry.squeeze()['quantity']).strip()
        input_str = new_qty_str.strip()
        if not input_str:
            return
        try:
            ry = parse_quant(recipe_yield_str)
            pq = parse_quant(input_str)
            if pq is None or ry is None or ry.m == 0:
                widget.style.text_color = 'red'
                return
            if pq.dimensionality == ry.dimensionality:
                scale = float((pq / ry).to_reduced_units().m)
            else:
                converted = self.cc.do_conversion(item, input_str, recipe_yield_str)
                if converted is None:
                    widget.style.text_color = 'red'
                    return
                scale = float((converted / ry).to_reduced_units().m)
            if scale <= 0:
                widget.style.text_color = 'red'
                return
            widget.style.text_color = self.defcolor
            self.scale_factor = scale
            if self.widget_mode == 'Flatten':
                self._render_flattened()
            else:
                self.lookup_name(item)
                self.update_display()
        except Exception as exc:
            print(f'[view_scale] {exc}')
            widget.style.text_color = 'red'
            
            
    def _render_flattened(self):
        item = self.last_lookup
        if not item:
            return
        recipe_entry = self.cc.get_recipe_entry(item)
        if recipe_entry.empty:
            # Not a recipe (e.g. navigated to a simple ingredient) — Flatten
            # doesn't apply; fall back to a normal display instead of an error.
            self.widget_mode = 'View'
            self.setdf(item)
            self.update_display()
            return

        recipe_yield_str = str(recipe_entry.squeeze()['quantity']).strip()
        scale = self.scale_factor
        if scale is not None:
            try:
                scaled_yield = parse_quant(recipe_yield_str) * scale
                quant_str = _format_quantity_display(
                    float(scaled_yield.magnitude), f"{scaled_yield.units:~}")
            except Exception:
                quant_str = recipe_yield_str
        else:
            quant_str = recipe_yield_str

        self.cc.recipe_cost(item)

        try:
            flat_df = self.cc.flatten_recipe(item, recipe_yield_str)
        except Exception as exc:
            with self.output:
                self.output.clear_output(wait=True)
                print(f'Could not flatten "{item}": {exc}')
            self._fast_displayed = False   # output was cleared out from under the fast box
            return

        if flat_df is None or flat_df.empty:
            with self.output:
                self.output.clear_output(wait=True)
                print(f'No base ingredients found for "{item}".')
            self._fast_displayed = False   # output was cleared out from under the fast box
            return

        flat_df = flat_df.copy()

        do_scale = scale is not None and abs(scale - 1.0) > 1e-9
        weight_dim = parse_quant('1 kg').dimensionality
        volume_dim = parse_quant('1 liter').dimensionality

        # Stage 1: scale, kept at full precision (not the final display
        # string yet) — the equ-quant conversion below, and the
        # standard-units conversion after it, both need an accurate value
        # to work from, not something already rounded to 2dp.
        if do_scale:
            def _scale_full(row):
                try:
                    pq = parse_quant(str(row['quantity']))
                    if pq is not None and hasattr(pq, 'm') and pq.m > 0:
                        scaled = pq * scale
                        return _format_quantity_full(float(scaled.magnitude), f"{scaled.units:~}")
                except Exception:
                    pass
                return row['quantity']
            flat_df['quantity'] = flat_df.apply(_scale_full, axis=1)
            if 'cost' in flat_df.columns:
                flat_df['cost'] = flat_df['cost'].apply(
                    lambda c: float(c) * scale
                    if pd.notna(c) and str(c) not in ('', 'nan') else c
                )

        equ_unit = self.equ_quant_unit
        equ_prec = self.equ_quant_precision
        if equ_unit:
            flat_df = flat_df.apply(
                lambda row: self.cc.add_equ_quant(row, equ_unit, precision=equ_prec), axis=1
            )

        # Stage 2: normalize to standard units (g/ml) and do the *final*
        # display/full-precision formatting in one step. This used to be a
        # separate pass that reparsed an already-.2f-rounded string and
        # reformatted with its own hardcoded ".2f" — which is what was
        # silently throwing away the display helpers' precision and
        # scientific notation the moment it ran.
        full_precision_by_name = {}

        def _finalize_quantity(row):
            ingredient = row['ingredient']
            try:
                q = parse_quant(str(row['quantity']))
                if q is None:
                    return row['quantity']
                converted = None
                if q.dimensionality == weight_dim:
                    converted = q.to('g')
                else:
                    result = self.cc.do_conversion(ingredient, q, '1 g')
                    if result is not None:
                        converted = result.to('g')
                    elif q.dimensionality == volume_dim:
                        converted = q.to('ml')
                    else:
                        result = self.cc.do_conversion(ingredient, q, '1 ml')
                        if result is not None:
                            converted = result.to('ml')
                final_q = converted if converted is not None else q
                unit_str = f"{final_q.units:~}"
                magf = float(final_q.magnitude)
                full_precision_by_name[str(ingredient).strip()] = _format_quantity_full(magf, unit_str)
                return _format_quantity_display(magf, unit_str)
            except Exception:
                return row['quantity']

        flat_df['quantity'] = flat_df.apply(_finalize_quantity, axis=1)

        flat_df = self._sort_flattened(flat_df)

        total_cost = 0.0
        if 'cost' in flat_df.columns:
            try:
                total_cost = flat_df['cost'].apply(lambda x: float(x) if pd.notna(x) else 0.0).sum()
            except (TypeError, ValueError):
                pass

        header = {col: '' for col in flat_df.columns}
        header.update({'item': 'recipe', 'ingredient': item, 'quantity': quant_str, 'cost': total_cost})
        if equ_unit and 'equ quant' in flat_df.columns:
            header['equ quant'] = ''

        flat_df['item'] = item
        display_df = pd.concat([pd.DataFrame([header]), flat_df], ignore_index=True)

        colorder = ['item', 'ingredient', 'quantity']
        if equ_unit and 'equ quant' in display_df.columns:
            colorder.append('equ quant')
        if 'cost' in display_df.columns:
            colorder.append('cost')
        display_df = reorder_columns(display_df, colorder)

        hide = set(self.hide_columns)
        if equ_unit:
            hide.discard('equ quant')
        else:
            hide.add('equ quant')
        display_df = display_df[[c for c in display_df.columns if c not in hide]]

        if 'cost' in display_df.columns:
            for cm in self.cost_multipliers:
                if cm > 0:
                    display_df[f'cost {cm:.1f}x'] = display_df['cost'].apply(
                        lambda x: float(x) * cm if pd.notna(x) and str(x) not in ('', 'nan') else ''
                    )

        display_df = display_df.reset_index(drop=True)
        self.df              = display_df
        self.df_type         = 'recipe'
        self.enabled_columns = []
        self._scaled_quantity_full = {}
        if full_precision_by_name:
            for i, ing in display_df['ingredient'].items():
                key = str(ing).strip()
                if key in full_precision_by_name:
                    self._scaled_quantity_full[i] = full_precision_by_name[key]
        self.update_column_width()
        self.update_display()

    def _sort_flattened(self, df):
        def _key(qty_str):
            s = str(qty_str).strip()
            try:
                if s.endswith(' g'):
                    return (0, -float(s[:-2].strip()))
                if s.endswith(' ml'):
                    return (1, -float(s[:-3].strip()))
                q = parse_quant(s)
                if q is not None:
                    if q.dimensionality == parse_quant('1 kg').dimensionality:
                        return (0, -float(q.to('g').magnitude))
                    if q.dimensionality == parse_quant('1 liter').dimensionality:
                        return (1, -float(q.to('ml').magnitude))
            except Exception:
                pass
            return (2, 0.0)
        df = df.copy()
        df['_sort_key'] = df['quantity'].apply(_key)
        df = df.sort_values('_sort_key').drop(columns=['_sort_key'])
        return df.reset_index(drop=True)

    def _make_subgrid(self, items_slice):
                return widgets.GridBox(
                    items_slice,
                    layout=widgets.Layout(grid_template_columns=self._grid_template_columns),
                )
    
    # ── Fast View (anywidget) ─────────────────────────────────────────────

    def _fast_format_value(self, v):
        '''Match create_row's display formatting: blanks for nan/'',
        floats to 2 decimal places, everything else str().'''
        if str(v) in (str(np.nan), ''):
            return ''
        return f"{v:0.2f}" if isinstance(v, float) else str(v)

    def _update_display_fast(self):
        '''Render self.df into the single-model fast grid (View or Edit).

        First call displays a persistent VBox [grid, child_output] into
        self.output; every later call is pure trait updates on the live
        widget — no clear_output, no rebuild, no flicker.
        '''
        edit_mode = (self.widget_mode == 'Edit')

        # ── Edit mode: trailing blank add-row + pending insert, mirroring
        #    the identical block in _create_grid (unconditionally, so the
        #    two paths stay in exact behavioral parity) ────────────────────
        if edit_mode and self.df_type == 'recipe':
            new_row = pd.DataFrame({column: [''] for column in self.df.columns})
            new_row['item'] = self.df.iloc[0]['ingredient']
            self.df = pd.concat([self.df, new_row], ignore_index=True)

            if self._pending_insert is not None:
                anchor_name, direction = self._pending_insert
                anchor_idx = self.df.index[self.df['ingredient'] == anchor_name]
                if len(anchor_idx) > 0:
                    pos = self.df.index.get_loc(anchor_idx[0])
                    if direction == 'after':
                        pos += 1
                    blank = pd.DataFrame({column: [''] for column in self.df.columns})
                    blank['item'] = self.df.iloc[0]['ingredient']
                    if self._pending_insert_name:
                        blank['ingredient'] = self._pending_insert_name
                    self.df = pd.concat(
                        [self.df.iloc[:pos], blank, self.df.iloc[pos:]],
                        ignore_index=True)
                else:
                    self._pending_insert = None
                    self._pending_insert_name = None

        cols = list(self.df.columns)
        n_rows = len(self.df)
        conv_errors = getattr(self.cc, 'conversion_errors', set())

        # Same per-column pixel widths the classic grid uses (getlayout /
        # grid_template_columns). Recomputed here so it's correct regardless
        # of which caller populated self.df last (setdf, _render_flattened,
        # or the Edit-mode blank-row splice just above).
        self.update_column_width()

        rows, flags = [], []
        for i in range(n_rows):
            row = self.df.iloc[i]
            is_header = (str(row.get('item', '')) == 'recipe')
            is_blank  = (str(row.get('ingredient', '')).strip() == '')

            cells = []
            for col in cols:
                val = self._fast_format_value(row[col])

                if col == 'item':
                    cells.append({'v': 'recipe for:' if is_header else '',
                                  'e': False, 'k': 'l'})
                    continue

                # View-mode rescale input on the header quantity cell
                if is_header and col == 'quantity' and self.scale_qty_editable:
                    cells.append({'v': val, 'e': True, 'k': 's'})
                    continue

                # editability: same rules as create_row
                editable = edit_mode and (col in self.enabled_columns)
                if col == 'conversion':
                    if is_header:
                        editable = edit_mode and ('conversion' in self.enabled_columns)
                    else:
                        editable = False   # ingredient conversions live in the Guide
                if is_header and col == 'ingredient':
                    editable = False       # recipe name isn't edited here

                kind = 'i' if (col == 'ingredient' and editable) else \
                       ('t' if editable else 'l')
                cell = {'v': val, 'e': bool(editable), 'k': kind}
                if (col == 'conversion' and editable
                        and row.get('ingredient', '') in conv_errors):
                    cell['inv'] = True     # pre-existing missing-conversion flag
                cells.append(cell)
            rows.append(cells)

            if is_header:
                flags.append({'header': True})
            else:
                can = bool(self.cc.can_lookup(row['ingredient'])) if not is_blank else False
                flags.append({
                    'header': False,
                    'lookup': can,
                    'view_below': can,
                    'below_open': (self.child_widget is not None
                                   and self.child_ingredient == row['ingredient']),
                    'add_row': edit_mode and i == n_rows - 1,
                })

        if self._fast_grid is None:
            self._fast_grid = RecipeGridWidget()
            self._fast_grid.on_msg(self._on_fast_grid_msg)
            self._fast_grid.has_clipboard = (DataFrameWidget._clipboard is not None)
            self._fast_grid.observe(self._on_selection_changed, names='selected_rows')
            if self not in DataFrameWidget._open_grids:
                DataFrameWidget._open_grids.append(self)

            # When this is the "view selected below" panel (_selection_controls
            # set by _selection_view_below), the Create/Replace controls belong
            # right after the recipe title, as part of the same card -- not a
            # separate bordered frame above it. The grid's own built-in title
            # bar is suppressed below (g.title = '') and replaced by this HTML
            # label, so title + controls + grid all read as one panel. Reuses
            # .rgw-title from recipe_grid_widget.py's stylesheet, which is
            # already on the page by the time any child grid exists.
            box_children = []
            if self._selection_controls is not None:
                box_children.append(widgets.HTML(
                    value=f"<div class='rgw-title'>{self.last_lookup}</div>"
                ))
                box_children.append(self._selection_controls)
            box_children += [self._fast_grid, self.child_output]
            self._fast_box = widgets.VBox(
                box_children,
                layout=widgets.Layout(border='1px solid #ccc',
                                      border_radius='3px',
                                      padding='2px 4px', margin='2px 0'),
            )

        g = self._fast_grid
        opts = sorted(self.all_ingredients)
        recipe_changed = (self._fast_last_recipe != self.last_lookup)
        with g.hold_trait_notifications():   # one message batch, one repaint
            g.columns    = cols
            g.rows       = rows
            g.row_flags  = flags
            # Suppress the grid's built-in title bar when the Python-rendered
            # title + selection controls above already show it.
            g.title      = '' if self._selection_controls is not None else self.last_lookup
            g.mode       = self.widget_mode
            # An <input>'s own padding + border (see .rgw input in _css)
            # eats into its text area in a way the label-based width
            # estimate above never accounted for — invisible on a short
            # value, but compounding into a few clipped characters on a
            # long one (ingredient names being the usual worst case). Only
            # columns that actually render as an input in this mode need
            # the extra room; label-only cells (all of View mode, and
            # non-enabled columns in Edit mode) are already sized correctly.
            INPUT_CHROME_PX = 32
            g.col_widths = {
                c: max(40, int(w * 0.72) + (INPUT_CHROME_PX if edit_mode and c in self.enabled_columns else 0))
                for c, w in self.column_width.items()
            }
            if recipe_changed:
                g.selected_rows = []
                self._fast_last_recipe = self.last_lookup
            if opts != self._fast_ingredient_opts:   # ship datalist only on change
                g.ingredients = opts
                self._fast_ingredient_opts = opts
            if edit_mode and self._focus_ingredient_input:
                self._focus_ingredient_input = False
                g.focus_seq = g.focus_seq + 1

        if not self._fast_displayed:
            with self.output:
                self.output.clear_output(wait=True)
                display(self._fast_box)
            self._fast_displayed = True

        # Mirror the tail of the classic update_display.
        if self.trigger is not None:
            self.trigger(self.df.iloc[0]['ingredient'])
        if self.parent_refresh is not None:
            self.parent_refresh()

    def _on_fast_grid_msg(self, widget, content, buffers):
        '''Route browser events into the existing handlers.'''
        msg_type = content.get('type')

        if msg_type == 'edit':
            index  = int(content['row'])
            column = str(content['col'])
            shim = _FastCellShim()
            try:
                self._apply_cell_edit(index, column,
                                      str(content.get('new', '')), shim)
            except Exception as exc:
                print(f'[fast grid] edit failed ({column}): {exc}')
                return
            if shim.invalid:
                widget.send({'type': 'cell_invalid', 'row': index, 'col': column})

        elif msg_type == 'lookup':
            # Same logic as on_lookup_click for recipe rows.
            row = self.df.iloc[int(content['row'])]
            if str(row.get('item', '')) == 'recipe':
                return
            target = row['ingredient']
            if self.root_trigger is not None:
                self.root_trigger(target)
            elif self.trigger is not None:
                self._pending_lookup_quantity = row.get('quantity', None)
                self.trigger(target)

        elif msg_type == 'view_below':
            b = _FastCellShim()     # on_view_below_click only needs .tag
            b.tag = int(content['row'])
            try:
                self.on_view_below_click(b)
            except Exception as exc:
                print(f'[fast view] view below failed: {exc}')

        elif msg_type == 'scale':
            cb = getattr(self, 'scale_quantity_callback', None)
            if cb is None:
                return
            shim = _FastCellShim()
            cb(str(content.get('value', '')), shim)
            if shim.invalid:
                widget.send({'type': 'scale_invalid'})

        elif msg_type == 'mode':
            self.set_widget_mode(content['value'])
            
        elif msg_type == 'selection_action':
            sel = sorted(set(self._fast_grid.selected_rows or []))
            if not sel:
                return
            action = content.get('action')

            read_only_actions = {'copy', 'view_below', 'label'}
            if self.widget_mode != 'Edit' and action not in read_only_actions:
                return   # View/Flatten: only Copy and View-selected-below are allowed

            if action == 'copy':
                self._selection_copy_cut(sel, cut=False)
            elif action == 'cut':
                self._selection_copy_cut(sel, cut=True)
            elif action == 'paste':
                self._selection_paste(sel[0])   # paste goes in above the first selected row
            elif action == 'view_below':
                self._selection_view_below(sel)
            elif action == 'label':
                self._selection_label(sel)
        
    def _update_display_fast_guide(self):
        '''Render self.df (a 'guide' price-entry list) into a single-model
        fast grid — the guide-display equivalent of _update_display_fast.

        First call displays a persistent VBox [delete-confirm banner, grid,
        child_output] into self.output; every later call is pure trait
        updates on the live widget — no clear_output, no rebuild, no
        flicker. Unlike the recipe grid there's no header row, add-row, or
        selection system — every row is a peer price entry with its own
        Dup/Delete buttons, gated on widget_mode exactly the way create_row
        gates them (buttons hidden whenever widget_mode == 'View').

        Column widths aren't computed here — GuideGridWidget measures them
        client-side from the actual cell text it's about to render, which
        can't drift out of sync with what's on screen the way a
        separately-computed pixel estimate can.

        self.df is already the full price history sorted newest-first (see
        setdf's guide branch / CostCalculator.guide_display_frame) — rows
        currently selected by cost_picker for cost calculation are flagged
        via _guide_row_used_map and highlighted by the grid.
        '''
        edit_mode = (self.widget_mode == 'Edit')
        cols = list(self.df.columns)

        # Display-only column tweaks: nickname is redundant (it's already
        # the title-bar heading above the grid) and description reads
        # better as the leftmost column. self.df itself is untouched, so
        # this has no effect on editing, cost calc, or the classic grid.
        # The internal-only columns are stripped by setdf already -- excluded
        # again here too, so the grid can never show them even if self.df
        # ever ends up holding them for some other reason.
        internal_cols = ('mycost', 'myconversion', '_guide_index', '_cost_used')
        cols = [c for c in cols if c not in internal_cols]
        if 'nickname' in cols:
            cols.remove('nickname')
        if 'description' in cols:
            cols.remove('description')
            cols.insert(0, 'description')

        n_rows = len(self.df)
        conv_errors = getattr(self.cc, 'conversion_errors', set())

        rows = []
        row_used = []
        for i in range(n_rows):
            row = self.df.iloc[i]
            cells = []
            for col in cols:
                val = self._fast_format_value(row[col])
                # editability: same rule as create_row's is_disabled check
                # for df_type == 'guide' (no per-column overrides there).
                editable = edit_mode and (col in self.enabled_columns)
                cell = {'v': val, 'e': bool(editable), 'k': 't' if editable else 'l'}
                if (col == 'conversion' and editable
                        and row.get('nickname', '') in conv_errors):
                    cell['inv'] = True     # pre-existing missing-conversion flag
                cells.append(cell)
            rows.append(cells)
            row_used.append(bool(self._guide_row_used_map.get(i, False)))

        if self._fast_guide_grid is None:
            self._fast_guide_grid = GuideGridWidget()
            self._fast_guide_grid.on_msg(self._on_fast_guide_grid_msg)

            self._fast_guide_box = widgets.VBox(
                [self._delete_confirm_row, self._fast_guide_grid, self.child_output],
                layout=widgets.Layout(border='1px solid #ccc',
                                      border_radius='3px',
                                      padding='2px 4px', margin='2px 0'),
            )

        g = self._fast_guide_grid
        with g.hold_trait_notifications():   # one message batch, one repaint
            g.columns   = cols
            g.rows      = rows
            g.row_used  = row_used
            g.title     = self.last_lookup
            g.mode      = self.widget_mode

        if not self._fast_guide_displayed:
            with self.output:
                self.output.clear_output(wait=True)
                display(self._fast_guide_box)

    def _on_fast_guide_grid_msg(self, widget, content, buffers):
        '''Route browser events from the guide fast grid into the existing
        handlers — on_duplicate_click / on_delete_click / _apply_cell_edit /
        set_widget_mode — exactly as _on_fast_grid_msg does for the recipe
        grid. duplicate/delete only need button.tag (the row index), so the
        same _FastCellShim used for recipe edits stands in for the button.'''
        msg_type = content.get('type')

        if msg_type == 'edit':
            index  = int(content['row'])
            column = str(content['col'])
            shim = _FastCellShim()
            try:
                self._apply_cell_edit(index, column,
                                      str(content.get('new', '')), shim)
            except Exception as exc:
                print(f'[fast guide grid] edit failed ({column}): {exc}')
                return
            if shim.invalid:
                widget.send({'type': 'cell_invalid', 'row': index, 'col': column})

        elif msg_type == 'duplicate':
            shim = _FastCellShim()
            shim.tag = int(content['row'])
            try:
                self.on_duplicate_click(shim)
            except Exception as exc:
                print(f'[fast guide grid] duplicate failed: {exc}')

        elif msg_type == 'delete':
            shim = _FastCellShim()
            shim.tag = int(content['row'])
            try:
                self.on_delete_click(shim)
            except Exception as exc:
                print(f'[fast guide grid] delete failed: {exc}')

        elif msg_type == 'mode':
            self.set_widget_mode(content['value'])
            
    # ── Selection actions (cut / copy / paste / view selected) ──

    def _on_selection_changed(self, change):
        '''Fires whenever THIS widget's grid selection changes (from a tap/
        drag in the browser, or from Python clearing it after an action).

        Keeps only one recipe's selection "live" at a time across every
        currently open grid (this widget plus any nested "view below"
        parents/children) — selecting here clears everyone else's.
        '''
        if change['new']:
            for w in DataFrameWidget._open_grids:
                if w is not self and w._fast_grid is not None and w._fast_grid.selected_rows:
                    w._fast_grid.selected_rows = []

    def _selected_ingredient_names(self, rows):
        '''Ingredient names for the given (possibly non-contiguous) display-row
        indices, skipping the header row (0) and any not-yet-committed blank row.'''
        names = []
        for i in rows:
            if i == 0 or i >= len(self.df):
                continue
            name = str(self.df.iloc[i]['ingredient']).strip()
            if name:
                names.append(name)
        return names

    def _selection_copy_cut(self, rows, cut):
        recipename = self.df.iloc[0]['ingredient']
        names = self._selected_ingredient_names(rows)
        if not names:
            return

        # Snapshot from self.df — what's actually on screen — rather than
        # cc.costdf, for the quantity only: in View mode with an active
        # scale_factor, self.df's quantity is scaled to the recipe's current
        # yield (see _apply_scaling), and Copy/Cut should carry that scaled
        # amount, not the raw, unscaled costdf value. The *displayed* string
        # is rounded for readability though, so prefer the full-precision
        # value _apply_scaling cached on the side when there is one. Menu
        # price/note still come from cc.costdf since self.df may not even
        # include those columns (hide_columns commonly hides both).
        snapshot = []
        for i in rows:
            if i == 0 or i >= len(self.df):
                continue
            disp_row = self.df.iloc[i]
            name = str(disp_row.get('ingredient', '')).strip()
            if not name:
                continue
            r = self.cc.get_item_ingredient(recipename, name)
            r = r.iloc[0] if not r.empty else {}
            quantity = self._scaled_quantity_full.get(i, disp_row.get('quantity', ''))
            snapshot.append({
                'ingredient': name,
                'quantity': quantity,
                'menu price': r.get('menu price', ''),
                'note': r.get('note', ''),
            })
        if not snapshot:
            return

        DataFrameWidget._clipboard = {
            'op': 'cut' if cut else 'copy',
            'recipe': recipename,
            'rows': snapshot,
        }

        if cut:
            for name in names:
                self.cc.removeIngredient(recipename, name)
            self._notify_recipe_changed(recipename)
            self.cc.clear_cost(recipename)
            self.cc.recipe_cost(recipename)

        if self._fast_grid is not None:
            self._fast_grid.selected_rows = []
        for w in DataFrameWidget._open_grids:
            if w._fast_grid is not None:
                w._fast_grid.has_clipboard = True

        self.setdf(recipename)
        self.update_display()

    def _selection_paste(self, before_row_index):
        clip = DataFrameWidget._clipboard
        if not clip or not clip['rows']:
            return

        recipename = self.df.iloc[0]['ingredient']
        anchor = None
        if 0 < before_row_index < len(self.df):
            anchor = str(self.df.iloc[before_row_index]['ingredient']).strip() or None

        for r in clip['rows']:
            name = r['ingredient']
            # Pasting a cut/copied row back where an identically-named row
            # already exists in THIS recipe would collide — skip it rather
            # than silently overwrite or error.
            if not self.cc.get_item_ingredient(recipename, name).empty:
                print(f'[paste] "{name}" is already in this recipe — skipped')
                continue
            self.cc.insert_ingredient(recipename, name, r.get('quantity', ''), before=anchor)
            self._notify_recipe_changed(recipename)
            if r.get('menu price', '') not in ('', None):
                self.cc.set_item_ingredient(recipename, name, 'menu price', r['menu price'])
            if r.get('note', '') not in ('', None):
                self.cc.set_item_ingredient(recipename, name, 'note', r['note'])

        # A cut clipboard is single-use; a copy clipboard can be pasted
        # again (into this recipe or another).
        if clip['op'] == 'cut':
            DataFrameWidget._clipboard = None
            for w in DataFrameWidget._open_grids:
                if w._fast_grid is not None:
                    w._fast_grid.has_clipboard = False

        self.cc.clear_cost(recipename)
        self.cc.recipe_cost(recipename)
        self.setdf(recipename)
        self.update_display()

    def _selection_view_below(self, rows):
        names = self._selected_ingredient_names(rows)
        if not names:
            return
        recipename = self.df.iloc[0]['ingredient']
        self.close_child()   # replace whatever was previously shown below, if anything

        selected_rows = self.df.iloc[rows].copy()
        selected_rows = selected_rows.loc[selected_rows['ingredient'].astype(str).str.strip() != '']

        total_cost = 0.0
        if 'cost' in selected_rows.columns:
            try:
                total_cost = selected_rows['cost'].apply(lambda x: float(x) if pd.notna(x) and str(x) != '' else 0.0).sum()
            except (TypeError, ValueError):
                pass

        header = {col: '' for col in selected_rows.columns}
        header.update({'item': 'recipe', 'ingredient': f'{recipename} (selection)',
                       'quantity': '', 'cost': total_cost})
        display_df = pd.concat([pd.DataFrame([header]), selected_rows], ignore_index=True)
        display_df['item'] = f'{recipename} (selection)'
        display_df = display_df.reset_index(drop=True)

        child = DataFrameWidget(
            pd.DataFrame(), width=self.width, enabled_columns=[],
            all_enabled_columns=list(self.all_enabled_columns),
            hide_columns=(list(self.hide_columns) if isinstance(self.hide_columns, (list, set)) else self.hide_columns),
            cc=self.cc, output=self.child_output, trigger=None, widget_mode='View',
        )
        child.equ_quant_unit = self.equ_quant_unit
        child.equ_quant_precision = self.equ_quant_precision
        child.cost_multipliers = list(self.cost_multipliers)
        child.root_trigger = self.root_trigger if self.root_trigger is not None else self.trigger
        child.parent_refresh = self._refresh_self
        child.guide_changed_callback = self.guide_changed_callback

        child.df = display_df
        child.df_type = 'recipe'
        child.last_lookup = header['ingredient']
        child.update_column_width()

        self.child_widget = child
        self.child_ingredient = None   # transient — not tied to any real row's "view below"

        # ── "Create as new recipe" / "Replace selection in original recipe" ──
        # Replaces the old JS-side "Encapsulate" menu item. Both mutate
        # recipename, so they're only offered when the selection came from
        # an Edit-mode grid — View/Flatten selections are read-only, same
        # as the Cut/Paste restriction on the popup menu itself.
        if self.widget_mode == 'Edit':
            name_box    = widgets.Text(placeholder='new recipe name', layout=widgets.Layout(width='200px'))
            qty_box     = widgets.Text(value='1 ct', layout=widgets.Layout(width='80px'))
            status_lbl  = widgets.Label(value='')
            create_btn  = widgets.Button(description='Create as new recipe', button_style='info')
            replace_btn = widgets.Button(description='Replace selection in original recipe', button_style='warning')

            def _read_inputs():
                new_name = name_box.value.strip()
                qty = qty_box.value.strip() or '1 ct'
                if not new_name:
                    status_lbl.value = 'Enter a name for the new recipe first.'
                    return None, None
                return new_name, qty

            def _on_create(b):
                new_name, qty = _read_inputs()
                if new_name is None:
                    return
                try:
                    self.cc.create_recipe_from_rows(recipename, names, new_name,
                                                     batch_quantity=qty, replace_in_source=False)
                except ValueError as exc:
                    status_lbl.value = f'[create] {exc}'
                    return
                if self.guide_changed_callback is not None:
                    self.guide_changed_callback()
                status_lbl.value = f'Created "{new_name}" — original recipe unchanged.'
                name_box.value = ''

            def _on_replace(b):
                new_name, qty = _read_inputs()
                if new_name is None:
                    return
                try:
                    self.cc.create_recipe_from_rows(recipename, names, new_name,
                                                     batch_quantity=qty, replace_in_source=True)
                    self._notify_recipe_changed(recipename)
                except ValueError as exc:
                    status_lbl.value = f'[replace] {exc}'
                    return
                if self.guide_changed_callback is not None:
                    self.guide_changed_callback()
                if self._fast_grid is not None:
                    self._fast_grid.selected_rows = []
                self.close_child()   # this panel's rows were just replaced in the source recipe
                self.setdf(recipename)
                self.update_display()

            create_btn.on_click(_on_create)
            replace_btn.on_click(_on_replace)

            child._selection_controls = widgets.VBox([
                widgets.HBox([name_box, qty_box, create_btn, replace_btn]),
                status_lbl,
            ], layout=widgets.Layout(padding='2px 4px 6px 4px'))

        with self.child_output:
            self.child_output.clear_output()
        child.update_display()

    def _selection_label(self, rows, initial_scope=None):
        '''Open the label maker below the grid, fed with both the current
        selection and the whole recipe (the widget has a scope toggle), so
        "Make label" works for either without a second menu entry. Values
        are pre-formatted with _fast_format_value so the label shows numbers
        exactly the way the grid does. Displays straight into child_output
        with its own Close button — no DataFrameWidget child is created, so
        close_child stays a no-op for it and any later view-below simply
        replaces it.'''
        try:
            from label_maker import LabelMakerWidget
        except Exception as exc:
            print(f'[label] label_maker unavailable: {exc}')
            return
        from datetime import date

        recipename = str(self.df.iloc[0]['ingredient'])
        skip_cols = {'item'}

        def _rows_for(indices):
            out = []
            for i in indices:
                if i == 0 or i >= len(self.df):
                    continue
                r = self.df.iloc[i]
                if str(r.get('ingredient', '')).strip() == '':
                    continue
                out.append({c: self._fast_format_value(r[c])
                            for c in self.df.columns if c not in skip_cols})
            return out

        cols = [c for c in self.df.columns if c not in skip_cols]
        header_row = ({c: self._fast_format_value(self.df.iloc[0][c]) for c in cols}
                          if len(self.df) else {})
        w = LabelMakerWidget()
        # Note: no w.columns assignment here -- LabelMakerWidget's own
        # __init__ already applies the last-saved column choice (or its
        # ['ingredient', 'quantity'] default on first-ever use), and the
        # widget filters that against all_columns for whatever recipe is
        # showing. Setting it here would just override "last used" with
        # a fixed default every time.
        w.title = recipename
        w.date_str = date.today().strftime('%m/%d/%Y')
        w.all_columns = cols
        w.header_row = header_row
        w.rows_all = _rows_for(range(1, len(self.df)))
        w.rows_selection = _rows_for(rows)
        if initial_scope:
            w.initial_scope = initial_scope

        self.close_child()
        close_btn = widgets.Button(description='Close', layout=widgets.Layout(width='80px'))
        box = widgets.VBox([close_btn, w])
        def _on_close(b):
            try:
                w.flush_settings()   # single deferred write -- see label_maker.py
            except Exception:
                pass   # never let a settings-save failure block Close
            self.child_output.clear_output()
        close_btn.on_click(_on_close)
        with self.child_output:
            self.child_output.clear_output(wait=True)
            display(box)
    
    def update_display(self):
        # Fast path: recipe View, Edit, and Flatten modes all render as one
        # anywidget model. (_render_flattened builds self.df/df_type exactly
        # like a normal recipe display before calling this, so no special
        # casing is needed here beyond including 'Flatten' in the mode set.)
        if (self.use_fast_view and RecipeGridWidget is not None
                and self.widget_mode in ('View', 'Edit', 'Flatten') and self.df_type == 'recipe'):
            self._fast_guide_displayed = False   # leaving guide fast view, if any
            self._update_display_fast()
            return
        if self.use_fast_view and GuideGridWidget is not None and self.df_type == 'guide':
            self._fast_displayed = False   # leaving recipe fast view, if any
            self._update_display_fast_guide()
            return
        self._fast_displayed = False   # leaving fast view; output gets rebuilt below
        self._fast_guide_displayed = False

        self.progress_bar.layout.visibility = 'visible'

        # Snapshot last render's widgets; they stay alive (and on screen)
        # until the replacement display has been swapped in — closing them
        # earlier blanks the output and makes the rebuild paint piecemeal.
        old_items    = list(getattr(self, '_grid_items', None) or [])
        old_subgrids = list(getattr(self, '_subgrids', None) or [])
        old_grid     = getattr(self, 'grid', None)
        self._grid_items = []
        self._subgrids = []

        self.grid = self._create_grid()
        self.progress_bar.value = 90
        
        rows = [self._delete_confirm_row]

        if self.last_lookup:
            rows.append(widgets.HTML(
                value=f"<div style='font-size:0.8em; color:#888; font-weight:bold; padding:1px 2px;'>{self.last_lookup}</div>"
            ))

        if self.df_type == 'guide':
            mode_dd = self._build_mode_dropdown(('Edit', 'View'), layout=widgets.Layout(width='160px'))
            rows.append(widgets.HBox([widgets.Label(value='Mode:'), mode_dd]))

        # rows.append(self.grid)
        # rows.append(self.child_output)   
        # # child renders its own bordered frame inside here
        if self.child_widget is not None and self.child_ingredient in self._row_names:
            split_pos = self._row_names.index(self.child_ingredient)
            _, split_end = self._row_item_blocks[split_pos]
            top_items = self._grid_items[:split_end]
            bottom_items = self._grid_items[split_end:]

            rows.append(self._make_subgrid(top_items))
            rows.append(self.child_output)   # child renders right after its row
            if bottom_items:
                rows.append(self._make_subgrid(bottom_items))
        else:
            rows.append(self.grid)
            rows.append(self.child_output)

        with self.output:
            self.output.clear_output(wait=True)
            display(widgets.VBox(
                rows,
                layout=widgets.Layout(
                    border='1px solid #ccc',
                    border_radius='3px',
                    padding='2px 4px',
                    margin='2px 0',
                )
            ))
        
        
        if self.df_type == 'recipe' and self.add_ingredient_widget is not None and self._focus_ingredient_input:
            self._focus_ingredient_input = False
            try:
                self.add_ingredient_widget.focus()
            except Exception:
                pass

        self.progress_bar.value = 100
        self.progress_bar.layout.visibility = 'hidden'

        # New display is on screen — now release the previous render's models.
        self._close_render(old_items, old_subgrids, old_grid)

        if (self.trigger != None):
            if (self.df_type == 'recipe'):
                self.trigger(self.df.iloc[0]['ingredient'])
            elif (self.df_type == 'guide'):
                self.trigger(self.df.loc[0]['nickname'])

        if self.parent_refresh is not None:
            self.parent_refresh()
           
           
    def _close_render(self, items, subgrids, grid):
        '''Close the widgets of a superseded render. Called AFTER the new
        display has replaced it, so nothing visible ever disappears early.
        Persistent widgets (progress_bar, backbutton, child_output,
        _delete_confirm_row, the child widget's tree) are never in these
        collections, so they survive.'''
        for item in items:
            for child in getattr(item, 'children', ()):
                try:
                    child.close()
                except Exception:
                    pass
            try:
                item.close()
            except Exception:
                pass
        for g in subgrids:
            try:
                g.close()
            except Exception:
                pass
        if grid is not None:
            try:
                grid.close()
            except Exception:
                pass
            
    def getlayout(self, col=None):
        if col and col in self.column_width:
            return {'width': f"{self.column_width[col]}px", 'padding': '0px 1px'}
        else:
            return {'width': self.width, 'padding': '0px 1px'}
        
    def findtype(self):
        if self.df.empty:
            self.df_type = None
        elif 'ingredient' in self.df.columns:
            if self.df.iloc[0]['item'] == 'recipe':
                self.df_type = 'recipe'                
            else:
                self.df_type = 'mentions'
        elif 'nickname' in self.df.columns:
            self.df_type = 'guide'
        else:
            self.df_type = None
        return self.df_type
        
    
    # Modify _create_grid method to update the progress bar
    def _create_grid(self):
         # Show progress bar
        self.progress_bar.layout.visibility = 'visible'
        self.progress_bar.value = 0

        self._pending_delete = {}
        self.delete_buttons = {}
        
        # Create a list to store the widgets
        items = []
        
        self.num_cols = len(self.df.columns) + 1 # extra one for button
        total_rows = len(self.df)
        
        # Setup column names
        # add blank label in place of a button
        for i in range(self.num_cols - len(self.df.columns)):
            items.append(widgets.Label(value='', layout=self.getlayout()))
        
        # add column labels for each column at top of interface
        for col in self.df.columns:
            items.append(widgets.Label(value=col, layout=self.getlayout(col)))
            
        # Update progress
        self.progress_bar.value = 5
        self.add_ingredient_widget = None   # <-- add this line
        self.ingredient_widgets = []        # <-- add this line
            
        # if we have a recipe df, add row at end for ability to add to ingredient to recipe
        if self.df_type == 'recipe':
            new_row = pd.DataFrame({column: [''] for column in self.df.columns})
            # set blank row up as a member of the recipe
            new_row['item'] = self.df.iloc[0]['ingredient']
            self.df = pd.concat([self.df, new_row], ignore_index=True)

            # If an "insert" was requested, splice a second blank row in
            # immediately above its anchor — purely in self.df; costdf is
            # untouched until a name + quantity are actually typed into it.
            if self._pending_insert is not None:
                anchor_name, direction = self._pending_insert
                anchor_idx = self.df.index[self.df['ingredient'] == anchor_name]
                if len(anchor_idx) > 0:
                    pos = self.df.index.get_loc(anchor_idx[0])
                    if direction == 'after':
                        pos += 1
                    blank = pd.DataFrame({column: [''] for column in self.df.columns})
                    blank['item'] = self.df.iloc[0]['ingredient']
                    if self._pending_insert_name:
                        blank['ingredient'] = self._pending_insert_name
                    self.df = pd.concat([self.df.iloc[:pos], blank, self.df.iloc[pos:]], ignore_index=True)
                else:
                    self._pending_insert = None
                    self._pending_insert_name = None
            
        # Update progress
        self.progress_bar.value = 10

        # Create interface for each row of the DataFrame.
        # Progress updates are throttled to ~8 messages per build instead of
        # one per row — same visual feedback, a fraction of the comm traffic.
        progress_step = max(1, total_rows // 8)
        for index, row in enumerate(self.df.iterrows()):
            self.create_row(items, row[0], row[1])
            if total_rows > 0 and (index % progress_step == 0 or index == total_rows - 1):
                self.progress_bar.value = min(10 + int((index + 1) / total_rows * 80), 90)
        
        # Remember row boundaries + names so update_display can split the grid
        # around whichever row currently has a "view below" child open.
        self._row_item_blocks = []
        block_start = self.num_cols  # header occupies the first block
        for _ in range(len(self.df)):
            self._row_item_blocks.append((block_start, block_start + self.num_cols))
            block_start += self.num_cols

        if self.df_type in ('recipe', 'mentions'):
            self._row_names = list(self.df['ingredient'])
        elif self.df_type == 'guide':
            self._row_names = list(self.df['nickname'])
        else:
            self._row_names = []

        self._grid_items = items
        
        # Create the grid with all items
        grid = widgets.GridBox(items, layout=widgets.Layout(grid_template_columns=f"repeat({self.num_cols}, {self.width})"))
        # set the width of the first column to 100 pixels
        grid.layout.grid_template_columns = f"{self.width} {'px '.join([str(self.column_width[x]) for x in self.df.columns])}px"
        self._grid_template_columns = grid.layout.grid_template_columns
        # Update progress and hide progress bar
        self.progress_bar.value = 100
        self.progress_bar.layout.visibility = 'hidden'
        
        return grid
    
    def _build_mode_dropdown(self, options, layout=None):
        '''Build an Edit/View(/Flatten) dropdown bound to set_widget_mode.'''
        opts = list(options)
        value = self.widget_mode if self.widget_mode in opts else opts[-1]
        dd = widgets.Dropdown(
            options=opts,
            value=value,
            layout=layout or widgets.Layout(width='85px'),
        )
        dd.observe(lambda change: self.set_widget_mode(change['new']), names='value')
        return dd
    
    def create_row(self, items, index, row):
        ''' given a 'row' from a dataframe and the 'index' of the row in the dataframe
            create ui widgets for the row and add the widgets to 'items'
        '''
        # Create a button for each row and associate it with the row index
        # only create lookup button for row with ingredients
        butlist = []
        
        def create_lookup_button():
            button = widgets.Button(description=f'lookup', layout=self.getlayout())
            if not self.cc.can_lookup(row['ingredient']):
                button.disabled = True
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_lookup_click)
            return button
        
        def create_search_button():
            button = widgets.Button(description=f'search', layout=self.getlayout())
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_search_click)
            return button

        def create_duplicate_button():
            button = widgets.Button(
                description='', icon='copy', tooltip='duplicate',
                layout=widgets.Layout(width='36px'), button_style='info',
            )
            button.tag = index
            button.on_click(self.on_duplicate_click)
            return button

        def create_delete_button():
            button = widgets.Button(
                description='', icon='trash', tooltip='delete',
                layout=widgets.Layout(width='36px'), button_style='danger',
            )
            button.tag = index
            button.on_click(self.on_delete_click)
            return button
        
        def create_view_below_button():
            can_view = self.cc.can_lookup(row['ingredient'])
            showing  = (self.child_widget is not None and self.child_ingredient == row['ingredient'])
            button = widgets.Button(
                description='',
                icon=('angle-up' if showing else 'angle-down'),
                tooltip=('hide below' if showing else 'view below'),
                layout=widgets.Layout(width='36px'),
                button_style='warning' if showing else '',
                disabled=not can_view,
            )
            button.tag = index
            button.on_click(self.on_view_below_click)
            return button
        
        # add button based on what type of dataframe we have
        if self.df_type:
            if self.df_type == 'recipe':
                if row['item'] == 'recipe':
                    butlist.append(self._build_mode_dropdown(('Edit', 'View', 'Flatten')))
                else:
                    butlist.append(create_lookup_button())
                    butlist.append(create_view_below_button()) 
            elif self.df_type == 'guide':
                if self.widget_mode != 'View':
                    butlist.append(create_duplicate_button())
                    butlist.append(create_delete_button())
            elif self.df_type == 'mentions':
                butlist.append(create_lookup_button())
                
            if butlist:
                self.buttons[index] = butlist[0]
            items.append(widgets.HBox(butlist))

            
        # Create a Text widget for each cell in the row
        for col in self.df.columns:
            # is_disabled = (col not in self.enabled_columns) or (self.df_type == 'mentions' and col == 'ingredient')
            is_disabled = (col not in self.enabled_columns) or (self.df_type == 'mentions' and col == 'ingredient')

            # Recipe conversion override:
            #   • Header row (item == 'recipe') → editable only in Edit mode,
            #     i.e. when 'conversion' is present in enabled_columns.
            #   • Ingredient rows               → never editable here; use the Guide.
            if col == 'conversion' and self.df_type == 'recipe':
                if row['item'] == 'recipe':
                    is_disabled = 'conversion' not in self.enabled_columns
                else:
                    is_disabled = True
                    
            # View/Flatten scaling override:
            # Make the header-row quantity cell editable so the user can type a
            # new yield and have the recipe rescaled to match.
            if (col == 'quantity' and self.df_type == 'recipe'
                    and row['item'] == 'recipe' and self.scale_qty_editable):
                is_disabled = False
                
            # hide cell visibility
            hide = False
            # Simplifying value assignment and handling for 'myval'
            if str(row[col]) not in [str(np.nan), '']:
                 myval = row[col]
            else:
                myval = ''
                hide = True
            #myval = row[col] if str(row[col]) not in [str(np.nan), ''] else '-'
            myval = f"{myval:0.2f}" if isinstance(myval, float) else myval

            # Widget assignment based on 'item' and 'df_type'
            if col == 'item':
                if myval == 'recipe':
                    cell_widget = widgets.Label(value='recipe for:', layout=self.getlayout(col), style={'font_style': 'italic'})
                elif self.df_type == 'mentions':
                    cell_widget = widgets.Label(value=str(myval), layout=self.getlayout())
                else:
                    cell_widget = widgets.Label()
            else:
                if is_disabled or (col == 'ingredient' and self.df_type == 'recipe' and row['item'] == 'recipe'):
                    cell_widget = widgets.Label(value=str(myval), layout=self.getlayout(col))
                else:
                    if (col == 'ingredient') and (self.df_type == 'recipe'):
                        # Combobox for every editable ingredient cell — blank
                        # (new) or already-filled (existing) — so editing an
                        # existing ingredient gets the same autocomplete /
                        # validity hints as adding a new one.
                        cell_widget = widgets.Combobox(
                            value=str(myval),
                            options=getattr(self, '_ingredient_options', None)
                                    or tuple(self.all_ingredients),
                            ensure_option=False,
                            disabled=is_disabled,
                            continuous_update=False,
                            layout=self.getlayout(col)
                        )
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget, index=index: self._apply_cell_edit(index, col, change['new'], cell_widget), 'value')
                        self.ingredient_widgets.append(cell_widget)   # <-- add this line
                        
                        # The trailing blank row is always last — remember its
                        # ingredient box so we can refocus it after a rebuild
                        if index == len(self.df) - 1:
                            self.add_ingredient_widget = cell_widget
                    else:
                        cell_widget = widgets.Text(
                            value=str(myval), 
                            layout=self.getlayout(col), 
                            disabled=is_disabled, 
                            continuous_update=False
                        )
                        # Highlight conversion cell when a unit conversion is missing
                        if col == 'conversion' and not is_disabled:
                            ingredient_key = row.get('ingredient', row.get('nickname', ''))
                            conv_errors = getattr(self.cc, 'conversion_errors', set())
                            if ingredient_key and ingredient_key in conv_errors:
                                cell_widget.layout.border = '2px solid red'
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget, index=index: self._apply_cell_edit(index, col, change['new'], cell_widget), 'value')


            if (hide and is_disabled):
                cell_widget.layout.visibility = 'hidden'
            items.append(cell_widget)
            
    def _apply_cell_edit(self, index, column, newval, widget):
        '''Apply a committed cell edit (shared by the classic ipywidgets grid
        and the fast anywidget grid).

        index   : row position in self.df
        column  : column name being edited
        newval  : the newly committed value (string as typed)
        widget  : the source widget — a real Text/Combobox, or a _FastCellShim.
                  Handlers flag invalid input via widget.style.text_color /
                  widget.layout.border, exactly as before.

        Extracted verbatim from the on_text_change closure that previously
        lived inside create_row; oldval is still read from self.df (the
        pre-edit display frame), matching the original closure's behavior.
        '''
        def set_df_val(df, row, column, newval):
            df.loc[
                (
                    df['item'] == row['item']
                ) & 
                (
                    df['ingredient'] == row['ingredient']
                ), column] = newval

        def set_df_for_iq(df, row, column, newval):
            '''
                set a value for df, match ingredient, quantity
            '''
            df.loc[
                (
                    df['ingredient'] == row['ingredient']
                ) & 
                (
                    df['quantity'] == row['quantity']
                ), column] = newval
            
        def get_df_val(df, row, column):
            return df.loc[
                (
                    df['item'] == row['item']
                ) & 
                (
                    df['ingredient'] == row['ingredient']
                ), column].values[0]

            
            
        def _update_df(df, row, match_columns, update_column, new_value):
            condition = pd.Series([True] * len(df), index=df.index)
            for col in match_columns:
                val = row[col]
                try:
                    val_is_nan = pd.isna(val)
                except (TypeError, ValueError):
                    val_is_nan = False
                if val_is_nan:
                    condition = condition & df[col].isna()
                else:
                    condition = condition & (df[col] == val)
            df.loc[condition, update_column] = new_value
            if df is self.cc.uni_g:
                self.cc.mark_guide_dirty()
                
        # clear cost of each recipe containing ingredient, then recompute it
        def _clear_costs(nickname):
            self._clear_ingredient_costs(nickname)
            
        def _update_guide_row(index, row, update_column, new_value):
            '''Write one guide cell, targeting the row by its real uni_g index.

            Prefers _guide_row_index_map (the same mechanism on_delete_click
            uses, and for the same reason) over defmatch value-matching:
            defmatch covers nickname/description/size/price/date/supplier, so
            two entries differing only in number, unit, or brand match each
            other and a defmatch write would hit both. Falls back to defmatch
            when no index was recorded for this display row.

            Also guards the dtype: writing a str into a column pandas inferred
            as float64 (an all-NaN brand column, or numeric product numbers
            read from Excel) otherwise trips the incompatible-dtype warning.
            '''
            if isinstance(new_value, str) and update_column in self.cc.uni_g.columns:
                if self.cc.uni_g[update_column].dtype != object:
                    self.cc.uni_g[update_column] = self.cc.uni_g[update_column].astype(object)

            uidx = self._guide_row_index_map.get(index)
            if uidx is not None and uidx in self.cc.uni_g.index:
                self.cc.uni_g.loc[uidx, update_column] = new_value
                self.cc.mark_guide_dirty()
            else:
                _update_df(self.cc.uni_g, row, defmatch, update_column, new_value)

        defmatch = ['nickname', 'description', 'size', 'price', 'date', 'supplier']
        oldval = self.df.iloc[index][column]
            
          
        if column == 'quantity':
            if self.df_type == 'recipe':
                # ── View / Flatten: header-row quantity → scale, don't edit DB ──
                if index == 0 and self.scale_qty_editable and self.scale_quantity_callback is not None:
                    self.scale_quantity_callback(newval, widget)
                    return
                # ── Edit mode: normal DB update follows unchanged ─────────────
                recipename = self.df.iloc[0]['ingredient']
                ingredient_name = self.df.iloc[index]['ingredient']
                if ingredient_name in self.all_ingredients:
                    row = self.df.iloc[index]
                    self.df.loc[index:index, column] = newval

                    # The recipe's own header row (item == 'recipe') always
                    # already exists the moment the recipe is created — only
                    # actual ingredient rows can be "not yet committed".
                    if row['item'] != 'recipe' and self.cc.get_item_ingredient(recipename, ingredient_name).empty:
                        if str(newval).strip() == '':
                            return

                        anchor = self._next_committed_anchor(recipename, index + 1)
                        self.cc.insert_ingredient(recipename, ingredient_name, newval, before=anchor)
                        self._notify_recipe_changed(recipename)
                        self._pending_insert = None
                        self._pending_insert_name = None

                        self.cc.clear_cost(recipename)
                        self.cc.recipe_cost(recipename)
                        self.setdf(recipename)
                        self._focus_ingredient_input = True
                        self.update_display()

                    elif (newval != oldval):
                        updatecost = True
                        set_df_val(self.cc.costdf, row, column, newval)
                        set_df_val(self.cc.costdf, row, 'cost', 0)
                        self.cc.clear_cost(recipename)
                        self.cc.recipe_cost(recipename)
                        self.setdf(recipename)
                        # at the point where a new ingredient is being entered in the blank row
                        self._focus_ingredient_input = True
                        self.update_display()          
          
        elif column == 'ingredient':
            if self.df_type == 'recipe':
                recipename = self.df.iloc[0]['ingredient']
                newval = newval.strip()
                is_committed = not self.cc.get_item_ingredient(recipename, oldval).empty

                # ── Comma-triggered insert ──────────────────────────────
                if is_committed and ',' in newval:
                    before_text, _, after_text = newval.partition(',')
                    before_text = before_text.strip()
                    after_text = after_text.strip()

                    direction = None
                    insert_name = None
                    if before_text == '' and after_text == oldval:
                        direction = 'before'
                    elif after_text == '' and before_text == oldval:
                        direction = 'after'
                    elif after_text == oldval and before_text != '':
                        direction = 'before'
                        insert_name = before_text
                    elif before_text == oldval and after_text != '':
                        direction = 'after'
                        insert_name = after_text

                    if direction is not None:
                        if insert_name is not None and insert_name not in self.all_ingredients:
                            widget.style.text_color = 'red'
                            return

                        self.df.loc[index:index, 'ingredient'] = oldval  # anchor cell unchanged

                        # Reordering shortcut: re-adding the ingredient we
                        # just deleted — restore it instead of starting blank.
                        if (insert_name is not None and self._last_deleted is not None
                                and self._last_deleted.get('recipe') == recipename
                                and insert_name == self._last_deleted['ingredient']):
                            if direction == 'before':
                                anchor = oldval
                            else:
                                ordered = list(self.cc.item_list(recipename)['ingredient'])
                                anchor = None
                                if oldval in ordered:
                                    pos = ordered.index(oldval)
                                    if pos + 1 < len(ordered):
                                        anchor = ordered[pos + 1]
                            self._commit_restored_ingredient(recipename, insert_name, anchor)
                            return

                        self._pending_insert = (oldval, direction)
                        self._pending_insert_name = insert_name
                        self.update_display()
                        return
                    # comma present but pattern didn't match — falls through, will show red

                # check if valid ingredient
                if newval in self.all_ingredients:
                    widget.style.text_color = self.defcolor
                    self.df.loc[index:index, 'item'] = recipename

                    if newval != oldval and newval in self.cc.item_list(recipename)['ingredient'].unique():
                        print('already in recipe')
                        widget.style.text_color = 'red'
                        return

                    if is_committed:
                        if newval != oldval:
                            try:
                                self.cc.replace_ingredient(recipename, oldval, newval)
                                self._notify_recipe_changed(recipename)
                            except ValueError as e:
                                print(e)
                                widget.style.text_color = 'red'
                                return
                            self.cc.clear_cost(recipename)
                            self.cc.recipe_cost(recipename)
                            self.setdf(recipename)
                            self.update_display()
                    else:
                        self.df.loc[index:index, 'ingredient'] = newval

                        # Reordering shortcut for a blank slot (bottom row
                        # or a comma-spliced blank): typed name matches
                        # the ingredient we just deleted — restore it now.
                        if (self._last_deleted is not None
                                and self._last_deleted.get('recipe') == recipename
                                and newval == self._last_deleted['ingredient']):
                            anchor = self._next_committed_anchor(recipename, index + 1)
                            self._commit_restored_ingredient(recipename, newval, anchor)
                            return

                else: # newval not a recognized ingredient
                    if str(newval) == '':
                        if is_committed:
                            deleted_row = self.cc.get_item_ingredient(recipename, oldval)
                            if not deleted_row.empty:
                                r = deleted_row.iloc[0]
                                self._last_deleted = {
                                    'recipe': recipename,
                                    'ingredient': oldval,
                                    'quantity': r.get('quantity', ''),
                                    'menu price': r.get('menu price', ''),
                                    'note': r.get('note', ''),
                                }
                            self.cc.removeIngredient(recipename, oldval)
                            self._notify_recipe_changed(recipename)
                            self.cc.clear_cost(recipename)
                            self.cc.recipe_cost(recipename)
                            self.setdf(recipename)
                            self.update_display()
                        else:
                            self.df.loc[index:index, 'ingredient'] = ''
                    else:
                        widget.style.text_color = 'red'

        elif column == 'menu price':
            # check if valid cost
            try:
                newval = float(newval)
                # check valid value
            
            except:
                print('invalid menu price')
                return

            if self.df_type == 'recipe':
                recipename = self.df.iloc[0]['ingredient']
                # update menu price
                row = self.df.iloc[index]
                #self.cc.costdf.loc[self.costdf['']
                set_df_for_iq(self.cc.costdf, row, 'menu price', newval)
                self.setdf(recipename)
                self.update_display()
                    
        elif column == 'note':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # match nickname, description, size, price, date, supplier
                _update_df(self.cc.uni_g, row, defmatch, 'note', newval)
                self.setdf(row['nickname'])
                self.update_display()

            elif self.df_type == 'recipe':
                recipename = self.df.iloc[0]['ingredient']
                row = self.df.iloc[index]
                set_df_for_iq(self.cc.costdf, row, 'note', newval)
                self.setdf(recipename)
                self.update_display()    

        elif column == 'date':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # match nickname, description, size, date
                mydate = pd.to_datetime(newval, errors='coerce')
                if (mydate is pd.NaT):
                    # don't update if date if the input is invalid
                    self.update_display()
                else:
                    mydate = mydate.strftime('%Y-%m-%d')
                        
                    _update_df(self.cc.uni_g, row, defmatch, 'date', mydate)
                        
                    _clear_costs(row['nickname'])

                    self.setdf(row['nickname'])
                    self.update_display()
                    
        elif column == 'size':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                newval = newval.strip()
                newsize = parse_size(newval)
                if (newval in ['', '-', '0']) or (newsize.m <= 0):
                    # ignore blank size, 0 size
                    self.update_display()
                else:
                    # match nickname, description, size, date
                    _update_df(self.cc.uni_g, row, defmatch, 'size', newval)
                    _clear_costs(row['nickname'])
    
                    self.setdf(row['nickname'])
                    self.update_display()
                    # update mention display?
            
        elif column == 'price':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                try:
                    newval = float(newval)
                except:
                    print('bad new price')
                    return

                # match nickname, description, size, date, and update
                _update_df(self.cc.uni_g, row, defmatch, 'price', newval)
                    
                # clear cost of each recipe containing ingredient
                _clear_costs(row['nickname'])

                self.setdf(row['nickname'])
                self.update_display()
                # update mention display?
                    
        elif column == 'supplier':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # match nickname, description, size, date, and update
                _update_df(self.cc.uni_g, row, defmatch, 'supplier', newval)          
                # clear cost of each recipe containing ingredient
                _clear_costs(row['nickname'])

                self.setdf(row['nickname'])
                self.update_display()
                # update mention display?
                    
        elif column == 'order':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                try:
                    newval = str(newval)
                except:
                    print('bad order value')
                    return

                # match nickname, description, size, date, and update
                _update_df(self.cc.uni_g, row, defmatch, 'order', newval)          
                    
                # clear cost of each recipe containing ingredient
                _clear_costs(row['nickname'])
                    
                self.setdf(row['nickname'])
                self.update_display()
                    
        elif column == 'description':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # match nickname, description, size, date, and update
                _update_df(self.cc.uni_g, row, defmatch, 'description', newval)          
                self.setdf(row['nickname'])
                self.update_display()
                # update mention display?
                    
        elif column == 'number':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # Kept as a string, always: product numbers carry leading
                # zeros and non-digit characters, and order_creator matches
                # options on (supplier, number).
                _update_guide_row(index, row, 'number', str(newval).strip())
                self.setdf(row['nickname'])
                self.update_display()

        elif column == 'unit':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # unit IS priced on: a row whose unit is 'lb' is costed per
                # pound regardless of size (see CostCalculator's pricing and
                # order_guide_reader._rate_for_row), so every recipe using
                # this ingredient needs its cached cost dropped -- unlike
                # description/brand/allergen, which are display-only.
                _update_guide_row(index, row, 'unit', str(newval).strip())
                _clear_costs(row['nickname'])
                self.setdf(row['nickname'])
                self.update_display()

        elif column == 'brand':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                _update_guide_row(index, row, 'brand', str(newval).strip())
                self.setdf(row['nickname'])
                self.update_display()

        elif column == 'allergen':
            if self.df_type == 'guide':
                row = self.df.iloc[index]
                # match nickname, description, supplier
                _update_df(self.cc.uni_g, row, ['nickname', 'description', 'supplier'], 'allergen', newval)          
                self.setdf(row['nickname'])
                self.update_display()
                # update mention display?
                    
        elif column == 'conversion':
            if (self.df_type == 'guide') or (self.df_type == 'recipe'):
                row = self.df.iloc[index]
                newval = newval.strip()
                # check valid conversion
                convrs = parse_conversion(newval)
                if len(convrs) > 0 or newval == '':
                    # Valid (or cleared) — remove any conversion error flag and border
                    ingredient_key = row.get('ingredient', row.get('nickname', ''))
                    conv_errors = getattr(self.cc, 'conversion_errors', set())
                    conv_errors.discard(ingredient_key)
                    widget.layout.border = ''
                    # set convrs
                    if self.df_type == 'recipe':
                        _update_df(self.cc.costdf, row, ['ingredient', 'item', 'quantity'], 'conversion', newval)
                        _clear_costs(row['ingredient'])
                        self.setdf(row['ingredient'])
                    else:
                        _update_df(self.cc.uni_g, row, ['nickname', 'description', 'size', 'supplier'], 'conversion', newval)
                        _clear_costs(row['nickname'])
                        self.setdf(row['nickname'])
                    self.update_display()
                else:
                    # Invalid format typed — show red border immediately as feedback
                    widget.layout.border = '2px solid red'
        

    def on_back_click(self, button):
        '''Navigate to the previous item in the search history.
 
        Restores the scale_factor that was active at that history level so nested
        scaled recipes remain correct at every depth.
 
        Sets self._navigating_back = True so that if DataFrameExplorer subsequently
        fires update_search (e.g. to sync searchinput.value), that handler will
        not overwrite the scale_factor we just restored.
 
        scale_stack layout
        ──────────────────
          index 0  root recipe        → scale None  (always unscaled)
          index 1  first sub-recipe   → scale 0.5   (parent used ½ the yield)
          index 2  second sub-recipe  → scale 0.5   (that sub used ½ of its yield)
 
        Popping one level restores stack[-1], which is exactly the scale that was
        active when the now-current item was first navigated to.
        '''
        self._pending_lookup_quantity = None
 
        if len(self.search_history) > 1:
            # Stash the item we're leaving (and its scale) so Forward can redo it.
            self.forward_stack.append(self.search_history[-1])
            self.forward_scale_stack.append(self.scale_stack[-1] if self.scale_stack else None)

            self.search_history.pop()
            if self.scale_stack:
                self.scale_stack.pop()
 
            # Restore the scale that belongs to the level we are going back to
            self.scale_factor = self.scale_stack[-1] if self.scale_stack else None
 
            # Signal update_search (if it fires) to preserve this scale
            self._navigating_back = True
 
            previous = self.search_history[-1]
            saved_history = self.search_history.copy()
            saved_stack   = self.scale_stack.copy()
 
            self.setdf(previous)          # uses the just-restored scale_factor
            self.search_history = saved_history
            self.scale_stack    = saved_stack
            self.backbutton.disabled = len(self.search_history) <= 1
            self.forwardbutton.disabled = len(self.forward_stack) == 0
            if self.widget_mode == 'Flatten':
                self._render_flattened()
            else:
                self.update_display()
            self._navigating_back = False

    def on_forward_click(self, button):
        '''Redo a navigation previously undone via on_back_click, moving
        forward through history in the direction opposite of Back.

        Mirrors on_back_click: restores the scale_factor that was active when
        the item was originally visited, and reuses the _navigating_back flag
        so DataFrameExplorer.update_search treats this like a Back click --
        preserve the restored scale, don't force out of Flatten mode -- since
        Forward is just history navigation in the other direction.
        '''
        self._pending_lookup_quantity = None

        if self.forward_stack:
            nxt = self.forward_stack.pop()
            nxt_scale = self.forward_scale_stack.pop() if self.forward_scale_stack else None

            self.search_history.append(nxt)
            self.scale_stack.append(nxt_scale)
            self.scale_factor = nxt_scale

            # Signal update_search (if it fires) to preserve this scale
            self._navigating_back = True

            saved_history = self.search_history.copy()
            saved_stack   = self.scale_stack.copy()

            self.setdf(nxt)                # uses the just-restored scale_factor
            self.search_history = saved_history
            self.scale_stack    = saved_stack
            self.backbutton.disabled    = len(self.search_history) <= 1
            self.forwardbutton.disabled = len(self.forward_stack) == 0
            if self.widget_mode == 'Flatten':
                self._render_flattened()
            else:
                self.update_display()
            self._navigating_back = False
                    
    def _clear_ingredient_costs(self, nickname):
        '''Zero and recompute the cost of every recipe line that uses
        `nickname` as an ingredient.

        recipe_cost() is memoized (see FastCostMixin._full_recipe_cost) --
        calling it again after a guide edit/duplicate/delete just returns
        the still-cached value unless clear_cost() has first dropped it from
        the memo. Call this right after mutating uni_g, before setdf/
        update_display, so a stale cost never lingers in self.cc.costdf or
        in a parent recipe widget's display.
        '''
        mdf = self.cc.find_ingredient(nickname)
        # Exclude nickname's own recipe header row (item == 'recipe') --
        # see _apply_cell_edit's identical exclusion for why: it isn't a use
        # of nickname elsewhere, and zeroing it would target a bogus item.
        mdf = mdf.loc[mdf['item'] != 'recipe']
        for i, m in mdf.iterrows():
            self.cc.set_item_ingredient(m['item'], nickname, 'cost', 0)
            self.cc.clear_cost(m['item'])
            self.cc.recipe_cost(m['item'])

    def on_duplicate_click(self, button):
        row = self.df.loc[button.tag]
        newdate = pd.to_datetime('today').strftime('%Y-%m-%d')
        if newdate != row['date']:
            newrow = row.copy()
            newrow['date'] = newdate
            # add only recognized guide columns
            newrow = newrow[self.cc.guide_columns]
            newdf = pd.DataFrame([newrow])
            self.cc.uni_g = pd.concat([self.cc.uni_g, newdf], ignore_index=True)

            self._clear_ingredient_costs(row['nickname'])

            self.setdf(row['nickname'])
            self.update_display()
        else:
            print("Can't duplicate! Dates must be different")
    
    def on_delete_click(self, button):
        """Handle delete button click - remove the specific row from uni_g.

        Uses the real uni_g index recorded for this displayed row (see setdf's
        '_guide_index' handling) instead of matching by column values -- value
        matching breaks down with NaNs, string-vs-float prices, or identical
        rows, all of which get more likely once an ingredient has multiple
        guide entries.

        If this is the LAST guide entry for the ingredient and it's still used
        in one or more recipes, deleting it would fully remove the ingredient
        AND take it out of every recipe that uses it -- so instead of deleting
        immediately, this asks for confirmation via delete_confirm_callback
        (set by DataFrameExplorer). If no callback is registered, it falls
        back to just removing this one price/size entry.
        """
        row_index = button.tag
        row = self.df.loc[row_index]
        nickname = row['nickname']

        original_index = self._guide_row_index_map.get(row_index)
        if original_index is None or original_index not in self.cc.uni_g.index:
            return  # stale reference -- nothing to delete

        remaining = self.cc.uni_g.loc[
            (self.cc.uni_g['nickname'] == nickname) & (self.cc.uni_g.index != original_index)
        ]
        is_last_entry = remaining.empty

        if is_last_entry:
            affected = sorted(set(self.cc.get_parents(nickname)) - {'recipe'})
            if affected and self.delete_confirm_callback is not None:
                self.delete_confirm_callback(nickname, original_index, affected)
                return

        self._remove_guide_row(original_index, nickname)

    def _remove_guide_row(self, original_index, nickname):
        '''Drop a single uni_g row and refresh search caches/display.'''
        self.cc.uni_g = self.cc.uni_g.drop(original_index).reset_index(drop=True)

        if hasattr(self, 'all_ingredients'):
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
            self.all_ingredients = nicks.union(ingrs)

        # Deleting a price entry can change which dates cost_picker selects
        # for the ones that remain -- without this, a parent recipe widget's
        # refresh just re-reads the still-cached (now stale) cost.
        self._clear_ingredient_costs(nickname)

        if self.guide_changed_callback is not None:
            self.guide_changed_callback()

        self.setdf(nickname)
        self.update_display()


    def confirmed_cascade_delete(self, nickname, original_index, affected):
        '''Called by DataFrameExplorer after the user confirms removing the last
        price entry for `nickname` AND its use in every recipe in `affected`.'''
        self.cc.uni_g = self.cc.uni_g.drop(original_index).reset_index(drop=True)

        for item in affected:
            self.cc.removeIngredient(item, nickname)
        for item in affected:
            self.cc.clear_cost(item)
            self.cc.recipe_cost(item)

        if hasattr(self, 'all_ingredients'):
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
            self.all_ingredients = nicks.union(ingrs)
            
        if self.guide_changed_callback is not None:
            self.guide_changed_callback()
        self.clear_display()


    def _on_confirm_delete_ingredient(self, button):
        """User confirmed: remove the last guide entry AND every recipe row using it."""
        pending = self._pending_guide_delete
        self._pending_guide_delete = None
        self._delete_confirm_row.layout.display = 'none'
        if pending is None:
            return

        nickname = pending['nickname']
        for item in set(pending['parents']):
            self.cc.removeIngredient(item, nickname)
            self.cc.clear_cost(item)
            self.cc.recipe_cost(item)

        self._delete_guide_row(pending['uni_g_index'], nickname)


    def _on_cancel_delete_ingredient(self, button):
        self._pending_guide_delete = None
        self._delete_confirm_row.layout.display = 'none'
        self.update_display()

            
    def refresh_ingredient_options(self):
        ''' Push the current set of valid ingredient names into every
            ingredient Combobox currently rendered, so a newly created (or
            removed) ingredient shows up as an autocomplete hint right away
            -- without waiting for the next full grid rebuild.
        '''
        self._ingredient_options = tuple(self.all_ingredients)
        for w in self.ingredient_widgets:
            w.options = self._ingredient_options

        # Keep the fast grid's shared datalist in sync as well.
        if self._fast_grid is not None:
            opts = sorted(self.all_ingredients)
            if opts != self._fast_ingredient_opts:
                self._fast_grid.ingredients = opts
                self._fast_ingredient_opts = opts
            
            
    def on_search_click(self, button):
        # Retrieve the row from the DataFrame using the button's 'tag' attribute
        row = self.df.loc[button.tag]
        
        # load mentions of the ingredient
        if self.df_type == 'recipe':
            self.search_name(row['ingredient'])
        elif self.df_type == 'mentions':
            self.search_name(row['item'])
        elif self.df_type == 'guide':
            self.search_name(row['nickname'])
        self.update_display()

    def on_lookup_click(self, button):
        '''Navigate to the ingredient's own recipe / guide entry.

        Root widgets navigate themselves in place (supporting Back), optionally
        scaling a sub-recipe to the parent quantity (DataFrameExplorer.trigger_update).
        Nested ("view below") child widgets instead jump the top-level display to
        the new ingredient — update_search closes any open nested view when that
        happens, since it no longer relates to the new content.
        '''
        row = self.df.loc[button.tag]

        if self.df_type == 'recipe':
            if row['item'] != 'recipe':
                target = row['ingredient']
            else:
                button.disabled = True
                return
        elif self.df_type == 'mentions':
            target = row['item']
        else:
            button.disabled = True
            return

        if self.root_trigger is not None:
            self.root_trigger(target)
        elif self.trigger is not None:
            self._pending_lookup_quantity = row.get('quantity', None) if self.df_type == 'recipe' else None
            self.trigger(target)

        button.disabled = True

    def _refresh_self(self):
        '''Re-render from current cc state without touching history or scale.
        Mirrors lookup_name's setdf → recipe_cost → setdf sequence: clear_cost's
        ancestor walk zeroes this recipe's cached cost for the edited ingredient
        (and this recipe's own header cost) — setdf alone would just display
        that zero, so we need recipe_cost(self.last_lookup) to recompute it.
        '''
        if not self.last_lookup:
            return
        if self.widget_mode == 'Flatten':
            self.cc.recipe_cost(self.last_lookup)
            self._render_flattened()
            return
        self.setdf(self.last_lookup)
        if self.df_type == 'recipe':
            self.cc.recipe_cost(self.last_lookup)
            self.setdf(self.last_lookup)
        self.update_display()

    def cascade_settings_to_children(self):
        c = self.child_widget
        if c is None:
            return
        c.hide_columns       = (list(self.hide_columns) if isinstance(self.hide_columns, (list, set)) else self.hide_columns)
        c.equ_quant_unit      = self.equ_quant_unit
        c.equ_quant_precision = self.equ_quant_precision
        c.cost_multipliers    = list(self.cost_multipliers)
        if c.last_lookup:
            saved_cb = c.parent_refresh
            c.parent_refresh = None
            if c.widget_mode == 'Flatten':
                c._render_flattened()
            else:
                c.setdf(c.last_lookup)
                if c.df_type == 'recipe':
                    c.cc.recipe_cost(c.last_lookup)
                    c.setdf(c.last_lookup)
                c.update_display()
            c.parent_refresh = saved_cb
        c.cascade_settings_to_children()

    def close_child(self):
        '''Discard any currently-open nested ("view below") child, if any.'''
        if self.child_widget is None:
            return
        if self.child_widget in DataFrameWidget._open_grids:
            DataFrameWidget._open_grids.remove(self.child_widget)
        self.child_widget = None
        self.child_ingredient = None
        with self.child_output:
            self.child_output.clear_output()
            
    def _refresh_keep_mode(self):
        '''Re-render THIS widget's grid without changing widget_mode.

        Flatten's self.df is built by _render_flattened, not by setdf -- so a
        plain setdf/update_display silently swaps the flattened rows for the
        ordinary recipe listing while the mode dropdown still reads "Flatten".
        Any re-render that is not itself a mode change must go through here.
        '''
        if self.widget_mode == 'Flatten':
            self._render_flattened()
        else:
            self.setdf(self.last_lookup)
            self.update_display()

    def on_view_below_click(self, button):
        row = self.df.loc[button.tag]
        ingredient_name = row['ingredient']

        if self.child_widget is not None and self.child_ingredient == ingredient_name:
            self.close_child()
            self._refresh_keep_mode()
            return

        is_subrecipe  = not self.cc.get_recipe_entry(ingredient_name).empty
        default_mode  = 'View' if is_subrecipe else self.widget_mode   # ← the only behavior change

        self.close_child()   # switching rows — replace whatever was previously shown below

        child = DataFrameWidget(
            pd.DataFrame(),
            width=self.width,
            enabled_columns=(list(self.all_enabled_columns) if default_mode == 'Edit' else []),
            all_enabled_columns=list(self.all_enabled_columns),
            hide_columns=(list(self.hide_columns) if isinstance(self.hide_columns, (list, set)) else self.hide_columns),
            cc=self.cc,
            output=self.child_output,
            trigger=None,
            widget_mode=default_mode,
        )
        child.equ_quant_unit          = self.equ_quant_unit
        child.equ_quant_precision     = self.equ_quant_precision
        child.cost_multipliers        = list(self.cost_multipliers)
        child.scale_quantity_callback = child._default_scale_quantity_callback
        # was: child.trigger = self._make_trigger_for(child)
        child.root_trigger = self.root_trigger if self.root_trigger is not None else self.trigger
        child.parent_refresh           = self._refresh_self

        self.child_widget     = child
        self.child_ingredient = ingredient_name

        self._refresh_keep_mode()

        if is_subrecipe:
            # Scale to how much of it THIS recipe uses, not its own default yield —
            # same ratio math as the in-place lookup trigger and the manual
            # scale-quantity callback use.
            try:
                recipe_entry   = self.cc.get_recipe_entry(ingredient_name)
                base_yield_str = str(recipe_entry.squeeze()['quantity'])
                used_qty_str   = str(row['quantity'])
                ry = parse_quant(base_yield_str)
                uq = parse_quant(used_qty_str)
                if ry is not None and uq is not None and ry.m != 0:
                    if uq.dimensionality == ry.dimensionality:
                        child.scale_factor = float((uq / ry).to_reduced_units().m)
                    else:
                        converted = self.cc.do_conversion(ingredient_name, used_qty_str, base_yield_str)
                        if converted is not None:
                            child.scale_factor = float((converted / ry).to_reduced_units().m)
            except Exception:
                pass

        child.lookup_name(ingredient_name)
        if default_mode == 'Flatten':
            child._render_flattened()
        else:
            child.update_display()

    def search_name(self, search):
        self.df = self.cc.find_ingredient(search).reset_index(drop=True)
        # calculate cost for each mention
        for i, row in self.df.iterrows():
            cost = self.cc.item_cost(row['item'], row['ingredient'])
            
        self.df = self.cc.find_ingredient(search).reset_index(drop=True)
        self.df = self.df.loc[self.df['item'] != 'recipe']
        mycolumns = [x for x in self.df.columns if x not in self.hide_columns]
        self.df = self.df[mycolumns]
        self.findtype()
        if self.df_type == 'mentions':
            if self.df.empty:
                return
        else:
            pass
            #print("my type: ", self.df_type)
        self.update_column_width()
        
                
    def lookup_name(self, lookup):
        # Update the DataFrame and the grid
        self.setdf(lookup)
        self.findtype()
        if self.df_type == 'recipe':
            self.cc.recipe_cost(self.df.iloc[0]['ingredient'])
            self.setdf(lookup)
        
        # Mirror scale_factor into scale_stack whenever a new entry is pushed.
        # scale_factor has already been set by DataFrameExplorer.update_search
        # (or left unchanged by on_back_click/on_forward_click) before lookup_name is called.
        if not self.search_history or lookup != self.search_history[-1]:
            self.search_history.append(lookup)
            self.scale_stack.append(self.scale_factor)
            # A fresh navigation invalidates any redo history captured by
            # earlier Back clicks.
            self.forward_stack.clear()
            self.forward_scale_stack.clear()
        
        # Update back/forward button state
        self.backbutton.disabled = len(self.search_history) <= 1
        self.forwardbutton.disabled = len(self.forward_stack) == 0

    def get_widget(self):
        return(self.grid)
    
    def display(self):
        # Display the GridBox
        with self.output:
            self.output.clear_output(wait=True)
            display(self.grid)
        display(self.output)
        
    def clear_display(self):
        '''Clear the grid and lookup state -- used when the previously-displayed
        item no longer exists (e.g. its last guide entry was just deleted).'''
        self.df = pd.DataFrame()
        self.last_lookup = ''
        self.findtype()
        self.update_display()


class DisplayDataFrameWidget(DataFrameWidget):
    def on_lookup_click(self, button):
        # Retrieve the row from the DataFrame using the button's 'tag' attribute
        row = self.df.loc[button.tag]
        # if a trigger was set
        if (self.trigger != None):
            if (self.df_type == 'recipe'):
                 if row['item'] != 'recipe':
                    self.trigger(row['ingredient'])

            elif self.df_type == 'mentions':
                self.trigger(row['item'])
            elif (self.df_type == 'guide'):
                self.trigger(row['nickname'])

        button.disabled = True
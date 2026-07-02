import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display, clear_output
from costcalulator import CostCalculator
from utils import *

class DataFrameWidget:
    ''' ipywidgets based interactive interface for pandas
    '''
    
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
        self.equ_quant_precision = None
        self.equ_quant_unit = None              # target unit for "equ quant" column
        self.scale_factor = None                # current display scale ratio (float|None)
        self._pending_lookup_quantity = None    # set by on_lookup_click before trigger fires
        self._navigating_back = False           # True while on_back_click is executing;
                                                # tells update_search not to clear scale
        self._pending_insert = None        # (anchor_ingredient, 'before'|'after') awaiting a mid-list slot
        self._pending_insert_name = None   # ingredient name to pre-fill that slot with, or None for a blank slot # row index -> delete Button widget, for direct enable/disable
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
        self.backbutton = widgets.Button(description='Back', disabled=True)
        self.backbutton.on_click(self.on_back_click) 
        self.cost_multipliers = [3.0]
        self.widget_mode = widget_mode                       # 'Edit' | 'View' | 'Flatten' — owned by THIS widget
        self.scale_qty_editable = (widget_mode != 'Edit')
        self.mode_changed_callback = None   
        self.scale_quantity_callback = None  # set by DataFrameExplorer
        self.delete_confirm_callback = None  # set by DataFrameExplorer
        self.guide_changed_callback = None   # set by DataFrameExplorer; called whenever uni_g membership changes
        
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
        mydf = self.cc.findframe(
            mylookup,
            equ_quant_unit=self.equ_quant_unit,
            equ_quant_precision=self.equ_quant_precision
        ).reset_index(drop=True).copy()
        self.df = mydf
        self.findtype()
        if (self.df_type == 'recipe'):
            colorder = ['item', 'ingredient', 'quantity', 'cost', 'equ quant']
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
                mycolumns = [x for x in mydf.columns if x not in ['myconversion', 'mycost', '_guide_index']]
            else:
                mycolumns = [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            self.df = mydf
            self.update_column_width()
            
            
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
          - quantity    : pint-aware string  ("1 cup"     → "0.5000 cup")
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
                    mydf.at[idx, 'quantity'] = f"{(q * scale):~.2f}"
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
    
    # def _render_flattened(self):
    #     item = self.last_lookup
    #     if not item:
    #         return
    #     recipe_entry = self.cc.get_recipe_entry(item)
    #     if recipe_entry.empty:
    #         with self.output:
    #             self.output.clear_output(wait=True)
    #             print(f'"{item}" is not a recipe — nothing to flatten.')
    #         return

        recipe_yield_str = str(recipe_entry.squeeze()['quantity']).strip()
        scale = self.scale_factor
        if scale is not None:
            try:
                quant_str = f"{(parse_quant(recipe_yield_str) * scale):~.2f}"
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
            return

        if flat_df is None or flat_df.empty:
            with self.output:
                self.output.clear_output(wait=True)
                print(f'No base ingredients found for "{item}".')
            return

        flat_df = flat_df.copy()

        if scale is not None and abs(scale - 1.0) > 1e-9:
            def _scale_qty(q):
                try:
                    pq = parse_quant(str(q))
                    if pq is not None and hasattr(pq, 'm') and pq.m > 0:
                        return f"{(pq * scale)}"
                except Exception:
                    pass
                return q
            flat_df['quantity'] = flat_df['quantity'].apply(_scale_qty)
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

        flat_df['quantity'] = flat_df.apply(
            lambda row: self._normalize_to_standard_units(row['ingredient'], str(row['quantity'])), axis=1
        )
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

    def _normalize_to_standard_units(self, ingredient, qty_str):
        try:
            q = parse_quant(qty_str)
            if q is None:
                return qty_str
            weight_dim = parse_quant('1 kg').dimensionality
            volume_dim = parse_quant('1 liter').dimensionality
            if q.dimensionality == weight_dim:
                return f'{q.to("g").magnitude:.2f} g'
            result = self.cc.do_conversion(ingredient, qty_str, '1 g')
            if result is not None:
                return f'{result.to("g").magnitude:.2f} g'
            if q.dimensionality == volume_dim:
                return f'{q.to("ml").magnitude:.2f} ml'
            result = self.cc.do_conversion(ingredient, qty_str, '1 ml')
            if result is not None:
                return f'{result.to("ml").magnitude:.2f} ml'
        except Exception:
            pass
        return qty_str
    
    def _make_subgrid(self, items_slice):
                return widgets.GridBox(
                    items_slice,
                    layout=widgets.Layout(grid_template_columns=self._grid_template_columns),
                )
    
    def update_display(self):
        self.progress_bar.layout.visibility = 'visible'
        self.progress_bar.value = 0
        self.grid.disabled = True
        self.progress_bar.value = 20
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

        if (self.trigger != None):
            if (self.df_type == 'recipe'):
                self.trigger(self.df.iloc[0]['ingredient'])
            elif (self.df_type == 'guide'):
                self.trigger(self.df.loc[0]['nickname'])

        if self.parent_refresh is not None:
            self.parent_refresh()
           
    # def update_display(self):
    #     self.progress_bar.layout.visibility = 'visible'
    #     self.progress_bar.value = 0
        
    #     self.grid.disabled = True
    #     self.progress_bar.value = 20
    #     self.grid = self._create_grid()
    #     self.progress_bar.value = 90
        
    #     with self.output:
    #         self.output.clear_output(wait=True)
    #         display(widgets.VBox([self._delete_confirm_row, self.grid, self.child_output])) 
            
    #     # Move the cursor back to the blank "add ingredient" row
    #     if self.df_type == 'recipe' and self.add_ingredient_widget is not None:
    #         try:
    #             self.add_ingredient_widget.focus()
    #         except Exception:
    #             pass
        
    #     self.progress_bar.value = 100
    #     self.progress_bar.layout.visibility = 'hidden'

    #     if (self.trigger != None):
    #         if (self.df_type == 'recipe'):
    #             self.trigger(self.df.iloc[0]['ingredient'])
    #         elif (self.df_type == 'guide'):
    #             self.trigger(self.df.loc[0]['nickname'])
                
    #     if self.parent_refresh is not None:
    #         self.parent_refresh()

            
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

        # Create interface for each row of the DataFrame
        for index, row in enumerate(self.df.iterrows()):
            self.create_row(items, row[0], row[1])
            # Update progress based on how many rows we've processed
            if total_rows > 0:
                progress = 10 + int((index + 1) / total_rows * 80)
                self.progress_bar.value = min(progress, 90)
        
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
        
        # def create_mode_dropdown(options=('Edit', 'View', 'Flatten')):
        #     value = self.widget_mode if self.widget_mode in options else options[-1]
        #     dd = widgets.Dropdown(
        #         options=list(options),
        #         value=value,
        #         layout=widgets.Layout(width='85px'),
        #     )
        #     dd.observe(lambda change: self.set_widget_mode(change['new']), names='value')
        #     return dd
        
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

            
        # Add an observer to the Text widget that enables the button when the content changes
        def on_text_change(change, column, widget):
            
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
                mdf = self.cc.find_ingredient(nickname)
                # Exclude nickname's own recipe header row. It also has
                # ingredient == nickname (that's just how headers are stored),
                # but it isn't a use of nickname elsewhere — treating it as one
                # zeroed the recipe's own cost via item == 'recipe' (not a real
                # recipe name) and could never recompute it back.
                mdf = mdf.loc[mdf['item'] != 'recipe']
                for i, m in mdf.iterrows():
                    self.cc.set_item_ingredient(m['item'], nickname, 'cost', 0)
                    self.cc.clear_cost(m['item'])
                    self.cc.recipe_cost(m['item'])
            
            defmatch = ['nickname', 'description', 'size', 'price', 'date', 'supplier']
            newval = change['new']
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
                            options=tuple(self.all_ingredients),
                            ensure_option=False,
                            disabled=is_disabled,
                            continuous_update=False,
                            layout=self.getlayout(col)
                        )
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget: on_text_change(change, col, cell_widget), 'value')
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
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget: on_text_change(change, col, cell_widget), 'value')


            if (hide and is_disabled):
                cell_widget.layout.visibility = 'hidden'
            items.append(cell_widget)
            
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
            if self.widget_mode == 'Flatten':
                self._render_flattened()
            else:
                self.update_display()
            self._navigating_back = False
                    
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

            # clear cost of each recipe containing ingredient
            mdf = self.cc.find_ingredient(row['nickname'])
            for i,m in mdf.iterrows():
                self.cc.set_item_ingredient(m['item'], row['nickname'], 'cost', 0)
                self.cc.clear_cost(m['item'])

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
        options = tuple(self.all_ingredients)
        for w in self.ingredient_widgets:
            w.options = options
            
            
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

    # def on_lookup_click(self, button):
    #     # Retrieve the row from the DataFrame using the button's 'tag' attribute
    #     row = self.df.loc[button.tag]
            
    #     # Update the DataFrame and the grid
    #     if self.df_type == 'recipe':
    #         if row['item'] != 'recipe':
    #             self.trigger(row['ingredient'])

    #     elif self.df_type == 'mentions':
    #         self.trigger(row['item'])

    #     button.disabled = True
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

    # def _make_trigger_for(self, widget):
    #     '''Build an in-place "lookup" trigger for a widget this widget just
    #     spawned as a child — mirrors DataFrameExplorer.trigger_update's
    #     navigation + view-mode scaling, but operates on `widget` directly
    #     instead of going through the main search box. Flatten mode is an
    #     Explorer-level concept and intentionally isn't replicated for nested
    #     views; they just follow whatever enabled_columns/scale_qty_editable
    #     cascade_settings_to_children gives them.
    #     '''
    #     def _trigger(iname):
    #         # update_display() calls self.trigger(currentname) on every render;
    #         # ignore that no-op case instead of re-navigating to where we already are.
    #         if iname == widget.last_lookup:
    #             return
    #         parent_quantity = widget._pending_lookup_quantity
    #         widget._pending_lookup_quantity = None
    #         scale = None
    #         if parent_quantity is not None and widget.scale_qty_editable:
    #             try:
    #                 recipe_entry = widget.cc.get_recipe_entry(iname)
    #                 if not recipe_entry.empty:
    #                     base_yield_str = str(recipe_entry['quantity'].squeeze())
    #                     pq = parse_quant(parent_quantity)
    #                     ry = parse_quant(base_yield_str)
    #                     if pq.dimensionality == ry.dimensionality:
    #                         scale = float((pq / ry).to_reduced_units().m)
    #             except Exception:
    #                 scale = None
    #         if scale is not None:
    #             widget.scale_factor = scale
    #         elif not widget._navigating_back:
    #             widget.scale_factor = None
    #         widget.lookup_name(iname)
    #         if widget.widget_mode == 'Flatten':
    #             widget._render_flattened()
    #         else:
    #             widget.update_display()
    #     return _trigger

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
        self.child_widget = None
        self.child_ingredient = None
        with self.child_output:
            self.child_output.clear_output()
            
    def on_view_below_click(self, button):
        row = self.df.loc[button.tag]
        ingredient_name = row['ingredient']

        if self.child_widget is not None and self.child_ingredient == ingredient_name:
            self.child_widget = None
            self.child_ingredient = None
            with self.child_output:
                self.child_output.clear_output()
            self.setdf(self.last_lookup)
            self.update_display()
            return

        is_subrecipe  = not self.cc.get_recipe_entry(ingredient_name).empty
        default_mode  = 'View' if is_subrecipe else self.widget_mode   # ← the only behavior change

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

        self.setdf(self.last_lookup)
        self.update_display()

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
        # (or left unchanged by on_back_click) before lookup_name is called.
        if not self.search_history or lookup != self.search_history[-1]:
            self.search_history.append(lookup)
            self.scale_stack.append(self.scale_factor)
        
        # Update back button state
        self.backbutton.disabled = len(self.search_history) <= 1

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
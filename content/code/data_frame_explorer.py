import pandas as pd
import ipywidgets as widgets
import os
from IPython.display import display, clear_output, HTML
from costcalulator import CostCalculator
from utils import *
from data_frame_widget import DataFrameWidget, DisplayDataFrameWidget

class DataFrameExplorer:
    def __init__(self, cc=CostCalculator()):
        self.df = pd.DataFrame()
        self.mentiondf = pd.DataFrame()
        self.allvals = set()

        if 'nickname' in cc.uni_g.columns:
            nicks = set(cc.uni_g['nickname'].dropna().unique())
            ingrs = set(cc.costdf['ingredient'].dropna().unique())
            self.allvals = nicks.union(ingrs)
        self.defcolor = widgets.Text().style.text_color
        self.fontstyle = {'font_size': '12pt'}
        self.excel_filename = 'amc_menu_database.xlsx'
        
        # Store original enabled columns for switching between modes
        self.all_enabled_columns = ['ingredient', 'quantity', 'price', 'menu price', 'size', 'saved cost', 'date', 'supplier', 'description', 'allergen', 'conversion', 'order', 'number']
        self.enabled_columns = self.all_enabled_columns.copy()
        self.hide_columns = ['note', 'conversion', 'saved cost', 'equ quant', 'menu price']
        self.cc = cc
        self.cost_select_method = {'recent': pick_recent_cost, 
                                'maximum': pick_max_cost, 
                                'minimum': pick_min_cost,
                                'all': lambda x: x}
        
        # Track current mode (edit/view)
        self.edit_mode = True
        # Pending scale factor computed in trigger_update, consumed in update_search.
        # Using an intermediate variable avoids a race with the searchinput observer.
        self._scale_pending = None

        # top utility displays
        cost_chooser = widgets.Text(value='menucost.xlsx')
        cost_button = widgets.Button(description='write cost excel')
        cost_button.on_click(lambda x: self.cc.ordered_xlsx(str(cost_chooser.value), cost_multipliers=self.df_widget.cost_multipliers))
        self.cost_display = widgets.HBox([widgets.Label(value='cost export filename'), cost_chooser, cost_button])
            
        database_chooser = widgets.Text(value=self.excel_filename)
        # Colour the filename red on startup when the default file doesn't exist yet
        database_chooser.style.text_color = self.defcolor if os.path.exists(self.excel_filename) else 'red'

        def _on_db_name_change(change):
            """Recolour the text box to show whether the typed filename exists on disk."""
            database_chooser.style.text_color = (
                self.defcolor if os.path.exists(change['new'].strip()) else 'red'
            )
        database_chooser.observe(_on_db_name_change, names='value')

        loadbutton = widgets.Button(description='reload database')
        writebutton = widgets.Button(description='write database')

        # --- inline confirmation / error row (hidden by default) ---
        _confirm_msg = widgets.HTML(value='')
        _confirm_yes = widgets.Button(
            description='✓ Confirm',
            button_style='warning',
            layout=widgets.Layout(width='110px')
        )
        _confirm_no = widgets.Button(
            description='✗ Cancel',
            button_style='danger',
            layout=widgets.Layout(width='90px')
        )
        _confirm_row = widgets.HBox(
            [_confirm_msg, _confirm_yes, _confirm_no],
            layout=widgets.Layout(display='none', align_items='center')
        )

        def _on_write_database(b):
            """Write the current in-memory database to the named file.

            • File EXISTS  → overwrite immediately, no prompt.
            • File MISSING → ask the user to confirm saving the current db
                            under the new name (i.e. a "Save As", not a blank file).
            """
            fname = database_chooser.value.strip()
            _confirm_row.layout.display = 'none'
            if os.path.exists(fname):
                try:
                    self.cc.write_cc(fname)
                except Exception as exc:
                    _confirm_msg.value = (
                        f"<b style='color:red'>⚠ Error writing '{fname}': {exc}</b>"
                    )
                    _confirm_row.layout.display = 'flex'
            else:
                _confirm_msg.value = (
                    f"<b style='color:darkorange'>⚠ '{fname}' does not exist. "
                    f"Save current database with this filename?</b>"
                )
                _confirm_row.layout.display = 'flex'

        def _on_confirm_write(b):
            """User confirmed the Save-As: write current database to the new filename."""
            fname = database_chooser.value.strip()
            try:
                self.cc.write_cc(fname)
                database_chooser.style.text_color = 'black'
                _confirm_row.layout.display = 'none'
            except Exception as exc:
                _confirm_msg.value = (
                    f"<b style='color:red'>⚠ Error writing '{fname}': {exc}</b>"
                )

        def _on_cancel_confirm(b):
            _confirm_row.layout.display = 'none'

        def _reset_to_blank():
            """Replace the current in-memory database with a fresh, empty one.

            costdf must use the *runtime* column layout that read_from_xlsx produces,
            not the on-disk layout stored in cost_columns:
            • 'cost' (on-disk)  is renamed → 'saved cost'  (user-set price)
            •  a new 'cost' column is added for computed/calculated values

            Using the runtime layout means create_recipe / findframe work correctly
            on the blank database, and write_cc can find 'saved cost' when saving.
            """
            blank = CostCalculator()
            # Runtime costdf columns: drop 'cost' from the serialisation schema,
            # then append 'saved cost' and 'cost' in the same order read_from_xlsx uses.
            runtime_cost_cols = (
                [c for c in blank.cost_columns if c != 'cost']
                + ['saved cost', 'cost']
            )
            # Produces: ['item', 'ingredient', 'quantity', 'conversion', 'note',
            #            'menu price', 'saved cost', 'cost']
            blank.costdf = pd.DataFrame(columns=runtime_cost_cols)
            blank.uni_g  = pd.DataFrame(columns=blank.guide_columns)
            # Update the shared cc in-place so df_widget / mdf_widget keep their
            # existing reference to the same object.
            self.cc.__dict__.update(blank.__dict__)
            self.allvals = set()
            self.searchinput.options = ()
            self.df_widget.all_ingredients = self.allvals
            self.menubutton_hbox.children = tuple(self._build_menu_buttons())

        def _on_reload_database(b):
            """Load from file, or create a blank in-memory database when file is missing."""
            fname = database_chooser.value.strip()
            _confirm_row.layout.display = 'none'
            if os.path.exists(fname):
                self.reload_database(fname)
            else:
                _reset_to_blank()
                # Keep text red: the file doesn't exist on disk yet
                database_chooser.style.text_color = 'red'

        loadbutton.on_click(_on_reload_database)
        writebutton.on_click(_on_write_database)
        _confirm_yes.on_click(_on_confirm_write)
        _confirm_no.on_click(_on_cancel_confirm)

        self.database_display = widgets.VBox([
            widgets.HBox([
                widgets.Label(value='Database filename:'),
                database_chooser, loadbutton, writebutton
            ]),
            _confirm_row   # hidden until needed; appears below the toolbar row
        ])

        # add recipe
        addrecipe_text = widgets.Text(value='recipe name')
        addrecipe_button = widgets.Button(description='create recipe')
        addrecipe_button.on_click(lambda x: self.create_recipe(addrecipe_text))
        addrecipe_hbox = widgets.HBox([addrecipe_text, addrecipe_button])
        
        # add ingredient
        addingredient_text = widgets.Text(value='ingredient name')
        addingredient_button = widgets.Button(description='create ingredient')
        addingredient_button.on_click(lambda x: self.create_ingredient(addingredient_text))
        addingredient_hbox = widgets.HBox([addingredient_text, addingredient_button])

        # main display

        # search combobox
        self.searchinput = widgets.Combobox(
            placeholder='ingredient/item',
            options=tuple(self.allvals),
            description='Search:',
            ensure_option=False,
            disabled=False,
            style=self.fontstyle
        )        
        self.searchinput.observe(self.update_search, names='value')

        # copy current display to clipboard
        copybutton = widgets.Button(description=f'copy sheet')
        copybutton.on_click(lambda x: self.df_widget.df.to_clipboard())

        # Three-way mode selector: Edit / View / Flatten
        self._mode_changing = False   # guard against observer re-entry
        self.mode_selector = widgets.Dropdown(
            options=['Edit', 'View', 'Flatten'],
            value='Edit',
            layout=widgets.Layout(width='110px', height='33px')
        )
        self.mode_selector.observe(self.on_mode_change, names='value')
            
        # self.hide_toggleVBox = widgets.HBox(hide_toggles)
        
        hide_toggles = [widgets.Label(value='Show/Hide columns:', layout=widgets.Layout(width='40%'))]
        for col in self.hide_columns:
            if col == 'equ quant':
                continue  # Controlled by the unit text input below, not a checkbox
            hide_quant = widgets.Checkbox(
                value=False,
                description=col,
                disabled=False,
                indent=False
            )
            hide_quant.observe(lambda change, col=col: self.hide_col(change, col), 'value')
            hide_toggles.append(hide_quant)
 
        # ── Equ Quant unit input (replaces the old checkbox) ─────────────────
        # Empty / invalid  →  column hidden
        # Valid pint unit  →  column shown, values converted to that unit
        self.equ_quant_input = widgets.Text(
            value='',
            placeholder='e.g. 1/4 tsp, 0',
            continuous_update=False,
            layout=widgets.Layout(width='120px')
        )
        self.equ_quant_input.observe(self.on_equ_quant_unit_change, names='value')

        hide_toggles.append(
            widgets.Label(
                value='equ quant',
                layout=widgets.Layout(flex='0 0 auto', margin='0 4px 0 12px')
            )
        )
        hide_toggles.append(self.equ_quant_input)


 
        self.hide_toggleVBox = widgets.HBox(hide_toggles)

        # use saved cost check box
        usesaved = widgets.Checkbox(
            value=False,
            description='Use saved cost',
            disabled=False,
            indent=False
        )
        usesaved.observe(self.usesaved, names='value')

        # set cost_picker
        cost_selection_widget = widgets.ToggleButtons(
            options=list(self.cost_select_method.keys()),
            description='Cost selection method:',
            disabled=False,
            button_style='', # 'success', 'info', 'warning', 'danger' or '',
        )
        cost_selection_widget.observe(self.cost_selector, names='value')
        
        # composition
        self.dfdisplay = widgets.Output(layout={ 'overflow': 'scroll', 'border': '1px solid black'})
        self.df_widget = DataFrameWidget(pd.DataFrame(), width='90px', enabled_columns=self.enabled_columns, 
                                        hide_columns=self.hide_columns, cc=self.cc, output=self.dfdisplay, trigger=self.trigger_update)
        
        # Get reference to the back button
        self.backbutton = self.df_widget.backbutton
        self.progress_bar = self.df_widget.progress_bar
        
        # cost multipliers (cost 3.0x, cost 3.5x)
        cost_mult_input = widgets.FloatsInput(
            value=self.df_widget.cost_multipliers,
            format = '.2f'
        )
        cost_mult_input.observe(self.set_cost_multipliers, names='value')
        cost_mult_hbox = widgets.HBox([widgets.Label(value='Cost multipliers: '), cost_mult_input])

        # Add menu buttons
        self.menubutton_hbox = widgets.HBox(
            self._build_menu_buttons(),
            layout=widgets.Layout(width='auto', margin='5px 0')
        )
        
        # Modify top display to include menu buttons and back button
        topdisplay = widgets.VBox([
            self.menubutton_hbox,
            widgets.HBox([self.backbutton, self.searchinput, copybutton, usesaved]), 
            self.dfdisplay
        ], layout={'border': '2px solid green'})
        
        # mentions display
        self.mdfdisplay = widgets.Output(layout={'border': '1px solid black'})        
        self.bottom_label = widgets.Label(value='items containing...', style=self.fontstyle)
        self.mdf_widget = DisplayDataFrameWidget(pd.DataFrame(), width='90px', enabled_columns=[], 
                                        hide_columns=self.hide_columns, cc=self.cc, output=self.mdfdisplay, trigger=self.trigger_mentions)
        bottom_display = widgets.VBox([self.bottom_label, self.mdfdisplay], layout={'border': '2px solid blue'})
        
        # Create tools section containing recipe and ingredient creation
        tools_section = widgets.VBox([
            addrecipe_hbox, 
            addingredient_hbox
        ], layout={'border': '1px solid gray', 'padding': '5px', 'margin': '5px'})
        
        # Track editor widgets for enabling/disabling in view mode
        # We're now only including the recipe/ingredient creation tools and database management tools
        self.editor_widgets = {
            'recipe_tools': tools_section,
            'database_tools': self.database_display,
            'cost_tools': self.cost_display
        }
        
        # display composition
        # combined display
        self.vbox = widgets.VBox([
            self.database_display, 
            self.cost_display, 
            tools_section,  # Now includes both recipe and ingredient creation
            self.hide_toggleVBox, 
            cost_selection_widget, 
            cost_mult_hbox, 
            topdisplay, 
            bottom_display
        ])
   
        
    # def toggle_edit_mode(self, b=None):
    #     '''Toggle between edit mode and view mode.
 
    #     Edit → View : use _activate_view_mode, then reload to render in view.
    #     View → Edit : clear any active scaling so the original (unscaled)
    #                   recipe is shown, then reload to render editable cells.
    #     '''
    #     if self.edit_mode:
    #         # ── Edit → View ──────────────────────────────────────────────────
    #         self._activate_view_mode()      # flips flag, updates UI, no reload
    #         if self.df_widget.last_lookup:
    #             self.df_widget.lookup_name(self.df_widget.last_lookup)
    #             self.df_widget.update_display()
 
    #     else:
    #         # ── View → Edit ──────────────────────────────────────────────────
    #         # Clear scaling: user must see original recipe quantities to edit
    #         self.df_widget.scale_factor = None
    #         self.df_widget.scale_stack = [None] * len(self.df_widget.search_history)
    #         self._scale_pending = None
 
    #         self.edit_mode = True
    #         self.mode_toggle_button.description = 'Edit Mode'
    #         self.mode_toggle_button.button_style = 'warning'
    #         self.enabled_columns = self.all_enabled_columns.copy()
    #         for widget_obj in self.editor_widgets.values():
    #             widget_obj.layout.display = 'flex'
    #         self.df_widget.enabled_columns = self.enabled_columns
 
    #         # Reload the original (unscaled) recipe
    #         if self.df_widget.last_lookup:
    #             self.df_widget.lookup_name(self.df_widget.last_lookup)
    #             self.df_widget.update_display()
    
    def on_mode_change(self, change):
        """Handle the Edit / View / Flatten mode dropdown."""
        if self._mode_changing:
            return

        new_mode = change['new']

        if new_mode == 'Edit':
            # Clear any active scaling so original quantities are editable.
            self.df_widget.scale_factor = None
            self.df_widget.scale_stack  = [None] * len(self.df_widget.search_history)
            self._scale_pending = None
            self.edit_mode = True
            self.enabled_columns = self.all_enabled_columns.copy()
            for w in self.editor_widgets.values():
                w.layout.display = 'flex'
            self.df_widget.enabled_columns = self.enabled_columns
            if self.df_widget.last_lookup:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()

        elif new_mode == 'View':
            self._activate_view_mode()
            if self.df_widget.last_lookup:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()

        elif new_mode == 'Flatten':
            # If coming from Edit, activate view-mode state (no editing,
            # no pre-existing scale to retain).
            if self.edit_mode:
                self._activate_view_mode()
            # If coming from View, scale_factor is preserved automatically.
            self._show_flattened_recipe()


    def _activate_view_mode(self):
        """Switch to View state without triggering a data reload.

        Used from on_mode_change and from trigger_update (auto-switch on
        scaled lookup).  The _mode_changing guard prevents the Dropdown
        observer from firing recursively.
        """
        if not self.edit_mode:
            return   # already in view mode

        self.edit_mode = False

        self._mode_changing = True
        self.mode_selector.value = 'View'
        self._mode_changing = False

        self.enabled_columns = []
        for w in self.editor_widgets.values():
            w.layout.display = 'none'
        self.df_widget.enabled_columns = self.enabled_columns
        # Deliberately no reload — the caller owns navigation.

        
    def _sort_flattened(self, df):
        """Sort flattened ingredients: weight (g) desc → volume (ml) desc → other.

        Assumes quantities have already been normalised by
        _normalize_to_standard_units, so most values end with ' g' or ' ml'.
        Falls back to pint parsing for any unconverted strings.
        """
        def _key(qty_str):
            s = str(qty_str).strip()
            try:
                if s.endswith(' g'):
                    return (0, -float(s[:-2].strip()))
                if s.endswith(' ml'):
                    return (1, -float(s[:-3].strip()))
                # Unconverted — use pint dimensionality
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
        """Convert qty_str to grams (preferred) or ml, falling back to original.

        Conversion priority
        ───────────────────
        1. If already in a weight unit  → convert directly to g.
        2. If already in a volume unit  → convert directly to ml.
        3. Try do_conversion to g using the ingredient's conversion factors.
        4. Try do_conversion to ml using the ingredient's conversion factors.
        5. Return the original string unchanged.
        """
        try:
            q = parse_quant(qty_str)
            if q is None:
                return qty_str

            weight_dim = parse_quant('1 kg').dimensionality
            volume_dim = parse_quant('1 liter').dimensionality

            # Already a weight → g
            if q.dimensionality == weight_dim:
                return f'{q.to("g").magnitude:.2f} g'

            # Always try weight first — even for volume quantities.
            # e.g. "1 cup flour" → "120.00 g" if a g/cup conversion exists.
            result = self.cc.do_conversion(ingredient, qty_str, '1 g')
            if result is not None:
                return f'{result.to("g").magnitude:.2f} g'

            # Weight conversion failed — fall back to ml.
            # Covers volume quantities with no weight conversion factor,
            # and count/other units that have a volume conversion factor.
            if q.dimensionality == volume_dim:
                return f'{q.to("ml").magnitude:.2f} ml'

            result = self.cc.do_conversion(ingredient, qty_str, '1 ml')
            if result is not None:
                return f'{result.to("ml").magnitude:.2f} ml'


        except Exception:
            pass
        return qty_str


    def _show_flattened_recipe(self):
        """Flatten the current recipe and display it through the DataFrameWidget
        grid so it matches the look of View mode exactly.

        Pipeline
        ────────
        1. flatten_recipe  → base ingredients with correctly scaled costs
        2. normalize       → quantities converted to g / ml where possible
        3. sort            → weight desc, volume desc, other
        4. equ quant       → added when a unit is set in the equ quant box
        5. header row      → item='recipe' prepended so findtype() works
        6. cost multipliers→ cost N.Nx columns added as in normal view
        7. render          → df_widget renders with enabled_columns=[] (read-only)
        """
        item = self.df_widget.last_lookup
        if not item:
            return

        recipe_entry = self.cc.get_recipe_entry(item)
        if recipe_entry.empty:
            with self.dfdisplay:
                self.dfdisplay.clear_output(wait=True)
                print(f'"{item}" is not a recipe — nothing to flatten.')
            return

        # ── Determine yield quantity (with optional scale) ────────────────────
        recipe_yield_str = str(recipe_entry.squeeze()['quantity']).strip()
        scale = self.df_widget.scale_factor
        if scale is not None:
            try:
                quant_str = f"{(parse_quant(recipe_yield_str) * scale):~.2f}"
            except Exception:
                quant_str = recipe_yield_str
        else:
            quant_str = recipe_yield_str

        # Ensure ingredient costs are current before flattening
        self.cc.recipe_cost(item)

        # ── Flatten ───────────────────────────────────────────────────────────
        try:
            flat_df = self.cc.flatten_recipe(item, quant_str)
        except Exception as exc:
            with self.dfdisplay:
                self.dfdisplay.clear_output(wait=True)
                print(f'Could not flatten "{item}": {exc}')
            return

        if flat_df is None or flat_df.empty:
            with self.dfdisplay:
                self.dfdisplay.clear_output(wait=True)
                print(f'No base ingredients found for "{item}".')
            return

        flat_df = flat_df.copy()

        # ── Add equ quant BEFORE normalising ──────────────────────────────────
        # add_equ_quant must receive the original quantity strings ("1/8 tsp",
        # "2 cup", …) — not the display-rounded "0.00 ml" that normalisation
        # would produce for very small quantities.
        equ_unit = self.df_widget.equ_quant_unit
        equ_prec = self.df_widget.equ_quant_precision
        if equ_unit:
            flat_df = flat_df.apply(
                lambda row: self.cc.add_equ_quant(row, equ_unit, precision=equ_prec),
                axis=1
            )

        # ── Normalise quantities to g / ml for display ────────────────────────
        flat_df['quantity'] = flat_df.apply(
            lambda row: self._normalize_to_standard_units(
                row['ingredient'], str(row['quantity'])
            ),
            axis=1
        )

        # ── Sort ──────────────────────────────────────────────────────────────
        flat_df = self._sort_flattened(flat_df)

        # ── Build header row (makes findtype() see df_type = 'recipe') ────────
        total_cost = 0.0
        if 'cost' in flat_df.columns:
            try:
                total_cost = flat_df['cost'].apply(
                    lambda x: float(x) if pd.notna(x) else 0.0
                ).sum()
            except (TypeError, ValueError):
                pass

        header = {col: '' for col in flat_df.columns}
        header.update({'item': 'recipe', 'ingredient': item,
                       'quantity': quant_str, 'cost': total_cost})
        if equ_unit and 'equ quant' in flat_df.columns:
            header['equ quant'] = ''

        flat_df['item'] = item   # ingredient rows belong to this recipe
        display_df = pd.concat(
            [pd.DataFrame([header]), flat_df], ignore_index=True
        )

        # ── Select and order columns (mirrors setdf recipe logic) ─────────────
        colorder = ['item', 'ingredient', 'quantity']
        if equ_unit and 'equ quant' in display_df.columns:
            colorder.append('equ quant')
        if 'cost' in display_df.columns:
            colorder.append('cost')
        display_df = reorder_columns(display_df, colorder)

        # Drop hidden columns (but keep equ quant when active)
        hide = set(self.df_widget.hide_columns)
        if equ_unit:
            hide.discard('equ quant')
        else:
            hide.add('equ quant')
        display_df = display_df[[c for c in display_df.columns if c not in hide]]

        # Add cost-multiplier columns (same as setdf)
        if 'cost' in display_df.columns:
            for cm in self.df_widget.cost_multipliers:
                if cm > 0:
                    display_df[f'cost {cm:.1f}x'] = display_df['cost'].apply(
                        lambda x: float(x) * cm
                        if pd.notna(x) and str(x) not in ('', 'nan') else ''
                    )

        display_df = display_df.reset_index(drop=True)

        # ── Render via DataFrameWidget (read-only) ────────────────────────────
        self.df_widget.df             = display_df
        self.df_widget.df_type        = 'recipe'
        self.df_widget.enabled_columns = []       # no editing in flatten mode
        self.df_widget.update_column_width()
        self.df_widget.update_display()


    
    def trigger_mentions(self, iname):
        # reload current search in no iname
        if iname == None:
            iname = self.searchinput.value
        else:
            self.searchinput.value = iname
    
    # def trigger_update(self, iname):
    #     self.searchinput.value = iname
        
    def trigger_update(self, iname):
        '''Handle a lookup navigation request from the DataFrameWidget.
 
        When the request originates from clicking a recipe ingredient's lookup
        button, the widget stores the parent-recipe quantity in
        df_widget._pending_lookup_quantity.  If iname has a sub-recipe, we
        compute a scale factor so the sub-recipe is displayed scaled to the
        portion used in the parent recipe.
 
        Scale pipeline
        ──────────────
        1. on_lookup_click sets df_widget._pending_lookup_quantity
        2. trigger_update reads it, clears it, computes scale → _scale_pending
        3. Changing searchinput.value fires update_search (observer)
        4. update_search reads _scale_pending, sets df_widget.scale_factor,
           then calls lookup_name / update_display
        '''
        
        
        # In flatten mode the display is managed by _show_flattened_recipe.
        if self.mode_selector.value == 'Flatten':
            if self.df_widget._navigating_back:
                # Back button — switch to View and let update_search handle it.
                self._mode_changing = True
                self.mode_selector.value = 'View'
                self._mode_changing = False
                self.searchinput.value = iname
                return
            # Menu buttons and lookup buttons both fall through to the normal
            # navigation path below.  update_search will sync the dropdown to
            # View (for menu buttons); _activate_view_mode handles it for
            # scaled sub-recipe lookups.

        parent_quantity = self.df_widget._pending_lookup_quantity
        self.df_widget._pending_lookup_quantity = None   # consume immediately
        self._scale_pending = None                       # default: no scaling
 
        if parent_quantity is not None:
            scale = self._compute_scale_factor(iname, parent_quantity)
            if scale is not None:
                # Auto-switch to view mode (scaling never applies in edit mode)
                self._activate_view_mode()
                self._scale_pending = scale
 
        self.searchinput.value = iname
        
    # def update_search(self, change):
    #     if change['new'] in self.allvals:
    #         change['owner'].style.text_color = self.defcolor
    #         iname = change['new']

    #         self.df_widget.lookup_name(iname)
    #         self.df_widget.update_display()
    #         self.update_mentions(iname)

    #     else:
    #         change['owner'].style.text_color = 'red'
    
    def update_search(self, change):
        '''Respond to searchinput value changes (user typing or trigger_update).
 
        Scale decision logic
        ────────────────────
        _scale_pending is not None  →  forward navigation via lookup click;
                                        use the freshly computed scale.
        _scale_pending is None AND
          _navigating_back is True   →  called from the back-button chain;
                                        scale_factor was already restored by
                                        on_back_click – don't touch it.
        _scale_pending is None AND
          _navigating_back is False  →  manual search or menu button;
                                        clear scale (show full recipe).
        '''
        if change['new'] in self.allvals:
            change['owner'].style.text_color = self.defcolor
            iname = change['new']
                
            # Read and clear the back-navigation flag before anything else.
            navigating_back = self.df_widget._navigating_back
            self.df_widget._navigating_back = False

            # ── Sync dropdown if leaving Flatten via any non-back navigation ──
            if self.mode_selector.value == 'Flatten' and not navigating_back:
                self._mode_changing = True
                self.mode_selector.value = 'View'
                self._mode_changing = False
 
            if self._scale_pending is not None:
                # Forward scaled navigation
                self.df_widget.scale_factor = self._scale_pending
            elif not navigating_back:
                # Fresh / manual navigation – clear any active scale
                self.df_widget.scale_factor = None
 
            self._scale_pending = None
 
            self.df_widget.lookup_name(iname)
            self.df_widget.update_display()
            self.update_mentions(iname)
 
        else:
            change['owner'].style.text_color = 'red'
            self._scale_pending = None
            self.df_widget._navigating_back = False

    def cost_selector(self, change):
        method = change['new']
        self.cc.cost_picker = self.cost_select_method[method]
        # clear all costs
        self.cc.costdf['cost'] = 0
        self.df_widget.lookup_name(self.df_widget.last_lookup)
        self.df_widget.update_display()

    def set_cost_multipliers(self, change):
        self.df_widget.cost_multipliers = change['new']
        if (self.df_widget.df_type == 'recipe'):
            self.df_widget.lookup_name(self.df_widget.last_lookup)
            self.df_widget.update_display()
        
    def hide_col(self, change, col):
        ''' set a column to hide or not
        '''
        hide = change['new']
        if hide:
            self.hide_columns = set(self.hide_columns) - {col}
        else:
            self.hide_columns = set(self.hide_columns).union({col})
            
        self.df_widget.hide_columns = self.hide_columns
        self.df_widget.lookup_name(self.df_widget.last_lookup)
        self.df_widget.update_display()
        
    def _compute_scale_factor(self, ingredient, parent_quantity):
        '''Return the ratio parent_quantity / recipe_yield, or None on failure.
 
        A returned value of 0.5 means "make half a batch of this sub-recipe".
        The calculation respects ingredient-specific unit conversions via
        CostCalculator.do_conversion (e.g. volume ↔ weight for a known item).
        '''
        recipe_entry = self.cc.get_recipe_entry(ingredient)
        if recipe_entry.empty:
            return None   # ingredient has no sub-recipe – nothing to scale
 
        recipe_yield_str = str(recipe_entry.squeeze()['quantity']).strip()
        if not recipe_yield_str:
            return None
 
        try:
            pq = parse_quant(str(parent_quantity))    # e.g. Q_("1 cup")
            ry = parse_quant(recipe_yield_str)        # e.g. Q_("2 cup")
 
            if pq is None or ry is None or ry.m == 0:
                return None
 
            # Same dimensionality → direct ratio
            if pq.dimensionality == ry.dimensionality:
                return float((pq / ry).to_reduced_units().m)
 
            # Different dimensionality → try ingredient conversion factors
            converted = self.cc.do_conversion(
                ingredient, str(parent_quantity), recipe_yield_str
            )
            if converted is not None:
                return float((converted / ry).to_reduced_units().m)
 
        except Exception as exc:
            print(f'[scale] could not compute scale for "{ingredient}": {exc}')
 
        return None
 
    # def _activate_view_mode(self):
    #     '''Switch to view mode WITHOUT triggering a data reload.
 
    #     Used when auto-switching during a scaled lookup so the reload is
    #     handled only once by update_search, not twice.
    #     '''
    #     if not self.edit_mode:
    #         return   # already in view mode
 
    #     self.edit_mode = False
    #     self.mode_toggle_button.description = 'View Mode'
    #     self.mode_toggle_button.button_style = 'info'
    #     self.enabled_columns = []
    #     for widget_obj in self.editor_widgets.values():
    #         widget_obj.layout.display = 'none'
    #     self.df_widget.enabled_columns = self.enabled_columns
    #     # Deliberately no reload here – the caller owns the navigation.
        
    def on_equ_quant_unit_change(self, change):
        """Parse 'unit[, precision]' and apply equ quant settings.

        Accepted formats
        ────────────────
        "cup"          → convert to cups, default precision (4 dp)
        "g, 0.0"       → convert to grams, 1 decimal place
        "1/8 tsp, 0"   → express as multiples of 1/8 tsp, 0 decimal places
        "2 liter, 0.000" → multiples of 2-litre, 3 decimal places

        The comma separates the pint quantity / unit from the precision
        template.  The number of characters after the decimal point in the
        template determines the decimal places shown (so "0" → 0, "0.0" → 1,
        "0.00" → 2 …).  No comma → precision is left at the default (4).
        """
        raw = change['new'].strip()
        unit_str  = raw
        precision = None   # None → use default (4 dp)
        valid     = False

        if raw:
            # ── Split "unit, precision_template" ─────────────────────────────
            parts = raw.split(',', 1)
            unit_str = parts[0].strip()

            if len(parts) == 2:
                prec_str = parts[1].strip()
                # Count decimal places in the template string
                if '.' in prec_str:
                    precision = len(prec_str.split('.')[1])
                else:
                    precision = 0   # "0" with no dot → 0 decimal places

            # ── Validate the unit/scale part with pint ───────────────────────
            if unit_str:
                try:
                    Q_(unit_str)   # accepts "1/8 tsp", "2 liter", "cup", "g" …
                    valid = True
                except Exception:
                    valid = False

        if valid:
            self.hide_columns = set(self.hide_columns) - {'equ quant'}
            self.df_widget.equ_quant_unit      = unit_str
            self.df_widget.equ_quant_precision = precision
            self.equ_quant_input.style.text_color = self.defcolor
        else:
            self.hide_columns = set(self.hide_columns) | {'equ quant'}
            self.df_widget.equ_quant_unit      = None
            self.df_widget.equ_quant_precision = None
            self.equ_quant_input.style.text_color = 'red' if raw else self.defcolor

        self.df_widget.hide_columns = self.hide_columns
        if self.df_widget.last_lookup:
            if self.mode_selector.value == 'Flatten':
                self._show_flattened_recipe()
            else:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()

    def usesaved(self, change):
        # set cc to use saved cost depending on user checkbox
        
        self.cc.use_saved = change['new']
        
        # recompute all?
        self.cc.costdf['cost'] = 0            
        self.df_widget.lookup_name(self.df_widget.last_lookup)
        self.df_widget.update_display()
        
    # def update_mentions(self, iname):
    #     self.mdf_widget.search_name(iname)
    #     if self.mdf_widget.df.empty:
    #         return
    #     self.mdf_widget.update_display()
    #     self.bottom_label.value = f"items containing {iname}:"
    def update_mentions(self, iname):
        """Update the mentions display for the current ingredient/item"""
        self.mdf_widget.search_name(iname)
        
        if self.mdf_widget.df.empty:
            # Create a message when no mentions are found
            with self.mdfdisplay:
                self.mdfdisplay.clear_output(wait=True)
                print(f"{iname} does not appear in any recipe")
            self.bottom_label.value = f"items containing {iname}:"
        else:
            self.mdf_widget.update_display()
            self.bottom_label.value = f"items containing {iname}:"
    
    def reload_database(self, database):
        self.cc.read_from_xlsx(database)
        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals
        self.menubutton_hbox.children = tuple(self._build_menu_buttons())

    def create_recipe(self, textbox):
        ''' add new recipe to menu
        '''
        # check recipe dne
        rname = textbox.value.strip()
        if self.cc.findframe(rname).empty:
            # add to costdf
            newdf = pd.DataFrame(
                data={'item':['recipe'], 
                      'ingredient':[rname], 
                      'quantity':['1 ct']}
            )
            self.cc.costdf = pd.concat([self.cc.costdf, newdf], ignore_index=True)
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
            self.allvals = nicks.union(ingrs)
            self.searchinput.options = tuple(self.allvals)
            self.df_widget.all_ingredients = self.allvals
        else:
            print(f'recipe/ingredient {rname} already exists')
            
    def _build_menu_buttons(self):
        """Build menu shortcut buttons from the children of 'fullmenu' in costdf.
        Returns a list ready to be used as HBox children (mode toggle and progress
        bar are always appended at the end).
        """
        try:
            menulist = self.cc.get_children('fullmenu')
        except (KeyError, AttributeError):
            menulist = []

        menubuttons = []
        for menu in menulist:
            button = widgets.Button(
                description=menu.capitalize(),
                button_style='primary',
                style={'font_weight': 'bold', 'font_variant': 'small-caps'},
                layout=widgets.Layout(width='auto', height='33px')
            )
            def make_menu_handler(menu_name):
                return lambda b: self.trigger_update(menu_name)
            button.on_click(make_menu_handler(menu))
            menubuttons.append(button)

        menubuttons.append(self.mode_selector)
        menubuttons.append(self.progress_bar)
        return menubuttons
    
    def create_ingredient(self, textbox):
        '''Add new ingredient to unified guide'''
        # Get the ingredient name and strip whitespace
        ing_name = textbox.value.strip()
        
        # Check if ingredient already exists in nickname column
        if not self.cc.uni_g.loc[self.cc.uni_g['nickname'] == ing_name].empty:
            print(f'Ingredient "{ing_name}" already exists in the guide')
            return
            
        # Create a new row for the unified guide
        current_date = pd.to_datetime('today').strftime('%Y-%m-%d')
        new_ingredient = pd.DataFrame(
            data={
                'supplier': [''],
                'description': [f'{ing_name}'],
                'number': [''],
                'price': [0],
                'unit': ['ea'],
                'size': ['1 count'],
                'brand': [''],
                'order': [''],
                'nickname': [ing_name],
                'note': [''],
                'allergen': [''],
                'conversion': [''],
                'date': [current_date]}
        )
        
        # Add the new ingredient to the guide
        self.cc.uni_g = pd.concat([self.cc.uni_g, new_ingredient], ignore_index=True)
        
        # Update the available values for search
        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals
        
        # Inform the user
        print(f'Created new ingredient: {ing_name}')
        
    def display(self):
        display(self.vbox)
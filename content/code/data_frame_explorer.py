import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output
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
        loadbutton = widgets.Button(description=f'reload database')
        loadbutton.on_click(lambda x: self.reload_database(database_chooser.value))
        writebutton = widgets.Button(description='write database')
        writebutton.on_click(lambda x: self.cc.write_cc(f"{database_chooser.value}"))
        self.database_display = widgets.HBox([widgets.Label(value='Database filename:'), database_chooser, loadbutton, writebutton])

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

        # Add edit/view mode toggle button with larger size for better text fit
        self.mode_toggle_button = widgets.Button(
            description='Edit Mode',
            button_style='warning',
            style={'font_weight': 'bold', 'font_variant': 'small-caps'},
            layout=widgets.Layout(width='auto', height='33px')
        )
        self.mode_toggle_button.on_click(self.toggle_edit_mode)

        # hide_toggles = [widgets.Label(value='Show/Hide columns:', layout=widgets.Layout(width='40%'))]
        # for col in self.hide_columns:
        #     # use saved cost check box
        #     hide_quant = widgets.Checkbox(
        #         value=False,
        #         description=col,
        #         disabled=False,
        #         indent=False
        #     )
        #     hide_quant.observe(lambda change, col=col: self.hide_col(change, col), 'value')
        #     hide_toggles.append(hide_quant)
            
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
        hide_toggles.append(
            widgets.Label(value='Equ Quant Unit:', layout=widgets.Layout(margin='0 4px 0 12px'))
        )
        self.equ_quant_input = widgets.Text(
            value='',
            placeholder='e.g. cup, lb, g, oz',
            layout=widgets.Layout(width='130px')
        )
        self.equ_quant_input.observe(self.on_equ_quant_unit_change, names='value')
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
        menulist = ['breakfast', 'lunch', 'dinner', 'desserts']
        menubuttons = []
        for menu in menulist:
            button = widgets.Button(
                description=menu.capitalize(),
                button_style='primary',
                style={'font_weight': 'bold', 'font_variant': 'small-caps'},
                layout=widgets.Layout(width='auto', height='33px')
            )
            # Create a closure to handle button clicks
            def make_menu_handler(menu_name):
                return lambda b: self.trigger_update(menu_name)
            button.on_click(make_menu_handler(menu))
            menubuttons.append(button)
        
        # Add the edit/view mode toggle button to the menu button row
        menubuttons.append(self.mode_toggle_button)
        menubuttons.append(self.progress_bar)
        
        self.menubutton_hbox = widgets.HBox(
            menubuttons, 
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
    #     """Toggle between edit mode and view mode"""
    #     # Toggle the current mode
    #     self.edit_mode = not self.edit_mode
        
    #     if self.edit_mode:
    #         # Switching to edit mode
    #         self.mode_toggle_button.description = 'Edit Mode'
    #         self.mode_toggle_button.button_style = 'warning'
            
    #         # Enable editing
    #         self.enabled_columns = self.all_enabled_columns.copy()
            
    #         # Show editor widgets
    #         for widget in self.editor_widgets.values():
    #             widget.layout.display = 'flex'
                
    #     else:
    #         # Switching to view mode
    #         self.mode_toggle_button.description = 'View Mode'
    #         self.mode_toggle_button.button_style = 'info'
            
    #         # Disable editing
    #         self.enabled_columns = []
            
    #         # Hide editor widgets
    #         for widget in self.editor_widgets.values():
    #             widget.layout.display = 'none'
        
    #     # Update the DataFrameWidget with new enabled_columns
    #     self.df_widget.enabled_columns = self.enabled_columns
        
    #     # Reload the current view to apply the changes
    #     if self.df_widget.last_lookup:
    #         self.df_widget.lookup_name(self.df_widget.last_lookup)
    #         self.df_widget.update_display()
    def toggle_edit_mode(self, b=None):
        '''Toggle between edit mode and view mode.
 
        Edit → View : use _activate_view_mode, then reload to render in view.
        View → Edit : clear any active scaling so the original (unscaled)
                      recipe is shown, then reload to render editable cells.
        '''
        if self.edit_mode:
            # ── Edit → View ──────────────────────────────────────────────────
            self._activate_view_mode()      # flips flag, updates UI, no reload
            if self.df_widget.last_lookup:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()
 
        else:
            # ── View → Edit ──────────────────────────────────────────────────
            # Clear scaling: user must see original recipe quantities to edit
            self.df_widget.scale_factor = None
            self.df_widget.scale_stack = [None] * len(self.df_widget.search_history)
            self._scale_pending = None
 
            self.edit_mode = True
            self.mode_toggle_button.description = 'Edit Mode'
            self.mode_toggle_button.button_style = 'warning'
            self.enabled_columns = self.all_enabled_columns.copy()
            for widget_obj in self.editor_widgets.values():
                widget_obj.layout.display = 'flex'
            self.df_widget.enabled_columns = self.enabled_columns
 
            # Reload the original (unscaled) recipe
            if self.df_widget.last_lookup:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
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
 
    def _activate_view_mode(self):
        '''Switch to view mode WITHOUT triggering a data reload.
 
        Used when auto-switching during a scaled lookup so the reload is
        handled only once by update_search, not twice.
        '''
        if not self.edit_mode:
            return   # already in view mode
 
        self.edit_mode = False
        self.mode_toggle_button.description = 'View Mode'
        self.mode_toggle_button.button_style = 'info'
        self.enabled_columns = []
        for widget_obj in self.editor_widgets.values():
            widget_obj.layout.display = 'none'
        self.df_widget.enabled_columns = self.enabled_columns
        # Deliberately no reload here – the caller owns the navigation.
        
    def on_equ_quant_unit_change(self, change):
        '''Handle changes to the equ quant unit text input.
 
        * Empty input or unrecognised unit → hide "equ quant" column.
        * Valid pint unit                  → show "equ quant" column and
                                             convert all ingredient quantities
                                             to that unit ("n/a" where not
                                             possible).
        Input box turns red for an invalid (non-empty) entry.
        '''
        unit_str = change['new'].strip()
        valid = False
        if unit_str:
            try:
                ureg.Unit(unit_str)   # ureg is imported via `from utils import *`
                valid = True
            except Exception:
                valid = False
 
        if valid:
            self.hide_columns = set(self.hide_columns) - {'equ quant'}
            self.df_widget.equ_quant_unit = unit_str
            self.equ_quant_input.style.text_color = self.defcolor
        else:
            self.hide_columns = set(self.hide_columns).union({'equ quant'})
            self.df_widget.equ_quant_unit = None
            # Red for invalid entry, default colour when simply empty
            self.equ_quant_input.style.text_color = 'red' if unit_str else self.defcolor
 
        self.df_widget.hide_columns = self.hide_columns
        if self.df_widget.last_lookup:
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
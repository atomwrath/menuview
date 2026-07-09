import pandas as pd
import ipywidgets as widgets
import os
import io
import contextlib
from IPython.display import display, clear_output, HTML
from costcalulator import CostCalculator
from utils import *
from data_frame_widget import DataFrameWidget, DisplayDataFrameWidget
from toolbar_widget import ToolbarWidget
from menuview_theme import theme_widget

class _TextBoxShim:
    """Minimal stand-in for an ipywidgets Text box, so create_recipe /
    create_ingredient can be called unmodified with a plain string coming
    from the toolbar's anywidget events instead of a real Text widget."""
    class _Style:
        def __init__(self):
            self.text_color = None
    def __init__(self, value):
        self.value = value
        self.style = _TextBoxShim._Style()


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
        self.all_enabled_columns = ['ingredient', 'quantity', 'price', 'menu price', 'size', 'date', 'supplier', 'description', 'allergen', 'conversion', 'order', 'number', 'note']
        self.enabled_columns = self.all_enabled_columns.copy()
        self.hide_columns = ['note', 'conversion', 'equ quant', 'menu price']
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

        # # top utility displays
        # cost_chooser = widgets.Text(value='menucost.xlsx')
        # cost_button = widgets.Button(description='write cost excel')
        # cost_button.on_click(lambda x: self.cc.ordered_xlsx(str(cost_chooser.value), cost_multipliers=self.df_widget.cost_multipliers))
        # self.cost_display = widgets.HBox([widgets.Label(value='cost export filename'), cost_chooser, cost_button])
            
        # database_chooser = widgets.Text(value=self.excel_filename)
        # # Colour the filename red on startup when the default file doesn't exist yet
        # database_chooser.style.text_color = self.defcolor if os.path.exists(self.excel_filename) else 'red'

        # def _on_db_name_change(change):
        #     """Recolour the text box to show whether the typed filename exists on disk."""
        #     database_chooser.style.text_color = (
        #         self.defcolor if os.path.exists(change['new'].strip()) else 'red'
        #     )
        # database_chooser.observe(_on_db_name_change, names='value')

        # loadbutton = widgets.Button(description='reload database')
        # writebutton = widgets.Button(description='write database')

        # # --- inline confirmation / error row (hidden by default) ---
        # _confirm_msg = widgets.HTML(value='')
        # _confirm_yes = widgets.Button(
        #     description='✓ Confirm',
        #     button_style='warning',
        #     layout=widgets.Layout(width='110px')
        # )
        # _confirm_no = widgets.Button(
        #     description='✗ Cancel',
        #     button_style='danger',
        #     layout=widgets.Layout(width='90px')
        # )
        # _confirm_row = widgets.HBox(
        #     [_confirm_msg, _confirm_yes, _confirm_no],
        #     layout=widgets.Layout(display='none', align_items='center')
        # )

        # def _on_write_database(b):
        #     """Write the current in-memory database to the named file.

        #     • File EXISTS  → overwrite immediately, no prompt.
        #     • File MISSING → ask the user to confirm saving the current db
        #                     under the new name (i.e. a "Save As", not a blank file).
        #     """
        #     fname = database_chooser.value.strip()
        #     _confirm_row.layout.display = 'none'
        #     if os.path.exists(fname):
        #         try:
        #             self.cc.write_cc(fname)
        #         except Exception as exc:
        #             _confirm_msg.value = (
        #                 f"<b style='color:red'>⚠ Error writing '{fname}': {exc}</b>"
        #             )
        #             _confirm_row.layout.display = 'flex'
        #     else:
        #         _confirm_msg.value = (
        #             f"<b style='color:darkorange'>⚠ '{fname}' does not exist. "
        #             f"Save current database with this filename?</b>"
        #         )
        #         _confirm_row.layout.display = 'flex'

        # def _on_confirm_write(b):
        #     """User confirmed the Save-As: write current database to the new filename."""
        #     fname = database_chooser.value.strip()
        #     try:
        #         self.cc.write_cc(fname)
        #         database_chooser.style.text_color = 'black'
        #         _confirm_row.layout.display = 'none'
        #     except Exception as exc:
        #         _confirm_msg.value = (
        #             f"<b style='color:red'>⚠ Error writing '{fname}': {exc}</b>"
        #         )

        # def _on_cancel_confirm(b):
        #     _confirm_row.layout.display = 'none'

        # def _reset_to_blank():
        #     """Replace the current in-memory database with a fresh, empty one."""
        #     blank = CostCalculator()
        #     blank.costdf = pd.DataFrame(columns=blank.cost_columns)
        #     blank.uni_g  = pd.DataFrame(columns=blank.guide_columns)
        #     # Update the shared cc in-place so df_widget / mdf_widget keep their
        #     # existing reference to the same object.
        #     self.cc.__dict__.update(blank.__dict__)
        #     self.allvals = set()
        #     self.searchinput.options = ()
        #     self.df_widget.all_ingredients = self.allvals
        #     self.menubutton_hbox.children = tuple(self._build_menu_buttons())

        # def _on_reload_database(b):
        #     """Load from file, or create a blank in-memory database when file is missing."""
        #     fname = database_chooser.value.strip()
        #     _confirm_row.layout.display = 'none'
        #     if os.path.exists(fname):
        #         self.reload_database(fname)
        #     else:
        #         _reset_to_blank()
        #         # Keep text red: the file doesn't exist on disk yet
        #         database_chooser.style.text_color = 'red'

        # loadbutton.on_click(_on_reload_database)
        # writebutton.on_click(_on_write_database)
        # _confirm_yes.on_click(_on_confirm_write)
        # _confirm_no.on_click(_on_cancel_confirm)

        # self.database_display = widgets.VBox([
        #     widgets.HBox([
        #         widgets.Label(value=''),
        #         database_chooser, loadbutton, writebutton
        #     ]),
        #     _confirm_row   # hidden until needed; appears below the toolbar row
        # ])

        # # add recipe
        # addrecipe_text = widgets.Text(value='', placeholder='recipe name')
        # addrecipe_text.layout = widgets.Layout(flex='1 1 auto', min_width='120px')
        # addrecipe_button = widgets.Button(description='+ recipe')
        # addrecipe_button.on_click(lambda x: self.create_recipe(addrecipe_text))
        # addrecipe_hbox = widgets.HBox([addrecipe_text, addrecipe_button])
        # addrecipe_hbox.add_class('mv-pair')
        
        # # add ingredient
        # addingredient_text = widgets.Text(value='', placeholder='nickname, size, price')
        # addingredient_text.layout = widgets.Layout(flex='1 1 auto', min_width='120px')
        # addingredient_button = widgets.Button(description='+ ingredient')
        # addingredient_button.on_click(lambda x: self.create_ingredient(addingredient_text))
        # addingredient_hbox = widgets.HBox([addingredient_text, addingredient_button])
        # addingredient_hbox.add_class('mv-pair')

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
        
        # rename or duplicate the currently loaded recipe / ingredient (edit mode only)
        self.renamebutton = widgets.Button(description='rename / duplicate', disabled=True)
        self.renamebutton.on_click(self.on_rename_click)

        self.rename_new_name = widgets.Text(value='', description='New name:', style=self.fontstyle)
        self.rename_info_label = widgets.Label(value='')
        self.rename_confirm_button = widgets.Button(description='Confirm rename', button_style='warning')
        self.rename_confirm_button.on_click(self.on_rename_confirm)
        self.duplicate_button = widgets.Button(description='Duplicate as new recipe', button_style='info')
        self.duplicate_button.on_click(self.on_duplicate_confirm)
        self.delete_recipe_button = widgets.Button(description='Delete recipe', button_style='danger')
        self.delete_recipe_button.on_click(self.on_delete_recipe_click)
        self.rename_cancel_button = widgets.Button(description='Cancel')
        self.rename_cancel_button.on_click(self.on_rename_cancel)
        self.rename_dialog = widgets.VBox(
            [self.rename_info_label,
             widgets.HBox([self.rename_new_name, self.rename_confirm_button,
                           self.duplicate_button, self.delete_recipe_button, self.rename_cancel_button])],
            layout={'display': 'none', 'border': '2px solid orange', 'padding': '5px', 'margin': '5px 0'}
        )
        self._rename_target = None   # nick the dialog is currently acting on
        
        self.delete_confirm_info = widgets.HTML(value='')
        self.delete_confirm_yes = widgets.Button(description='✓ Confirm delete', button_style='danger')
        self.delete_confirm_no = widgets.Button(description='✗ Cancel')
        self.delete_confirm_yes.on_click(self.on_delete_confirm_yes)
        self.delete_confirm_no.on_click(self.on_delete_confirm_no)
        self.delete_confirm_dialog = widgets.VBox(
            [self.delete_confirm_info,
            widgets.HBox([self.delete_confirm_yes, self.delete_confirm_no])],
            layout={'display': 'none', 'border': '2px solid red', 'padding': '5px', 'margin': '5px 0'}
        )
        self._delete_pending = None   # (nickname, original_index, affected) awaiting confirmation
        
        # hide_toggles = []
        # for col in self.hide_columns:
        #     if col == 'equ quant':
        #         continue  # Controlled by the unit text input below, not a checkbox
        #     hide_quant = widgets.Checkbox(
        #         value=False,
        #         description=col,
        #         disabled=False,
        #         indent=False
        #     )
        #     hide_quant.observe(lambda change, col=col: self.hide_col(change, col), 'value')
        #     hide_toggles.append(hide_quant)
 
        # # ── Equ Quant unit input (replaces the old checkbox) ─────────────────
        # # Empty / invalid  →  column hidden
        # # Valid pint unit  →  column shown, values converted to that unit
        # self.equ_quant_input = widgets.Text(
        #     value='',
        #     placeholder='e.g. 1/4 tsp, 0',
        #     continuous_update=False,
        #     layout=widgets.Layout(width='160px', flex='0 0 auto')
        # )
        # self.equ_quant_input.observe(self.on_equ_quant_unit_change, names='value')

        # hide_toggles.append(widgets.Box(layout=widgets.Layout(flex='1 1 auto')))
        # hide_toggles.append(
        #     widgets.Label(
        #         value='equ quant',
        #         layout=widgets.Layout(flex='0 0 auto', margin='0 0px 0 0')
        #     )
        # )
        # hide_toggles.append(self.equ_quant_input)


 
        # self.hide_toggleVBox = widgets.HBox(hide_toggles)
        # self.hide_toggleVBox.add_class('mv-columns-row')

        # # set cost_picker
        # cost_selection_widget = widgets.Dropdown(
        #     options=list(self.cost_select_method.keys()),
        #     layout=widgets.Layout(width='150px'),
        # )
        # cost_selection_widget.observe(self.cost_selector, names='value')
        
        # composition
        self.dfdisplay = widgets.Output(layout={'overflow': 'scroll'})
        self.df_widget = DataFrameWidget(
            pd.DataFrame(), width='90px',
            enabled_columns=self.enabled_columns,
            all_enabled_columns=self.all_enabled_columns,
            hide_columns=self.hide_columns, cc=self.cc, output=self.dfdisplay,
            trigger=self.trigger_update,
            widget_mode='Edit',
        )
        self.df_widget.scale_quantity_callback = self.df_widget._default_scale_quantity_callback
        self.df_widget.mode_changed_callback   = self._on_root_mode_changed
        self.df_widget.delete_confirm_callback = self.on_delete_confirm_needed
        self.df_widget.guide_changed_callback = self.refresh_search_options
        # Get reference to the back button
        self.backbutton = self.df_widget.backbutton
        self.progress_bar = self.df_widget.progress_bar
        
        # # cost multipliers (cost 3.0x, cost 3.5x)
        # cost_mult_input = widgets.FloatsInput(
        #     value=self.df_widget.cost_multipliers,
        #     format = '.2f'
        # )
        # cost_mult_input.observe(self.set_cost_multipliers, names='value')
        # cost_mult_hbox = widgets.HBox([widgets.Label(value='Cost multipliers: '), cost_mult_input])

        # Add menu buttons
        self.menubutton_hbox = widgets.HBox(
            self._build_menu_buttons(),
            layout=widgets.Layout(width='auto', margin='5px 0')
        )
        self.menubutton_hbox.add_class('mv-menu')
        
        topdisplay = widgets.VBox([
            self.menubutton_hbox,
            widgets.HBox([self.backbutton, self.searchinput, copybutton, self.renamebutton]),
            self.rename_dialog,
            self.delete_confirm_dialog,
            self.dfdisplay
        ])
        topdisplay.add_class('mv-card')
        # mentions display
        self.mdfdisplay = widgets.Output()       
        self.bottom_label = widgets.Label(value='items containing...', style=self.fontstyle)
        self.mdf_widget = DisplayDataFrameWidget(pd.DataFrame(), width='90px', enabled_columns=[], 
                                        hide_columns=self.hide_columns, cc=self.cc, output=self.mdfdisplay, trigger=self.trigger_mentions)
        self.bottom_label.add_class('mv-mhead')
        bottom_display = widgets.VBox([self.bottom_label, self.mdfdisplay])
        bottom_display.add_class('mv-card')
        
        # # Create tools section containing recipe and ingredient creation
        # def _eyebrow(text):
        #     return widgets.HTML(f"<div class='mv-eyebrow'>{text}</div>")

        # create_row = widgets.HBox([addrecipe_hbox, addingredient_hbox])
        # create_row.add_class('mv-create-row')
        # tools_section = widgets.VBox([_eyebrow('Create'), create_row])
        
        # # Track editor widgets for enabling/disabling in view mode
        # # We're now only including the recipe/ingredient creation tools and database management tools
        # self.editor_widgets = {
        #     'recipe_tools': tools_section,
        #     'database_tools': self.database_display,
        #     'cost_tools': self.cost_display
        # }
        
        # # display composition
        # # combined display
        # g_files   = widgets.VBox([_eyebrow('Database'), self.database_display])
        # g_create  = tools_section
        # g_columns = widgets.VBox([_eyebrow('Columns'), self.hide_toggleVBox])
        # g_cost    = widgets.VBox([_eyebrow('Cost selection'),
        #                         widgets.HBox([cost_selection_widget, cost_mult_hbox])])
        # toolbar = widgets.VBox([
        #     g_files,
        #     g_cost,
        #     g_create,
        #     g_columns,
        # ], layout=widgets.Layout(gap='12px'))

        self.toolbar = ToolbarWidget(
            database_filename=self.excel_filename,
            file_exists=os.path.exists(self.excel_filename),
            cost_method='recent',
            cost_methods=list(self.cost_select_method.keys()),
            cost_multipliers=list(self.df_widget.cost_multipliers),
            show_note=('note' not in self.hide_columns),
            show_conversion=('conversion' not in self.hide_columns),
            show_menu_price=('menu price' not in self.hide_columns),
            equ_quant_unit='',
        )

        # database_display is kept as an alias, not a separate widget —
        # product_fetcher.py's Shamrock integration locates it inside
        # self.vbox.children to position a button it injects after it.
        self.database_display = self.toolbar

        def _reset_to_blank():
            """Replace the current in-memory database with a fresh, empty one."""
            blank = CostCalculator()
            blank.costdf = pd.DataFrame(columns=blank.cost_columns)
            blank.uni_g  = pd.DataFrame(columns=blank.guide_columns)
            self.cc.__dict__.update(blank.__dict__)
            self.allvals = set()
            self.searchinput.options = ()
            self.df_widget.all_ingredients = self.allvals
            self.menubutton_hbox.children = tuple(self._build_menu_buttons())

        def _toolbar_on_msg(widget, content, buffers):
            t = content.get('type')
            fname = self.toolbar.database_filename.strip()

            if t == 'reload_database':
                if os.path.exists(fname):
                    self.reload_database(fname)
                    self.toolbar.file_exists = True
                else:
                    _reset_to_blank()
                    self.toolbar.file_exists = False

            elif t == 'write_database':
                if os.path.exists(fname):
                    try:
                        self.cc.write_cc(fname)
                    except Exception as exc:
                        self.toolbar.send({'type': 'db_error',
                                           'message': f"Error writing '{fname}': {exc}"})
                else:
                    self.toolbar.send({
                        'type': 'db_confirm',
                        'message': f"'{fname}' does not exist. Save current database with this filename?"
                    })

            elif t == 'confirm_write':
                try:
                    self.cc.write_cc(fname)
                    self.toolbar.file_exists = True
                except Exception as exc:
                    self.toolbar.send({'type': 'db_error',
                                       'message': f"Error writing '{fname}': {exc}"})

            elif t == 'create_recipe':
                shim = _TextBoxShim(content.get('value', ''))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.create_recipe(shim)
                msg = buf.getvalue().strip()
                if msg:
                    self.toolbar.send({'type': 'create_error', 'target': 'recipe', 'message': msg})

            elif t == 'create_ingredient':
                shim = _TextBoxShim(content.get('value', ''))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.create_ingredient(shim)
                msg = buf.getvalue().strip()
                if msg or shim.style.text_color == 'red':
                    self.toolbar.send({'type': 'create_error', 'target': 'ingredient',
                                       'message': msg or 'Invalid entry'})

        self.toolbar.on_msg(_toolbar_on_msg)

        def _toolbar_db_name_change(change):
            self.toolbar.file_exists = os.path.exists(change['new'].strip())
        self.toolbar.observe(_toolbar_db_name_change, names='database_filename')

        self.toolbar.observe(self.cost_selector, names='cost_method')
        self.toolbar.observe(self.set_cost_multipliers, names='cost_multipliers')
        self.toolbar.observe(self.on_equ_quant_unit_change, names='equ_quant_unit')
        self.toolbar.observe(lambda ch: self.hide_col(ch, 'note'), names='show_note')
        self.toolbar.observe(lambda ch: self.hide_col(ch, 'conversion'), names='show_conversion')
        self.toolbar.observe(lambda ch: self.hide_col(ch, 'menu price'), names='show_menu_price')

        toolbar = self.toolbar

        self.vbox = widgets.VBox([
            theme_widget(),
            toolbar,
            topdisplay,
            bottom_display
        ])
        self.vbox.add_class('mv-app')
        
    def _on_root_mode_changed(self, mode):
        '''Keep Explorer-owned chrome that depends on the root's mode in sync.
        Editor tools (load database / create recipe / create ingredient) are no
        longer hidden by mode — they stay visible always.
        '''
        edit = (mode == 'Edit')
        self.edit_mode = edit
        self.enabled_columns = self.df_widget.enabled_columns
        self.renamebutton.layout.display = 'flex' if edit else 'none'
        if not edit:
            # Leaving Edit mode -- close any open edit-only dialogs instead of
            # forcing them open. (Forcing rename_dialog to 'flex' here on every
            # Edit-mode entry was the bug behind it popping open unprompted.)
            self.rename_dialog.layout.display = 'none'
            self.delete_confirm_dialog.layout.display = 'none'
        self._refresh_rename_button()


    def _activate_view_mode(self):
        if self.df_widget.widget_mode != 'Edit':
            return
        self.df_widget.set_widget_mode('View', refresh=False)

    
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
        if self.df_widget.widget_mode == 'Flatten':
            if self.df_widget._navigating_back:
                self.df_widget.set_widget_mode('View', refresh=False)
                self.searchinput.value = iname
                return
            # falls through to normal navigation below, same as before
            # Menu buttons and lookup buttons both fall through to the normal
            # navigation path below.  update_search will sync the dropdown to
            # View (for menu buttons); _activate_view_mode handles it for
            # scaled sub-recipe lookups.

        parent_quantity = self.df_widget._pending_lookup_quantity
        self.df_widget._pending_lookup_quantity = None   # consume immediately
        self._scale_pending = None                       # default: no scaling

        # Edit mode: stay in Edit, no auto-switch, no auto-scale.
        if parent_quantity is not None and not self.edit_mode:
            scale = self._compute_scale_factor(iname, parent_quantity)
            if scale is not None:
                # Auto-switch to view mode and scale (View mode only)
                self._activate_view_mode()
                self._scale_pending = scale

        self.searchinput.value = iname
        
    def refresh_search_options(self):
        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals
        self.df_widget.refresh_ingredient_options()   # <-- add this line
    
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
            if self.df_widget.widget_mode == 'Flatten' and not navigating_back:
                self.df_widget.set_widget_mode('View', refresh=False)
 
            if self._scale_pending is not None:
                # Forward scaled navigation
                self.df_widget.scale_factor = self._scale_pending
            elif not navigating_back:
                # Fresh / manual navigation – clear any active scale
                self.df_widget.scale_factor = None
 
            self._scale_pending = None
            self.df_widget.close_child()
            self.df_widget.lookup_name(iname)
            self.df_widget.update_display()
            self.update_mentions(iname)
            self._refresh_rename_button()

        else:
            change['owner'].style.text_color = 'red'
            self._scale_pending = None
            self.df_widget._navigating_back = False
            self._refresh_rename_button()

    def cost_selector(self, change):
        method = change['new']
        self.cc.change_cost_method(self.cost_select_method[method])  # picker + memo flush + zero
        self.df_widget.lookup_name(self.df_widget.last_lookup)
        self.df_widget.update_display()
        self.df_widget.cascade_settings_to_children()

    def set_cost_multipliers(self, change):
        self.df_widget.cost_multipliers = change['new']
        if (self.df_widget.df_type == 'recipe'):
            if self.df_widget.widget_mode == 'Flatten':
                self.df_widget._render_flattened()
            else:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()
            self.df_widget.cascade_settings_to_children()
        
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
        self.df_widget.cascade_settings_to_children()
        
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
        else:
            self.hide_columns = set(self.hide_columns) | {'equ quant'}
            self.df_widget.equ_quant_unit      = None
            self.df_widget.equ_quant_precision = None

        # red only when something was actually typed and it didn't parse —
        # an empty field isn't an error, same as the old text_color logic
        self.toolbar.equ_quant_valid = valid or not raw

        self.df_widget.hide_columns = self.hide_columns
        if self.df_widget.last_lookup:
            if self.df_widget.widget_mode == 'Flatten':
                self.df_widget._render_flattened()
            else:
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()
            self.df_widget.cascade_settings_to_children()
        
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
            print(f'created recipe "{rname}"')
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

        menubuttons.append(self.progress_bar)
        return menubuttons
    
    def create_ingredient(self, textbox):
        '''Add a new ingredient to the unified guide -- or, if the nickname
        already exists, add a new price/size entry for it (an ingredient can
        have multiple guide rows over time, e.g. across dates/suppliers).

        Accepts "nickname" alone, or "nickname, size, price" with size and
        price optional and recognized in any order, comma-separated. Size and
        price must be given together (or not at all) -- a lone one is ignored.
        For an EXISTING nickname, a size/price pair is required to add a new
        entry; with no pair given, nothing happens (existing ingredient, no
        new info to record).
        '''
        raw = textbox.value.strip()
        if not raw:
            return

        try:
            parsed = parse_ingredient_entry(raw)
        except ValueError as e:
            print(str(e))
            textbox.style.text_color = 'red'
            return

        if parsed['partial_ignored']:
            print('Size and price must both be given (or neither) -- ignoring the one you entered.')

        ing_name = parsed['nickname']
        has_pair = parsed['size'] is not None and parsed['price'] is not None
        current_date = pd.to_datetime('today').strftime('%Y-%m-%d')

        existing = self.cc.uni_g.loc[self.cc.uni_g['nickname'] == ing_name]

        if not existing.empty:
            # ---- Existing ingredient: only act on a full size+price pair ----
            if not has_pair:
                print(f'Ingredient "{ing_name}" already exists in the guide. '
                    f'Give both a size and a price to add a new entry for it.')
                textbox.style.text_color = self.defcolor
                return

            # New row reuses the most recent existing row's other metadata
            # (description, supplier, brand, allergen, conversion, ...) and
            # just updates size, price, and date.
            template = existing.iloc[-1].copy()
            template['price'] = parsed['price']
            template['size'] = parsed['size']
            template['date'] = current_date
            new_row = pd.DataFrame([template])

            self.cc.uni_g = pd.concat([self.cc.uni_g, new_row], ignore_index=True)
            self.cc.mark_guide_dirty()
            self.cc.clear_cost(ing_name)  # cached costs for this ingredient (and its recipes) are stale now

            # If this ingredient is currently on screen, refresh it in place
            if self.df_widget.last_lookup == ing_name:
                self.df_widget.lookup_name(ing_name)
                self.df_widget.update_display()

            textbox.style.text_color = self.defcolor
            print(f'Added new entry for "{ing_name}": size={parsed["size"]}, price=${parsed["price"]:g}')
            textbox.value = ''
            return

        # ---- Brand new ingredient ----
        textbox.style.text_color = self.defcolor
        size = parsed['size'] if parsed['size'] is not None else '1 count'
        price = parsed['price'] if parsed['price'] is not None else 0

        new_ingredient = pd.DataFrame(
            data={
                'supplier': [''],
                'description': [f'{ing_name}'],
                'number': [''],
                'price': [price],
                'unit': ['ea'],
                'size': [size],
                'brand': [''],
                'order': [''],
                'nickname': [ing_name],
                'note': [''],
                'allergen': [''],
                'conversion': [''],
                'date': [current_date]}
        )

        self.cc.uni_g = pd.concat([self.cc.uni_g, new_ingredient], ignore_index=True)
        self.cc.mark_guide_dirty()

        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals
        self.df_widget.refresh_ingredient_options()

        details = ing_name
        if parsed['size'] is not None:
            details += f', size={size}'
        if parsed['price'] is not None:
            details += f', price=${price:g}'
        print(f'Created new ingredient: {details}')

        textbox.value = ''
        
    def _refresh_rename_button(self):
        ''' Enable rename only in Edit mode with a valid recipe/ingredient loaded '''
        nick = self.searchinput.value
        self.renamebutton.disabled = not (self.edit_mode and nick in self.allvals)

    def on_rename_click(self, b=None):
        ''' Open the rename/duplicate dialog for the currently loaded nick '''
        nick = self.df_widget.last_lookup
        if not nick or nick not in self.allvals:
            return
        self._rename_target = nick

        is_recipe = not self.cc.get_recipe_entry(nick).empty
        affected = self.cc.count_rename_impact(nick)
        if affected == 0:
            msg = f'Renaming "{nick}" will not affect any other recipe.'
        elif affected == 1:
            msg = f'Renaming "{nick}" will update 1 other recipe that uses it.'
        else:
            msg = f'Renaming "{nick}" will update {affected} other recipes that use it.'
        if is_recipe:
            msg += ' Duplicating creates an independent copy and leaves everything else unchanged.'

        self.rename_info_label.value = msg
        self.rename_new_name.value = nick
        self.rename_new_name.style.text_color = self.defcolor
        self.duplicate_button.layout.display = 'flex' if is_recipe else 'none'
        self.delete_recipe_button.layout.display = 'flex' if is_recipe else 'none'
        self.rename_dialog.layout.display = 'flex'

    def on_rename_cancel(self, b=None):
        self.rename_dialog.layout.display = 'none'

    def on_rename_confirm(self, b=None):
        old_name = self._rename_target
        new_name = self.rename_new_name.value.strip()
        try:
            self.cc.rename_nick(old_name, new_name)
        except ValueError as e:
            self.rename_new_name.style.text_color = 'red'
            self.rename_info_label.value = str(e)
            return
        self._after_rename_or_duplicate(old_name, new_name, renamed=True)
        
    # def on_delete_confirm_needed(self, nickname, original_index, affected):
    #     '''Called by DataFrameWidget when deleting the last guide entry for
    #     `nickname` would also remove it from one or more recipes.'''
    #     self._delete_pending = (nickname, original_index, affected)
    #     names = ', '.join(affected)
    #     plural = 'recipe' if len(affected) == 1 else 'recipes'
    #     self.delete_confirm_info.value = (
    #         f'<b style="color:red">⚠ "{nickname}" has no other price entries. '
    #         f'Deleting this one will fully remove "{nickname}" and take it out of '
    #         f'{len(affected)} {plural} that use it: {names}. This cannot be undone.</b>'
    #     )
    #     self.delete_confirm_dialog.layout.display = 'flex'

    # def on_delete_confirm_yes(self, b=None):
    #     if self._delete_pending is None:
    #         return
    #     nickname, original_index, affected = self._delete_pending
    #     self.df_widget.confirmed_cascade_delete(nickname, original_index, affected)
    #     self._delete_pending = None
    #     self.delete_confirm_dialog.layout.display = 'none'

    #     # nickname no longer exists -- refresh search caches and clear the display
    #     nicks = set(self.cc.uni_g['nickname'].dropna().unique())
    #     ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
    #     self.allvals = nicks.union(ingrs)
    #     self.searchinput.options = tuple(self.allvals)
    #     self.df_widget.all_ingredients = self.allvals
    #     self.searchinput.value = ''

    # def on_delete_confirm_no(self, b=None):
    #     self._delete_pending = None
    #     self.delete_confirm_dialog.layout.display = 'none'
    
    def on_delete_confirm_needed(self, nickname, original_index, affected):
        '''Called by DataFrameWidget when deleting the last guide entry for
        `nickname` would also remove it from one or more recipes.'''
        self._delete_pending = {'kind': 'guide', 'nickname': nickname,
                                 'original_index': original_index, 'affected': affected}
        names = ', '.join(affected)
        plural = 'recipe' if len(affected) == 1 else 'recipes'
        self.delete_confirm_info.value = (
            f'<b style="color:red">⚠ "{nickname}" has no other price entries. '
            f'Deleting this one will fully remove "{nickname}" and take it out of '
            f'{len(affected)} {plural} that use it: {names}. This cannot be undone.</b>'
        )
        self.delete_confirm_dialog.layout.display = 'flex'

    def on_delete_recipe_click(self, b=None):
        '''From the rename/duplicate dialog: show a confirmation before
        permanently deleting the recipe currently loaded there.'''
        nickname = self._rename_target
        if not nickname:
            return
        affected = sorted(set(self.cc.get_parents(nickname)) - {'recipe'})
        msg = f'<b style="color:red">⚠ Permanently delete "{nickname}"?</b> This cannot be undone.'
        if affected:
            names = ', '.join(affected)
            plural = 'recipe' if len(affected) == 1 else 'recipes'
            msg += (f' It will also be removed from {len(affected)} other {plural} '
                    f'that use it: {names}.')
        self.delete_confirm_info.value = msg
        self._delete_pending = {'kind': 'recipe', 'nickname': nickname}
        self.rename_dialog.layout.display = 'none'
        self.delete_confirm_dialog.layout.display = 'flex'

    def on_delete_confirm_yes(self, b=None):
        if self._delete_pending is None:
            return
        pending = self._delete_pending
        self._delete_pending = None
        self.delete_confirm_dialog.layout.display = 'none'

        if pending['kind'] == 'recipe':
            self.cc.delete_recipe(pending['nickname'])
            self.df_widget.clear_display()
        else:
            self.df_widget.confirmed_cascade_delete(
                pending['nickname'], pending['original_index'], pending['affected']
            )

        # the deleted item no longer exists -- refresh search caches and chrome
        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals
        self.menubutton_hbox.children = tuple(self._build_menu_buttons())
        self.searchinput.value = ''

    def on_delete_confirm_no(self, b=None):
        self._delete_pending = None
        self.delete_confirm_dialog.layout.display = 'none'

    def on_duplicate_confirm(self, b=None):
        old_name = self._rename_target
        new_name = self.rename_new_name.value.strip()
        try:
            self.cc.duplicate_recipe(old_name, new_name)
        except ValueError as e:
            self.rename_new_name.style.text_color = 'red'
            self.rename_info_label.value = str(e)
            return
        self._after_rename_or_duplicate(old_name, new_name, renamed=False)

    def _after_rename_or_duplicate(self, old_name, new_name, renamed):
        ''' Common cleanup after either action succeeds: refresh search
            caches, close the dialog, and navigate to the result.
        '''
        nicks = set(self.cc.uni_g['nickname'].dropna().unique())
        ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        self.allvals = nicks.union(ingrs)
        self.searchinput.options = tuple(self.allvals)
        self.df_widget.all_ingredients = self.allvals

        self.rename_dialog.layout.display = 'none'

        if renamed:
            # old_name no longer exists anywhere — fix up history
            self.df_widget.search_history = [
                new_name if h == old_name else h for h in self.df_widget.search_history
            ]
        # for a duplicate, old_name is still valid and untouched — just
        # navigate to the freshly created copy
        self.searchinput.value = new_name
        
    def display(self):
        display(self.vbox)
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output
from df_functions import *
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
        self.enabled_columns = ['ingredient', 'quantity', 'price', 'menu price', 'size', 'saved cost', 'date', 'supplier', 'description', 'allergen', 'conversion', 'order', 'number']
        self.hide_columns = ['note', 'conversion', 'saved cost', 'equ quant', 'menu price']
        self.cc = cc
        self.cost_select_method = {'recent': pick_recent_cost, 
                                'maximum': pick_max_cost, 
                                'minimum': pick_min_cost,
                                'all': lambda x: x}
        

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

        hide_toggles = [widgets.Label(value='Show/Hide columns:', layout=widgets.Layout(width='40%'))]
        for col in self.hide_columns:
            # use saved cost check box
            hide_quant = widgets.Checkbox(
                value=False,
                description=col,
                disabled=False,
                indent=False
            )
            hide_quant.observe(lambda change, col=col: self.hide_col(change, col), 'value')
            hide_toggles.append(hide_quant)
            
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

        # cost multipliers (cost 3.0x, cost 3.5x)
        cost_mult_input = widgets.FloatsInput(
            value=self.df_widget.cost_multipliers,
            format = '.2f'
        )
        cost_mult_input.observe(self.set_cost_multipliers, names='value')
        cost_mult_hbox = widgets.HBox([widgets.Label(value='Cost multipliers: '), cost_mult_input])

        
        topdisplay = widgets.VBox([widgets.HBox([self.searchinput, copybutton, usesaved]), self.dfdisplay], layout={'border': '2px solid green'})
        
        
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
        
    def trigger_mentions(self, iname):
        # reload current search in no iname
        if iname == None:
            iname = self.searchinput.value
        else:
            self.searchinput.value = iname
    
    def trigger_update(self, iname):
        self.searchinput.value = iname
        
    def update_search(self, change):
        if change['new'] in self.allvals:
            change['owner'].style.text_color = self.defcolor
            iname = change['new']

            self.df_widget.lookup_name(iname)
            self.df_widget.update_display()
            self.update_mentions(iname)

        else:
            change['owner'].style.text_color = 'red'

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

    def usesaved(self, change):
        # set cc to use saved cost depending on user checkbox
        
        self.cc.use_saved = change['new']
        
        # recompute all?
        self.cc.costdf['cost'] = 0            
        self.df_widget.lookup_name(self.df_widget.last_lookup)
        self.df_widget.update_display()
        
    def update_mentions(self, iname):
        self.mdf_widget.search_name(iname)
        if self.mdf_widget.df.empty:
            return
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
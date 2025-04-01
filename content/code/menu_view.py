import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display, clear_output
import os
from df_functions import *
from utils import get_xlsx_files

# List of common allergens for filtering
my_allergens = ['gluten', 'dairy', 'egg', 'soy', 'fish', 'shellfish', 'tree-nut', 'peanut', 'poultry', 'sesame']

class MenuViewer:
    """
    A simplified menu viewing interface based on menu_view.py that integrates with
    the existing data structures from data_frame_explorer.py and data_frame_widget.py
    """
    
    def __init__(self, cc=None):
        # Initialize with a CostCalculator if provided, otherwise create a new one
        self.cc = cc if cc is not None else CostCalculator()
        self.allvals = set()
        self.excel_filename = 'amc_menu_database.xlsx'
        self.hide_columns = ['cost', 'note', 'conversion', 'saved cost', 'equ quant']
        self.fontstyle = {'font_size': '12pt'}
        
        # Track selected allergens
        self.selected_allergens = []
        
        # Track highlighted ingredients
        self.highlighted_ingredients = []
        
        # Set up file selection UI
        self.setup_file_selector()
        
        # Set up main UI components
        self.setup_menu_interface()
        
        # Try to load default database
        self.try_load_default_database()
    
    def setup_file_selector(self):
        """Set up the file selection UI components"""
        # Create dropdown for file selection
        self.dropdown = widgets.Dropdown(
            options=['No .xlsx files found'],
            description='Files:',
            disabled=True,
        )
        self.dropdown.observe(self.on_dropdown_change, names='value')
        
        # Create text box for manual filename entry
        self.text_box = widgets.Text(
            description='Filename:',
            disabled=True,
            continuous_update=False
        )
        self.text_box.observe(self.on_text_box_value_change, names='value')
        
        # Create refresh button
        self.refresh_button = widgets.Button(
            description='Refresh',
            disabled=False,
            button_style='',
            tooltip='Refresh file list',
            icon='refresh'
        )
        self.refresh_button.on_click(self.on_refresh_button_clicked)
        
        # Create status label
        self.selected_file_label = widgets.Label()
        
        # Update dropdown with available files
        self.update_dropdown()
        
        # Assemble file selector
        self.file_selector = widgets.VBox([
            widgets.HBox([self.dropdown, self.text_box, self.refresh_button]),
            self.selected_file_label
        ])
    
    def setup_menu_interface(self):
        """Set up the main menu viewing interface"""
        # Create search input
        self.searchinput = widgets.Combobox(
            placeholder='ingredient/item',
            options=tuple(self.allvals),
            description='Search:',
            ensure_option=False,
            disabled=False,
            style=self.fontstyle
        )
        self.searchinput.observe(self.update_search, names='value')
        
        # Create main display area
        self.dfdisplay = widgets.Output(layout={'overflow': 'scroll', 'border': '1px solid black', 'min_height': '400px'})
        
        # Pass the highlighted_ingredients reference to the MenuDisplayWidget
        self.df_widget = MenuDisplayWidget(
            pd.DataFrame(), 
            cc=self.cc, 
            output=self.dfdisplay, 
            trigger=self.trigger_update,
            viewer=self  # Pass reference to MenuViewer for access to highlighted_ingredients
        )
        
        # Get references to back button and ingredient accordion
        self.backbutton = self.df_widget.backbutton
        
        # Create top display area
        self.top_display = widgets.VBox([
            widgets.HBox([self.backbutton, self.searchinput]),
            self.dfdisplay
        ], layout={'border': '2px solid green'})
        
        # # Create allergen filter section
        # self.allergen_title = widgets.HTML(value="<h3>Highlight by Allergens:</h3>")
        # self.allergen_checkboxes = []
        # for allergen in my_allergens:
        #     checkbox = widgets.Checkbox(value=False, description=allergen)
        #     checkbox.observe(self.on_allergen_toggle, names='value')
        #     self.allergen_checkboxes.append(checkbox)
        
        # # Arrange checkboxes into rows
        # numcols = 5
        # allergen_rows = [widgets.HBox(self.allergen_checkboxes[i:i+numcols]) for i in range(0, len(self.allergen_checkboxes), numcols)]
        # self.allergen_box = widgets.VBox([self.allergen_title] + allergen_rows)
        
        # Create allergen filter section with more compact layout
        self.allergen_title = widgets.HTML(value="<h3>Highlight by Allergens:</h3>")
        self.allergen_checkboxes = []
        for allergen in my_allergens:
            checkbox = widgets.Checkbox(
                value=False, 
                description=allergen,
                indent=False,
                layout=widgets.Layout(width='auto', margin='0px 15px 0px 20px')  # More compact layout
            )
            checkbox.observe(self.on_allergen_toggle, names='value')
            self.allergen_checkboxes.append(checkbox)
        
        # Arrange checkboxes into more rows with fewer items per row to make them take less vertical space
        allergen_rows = [widgets.HBox(self.allergen_checkboxes[i:i+5], layout=widgets.Layout(
            flex_wrap='wrap',
            align_items='center',
            margin='0',
            padding='0'
        )) for i in range(0, len(self.allergen_checkboxes), 5)]
        
        self.allergen_box = widgets.VBox(
            [self.allergen_title] + allergen_rows,
            layout=widgets.Layout(
                margin='0',
                padding='3px',
                border='1px solid lightgray'
            )
        )
        
        # Create ingredient highlighting section
        self.setup_ingredient_highlight_section()
        
        # Create menu buttons
        menulist = ['breakfast', 'lunch', 'dinner', 'deserts']
        menubuttons = []
        for menu in menulist:
            button = widgets.Button(
                description=menu.capitalize(),
                layout=widgets.Layout(width='auto'),
                button_style='primary'
            )
            button.on_click(self.df_widget.make_on_click(menu))
            menubuttons.append(button)
        
        self.menubutton_hbox = widgets.HBox(menubuttons, layout=widgets.Layout(width='auto'))
        
        # Create title
        self.title = widgets.HTML(value="<h2>Menu Viewer</h2>")
        
        # Assemble the whole interface
        self.vbox = widgets.VBox([
            self.file_selector,
            self.title,
            self.menubutton_hbox,
            self.allergen_box,
            self.ingredient_highlight_box,
            self.top_display
        ])
    
    def setup_ingredient_highlight_section(self):
        """Set up the ingredient highlighting section"""
        # Create ingredient highlight title
        self.ingredient_highlight_title = widgets.HTML(value="<h3>Highlight by Ingredients:</h3>")
        
        # Create ingredient input with autocomplete
        self.ingredient_input = widgets.Combobox(
            placeholder='Enter ingredient to highlight',
            options=tuple(), # Will be populated after loading data
            description='Ingredient:',
            ensure_option=False,
            continuous_update=False,
            layout=widgets.Layout(width='300px')
        )
        
        # Create add button
        self.add_ingredient_button = widgets.Button(
            description='Add',
            button_style='success',
            layout=widgets.Layout(width='auto')
        )
        self.add_ingredient_button.on_click(self.on_add_ingredient)
        
        # Create clear button
        self.clear_ingredients_button = widgets.Button(
            description='Clear All',
            button_style='warning',
            layout=widgets.Layout(width='auto')
        )
        self.clear_ingredients_button.on_click(self.on_clear_ingredients)
        
        # Create container for ingredient chips
        self.ingredient_chips_container = widgets.HBox([], layout=widgets.Layout(flex_wrap='wrap'))
        
        # Assemble input row
        ingredient_input_row = widgets.HBox([
            self.ingredient_input, 
            self.add_ingredient_button,
            self.clear_ingredients_button
        ])
        
        # Assemble ingredient highlight box
        self.ingredient_highlight_box = widgets.VBox([
            self.ingredient_highlight_title,
            ingredient_input_row,
            self.ingredient_chips_container
        ], layout={'border': '1px solid lightgray', 'padding': '5px', 'margin': '5px'})
    
    def create_ingredient_chip(self, ingredient):
        """Create a removable chip for a highlighted ingredient"""
        # Create container
        chip = widgets.HBox(layout=widgets.Layout(
            border='1px solid #ccc',
            border_radius='15px',
            padding='2px 10px',
            margin='3px',
            background_color='#e8f4f8'
        ))
        
        # Create label
        label = widgets.Label(value=ingredient)
        
        # Create remove button
        remove_button = widgets.Button(
            description='×',
            button_style='',
            layout=widgets.Layout(width='24px', height='24px', padding='0px')
        )
        
        # Set up remove action
        def on_remove(b):
            self.highlighted_ingredients.remove(ingredient)
            self.update_ingredient_chips()
            self.apply_ingredient_highlighting()
        
        remove_button.on_click(on_remove)
        
        # Assemble chip
        chip.children = [label, remove_button]
        return chip
    
    def update_ingredient_chips(self):
        """Update the ingredient chips display"""
        chips = [self.create_ingredient_chip(ing) for ing in self.highlighted_ingredients]
        self.ingredient_chips_container.children = chips
    
    def on_add_ingredient(self, b):
        """Handle adding an ingredient to highlight"""
        ingredient = self.ingredient_input.value.strip()
        
        # Validate ingredient exists in the dataset
        if ingredient and ingredient in self.get_valid_ingredients():
            if ingredient not in self.highlighted_ingredients:
                self.highlighted_ingredients.append(ingredient)
                self.update_ingredient_chips()
                self.apply_ingredient_highlighting()
                self.ingredient_input.value = ""  # Clear input
        else:
            # Show error if ingredient doesn't exist
            original_description = self.ingredient_input.description
            self.ingredient_input.description = "Not found!"
            self.ingredient_input.style = {'description_color': 'red'}
            
            # Reset after 2 seconds
            import threading
            def reset_description():
                self.ingredient_input.description = original_description
                self.ingredient_input.style = {}
            
            timer = threading.Timer(2.0, reset_description)
            timer.start()
    
    def on_clear_ingredients(self, b):
        """Handle clearing all highlighted ingredients"""
        self.highlighted_ingredients = []
        self.update_ingredient_chips()
        self.apply_ingredient_highlighting()
    
    def get_valid_ingredients(self):
        """Get set of valid ingredients for highlighting"""
        return set(self.cc.costdf['ingredient'].dropna().unique())
    
    def update_dropdown(self):
        """Update dropdown options with available Excel files"""
        xlsx_files = get_xlsx_files()
        if xlsx_files:
            self.dropdown.options = xlsx_files
            self.dropdown.disabled = False
            self.text_box.disabled = True
        else:
            self.dropdown.options = ['No .xlsx files found']
            self.dropdown.disabled = True
            self.text_box.disabled = False
    
    def on_refresh_button_clicked(self, b):
        """Handle refresh button click"""
        self.update_dropdown()
    
    def on_dropdown_change(self, change):
        """Handle dropdown selection change"""
        if change['new'] != 'No .xlsx files found':
            self.selected_file_label.value = f'Selected file: {change["new"]}'
            self.read_file(change["new"])
    
    def on_text_box_value_change(self, change):
        """Handle text box value change"""
        if change['new']:
            self.selected_file_label.value = f'Selected file: {change["new"]}'
            self.read_file(change["new"])
    
    def read_file(self, filename):
        """Read data from the specified Excel file"""
        try:
            self.excel_filename = filename
            self.cc.read_from_xlsx(filename)
            self.selected_file_label.value = f'Successfully loaded file: {filename}'
            
            # Update UI with new data
            self.update_all_values()
        except Exception as e:
            self.selected_file_label.value = f'Error loading file: {filename}. {str(e)}'
    
    def update_all_values(self):
        """Update the set of all valid values for search"""
        if 'nickname' in self.cc.uni_g.columns:
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
            self.allvals = nicks.union(ingrs)
            self.searchinput.options = tuple(self.allvals)
            self.df_widget.all_ingredients = self.allvals
            
            # Update ingredient input options
            self.ingredient_input.options = tuple(ingrs)
    
    def update_search(self, change):
        """Handle search input changes"""
        if change['new'] in self.allvals:
            change['owner'].style.text_color = 'black'  # Reset color if valid
            iname = change['new']
            self.df_widget.lookup_name(iname)
            
            # Apply allergen and ingredient highlighting to the new search result
            self.apply_allergen_highlighting()
            self.apply_ingredient_highlighting()
            
            self.df_widget.update_display()
        else:
            change['owner'].style.text_color = 'red'  # Show red if invalid
    
    def trigger_update(self, iname):
        """Handle updates triggered from the widget"""
        self.searchinput.value = iname
    
    def on_allergen_toggle(self, change):
        """Handle allergen checkbox toggles"""
        # Update selected allergens list
        self.selected_allergens = [cb.description for cb in self.allergen_checkboxes if cb.value]
        
        # Apply the filtering
        self.apply_allergen_highlighting()
    
    def apply_allergen_highlighting(self):
        """Apply allergen highlighting based on selected allergens"""
        # If we have a recipe displayed, update with filtered ingredients
        if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
            # Store current recipe name
            recipe_name = self.df_widget.last_lookup
            
            # Reload the recipe to show all ingredients
            self.df_widget.lookup_name(recipe_name)
            
            # Filter ingredients if allergens are selected
            if self.selected_allergens:
                # Filter out rows containing selected allergens
                filtered_df = self.df_widget.df.copy()
                
                # Only filter ingredient rows (not the recipe header)
                for i, row in filtered_df.iloc[1:].iterrows():
                    allergens = row.get('allergen', '')
                    if isinstance(allergens, str):
                        allergen_list = [a.strip().lower() for a in allergens.split(',')]
                        if any(a.lower() in allergen_list for a in self.selected_allergens):
                            # Highlight the row by adding a visual indicator
                            filtered_df.at[i, 'allergen'] = f"⚠️ {allergens}"
                
                self.df_widget.df = filtered_df
            
            # Update the display
            self.df_widget.update_display()
    
    def apply_ingredient_highlighting(self):
        """Apply highlighting for selected ingredients"""
        # Skip if no ingredients to highlight
        if not self.highlighted_ingredients:
            pass
        
        # If we have a recipe displayed, update with highlighted ingredients
        if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
            recipe_name = self.df_widget.last_lookup
            
            # Make a copy of the current DataFrame and add a highlighting flag
            filtered_df = self.df_widget.df.copy()
            filtered_df['highlight'] = False
            
            # Check each ingredient in the recipe for direct matches
            for i, row in filtered_df.iloc[1:].iterrows():
                ingredient = row.get('ingredient', '')
                
                # Check if this ingredient should be highlighted directly
                if ingredient in self.highlighted_ingredients:
                    filtered_df.at[i, 'highlight'] = True
                
                # Also check for sub-ingredients in recipes
                if not self.cc.is_ingredient(ingredient) and len(self.cc.get_children(ingredient)) > 0:
                    # Get flattened ingredients
                    ing_list = []
                    try:
                        if isinstance(row.get('ingredient list'), str):
                            ing_list = row['ingredient list'].split(',')
                        else:
                            flat_ingredients = self.cc.flatten_recipe(ingredient, row['quantity'])
                            ing_list = flat_ingredients['ingredient'].tolist()
                        
                        # Check if any highlighted ingredients are in the flattened list
                        if any(ing in self.highlighted_ingredients for ing in ing_list):
                            filtered_df.at[i, 'highlight'] = True
                    except:
                        pass
            
            # Update the display widget with the highlighted DataFrame
            self.df_widget.df = filtered_df
            self.df_widget.update_display()
    
    def try_load_default_database(self):
        """Try to load the default database file"""
        try:
            self.read_file('amc_menu_database.xlsx')
        except:
            # If default doesn't exist, try any available Excel file
            xlsx_files = get_xlsx_files()
            if xlsx_files:
                self.read_file(xlsx_files[0])
            else:
                self.selected_file_label.value = 'No database loaded. Please select a file.'
    
    def display(self):
        """Display the complete interface"""
        display(self.vbox)


class MenuDisplayWidget:
    """
    Widget for displaying menu items and recipes in a user-friendly format
    """
    
    def __init__(self, df, cc=None, output=None, trigger=None, viewer=None):
        # Initialize with a CostCalculator if provided, otherwise create a new one
        self.cc = cc if cc is not None else CostCalculator()
        self.df = df.reset_index(drop=True).copy()
        self.output = output if output is not None else widgets.Output()
        self.trigger = trigger
        self.viewer = viewer  # Store reference to MenuViewer
        
        # Initialize properties
        self.width = '100px'
        self.column_width = {}
        self.df_type = None
        self.hide_columns = ['cost', 'note', 'conversion', 'saved cost', 'equ quant']
        self.backbutton = widgets.Button(description='Back')
        self.search_history = []
        self.last_lookup = ''
        
        # Initialize ingredient lists
        self.all_ingredients = set()
        if cc and 'nickname' in cc.uni_g.columns:
            nicks = set(cc.uni_g['nickname'].dropna().unique())
            ingrs = set(cc.costdf['ingredient'].dropna().unique())
            self.all_ingredients = nicks.union(ingrs)
        
        # Set type based on DataFrame structure
        self.findtype()
    
    def findtype(self):
        """Determine the type of the current DataFrame"""
        if self.df.empty:
            self.df_type = None
        elif 'ingredient' in self.df.columns:
            if len(self.df) > 0 and self.df.iloc[0]['item'] == 'recipe':
                self.df_type = 'recipe'                
            else:
                self.df_type = 'mentions'
        elif 'nickname' in self.df.columns:
            self.df_type = 'guide'
        else:
            self.df_type = None
            
        return self.df_type
    
    def update_column_width(self):
        """Calculate and update column widths based on content"""
        def carlen(myval):
            myval = f"{myval:0.2f}" if isinstance(myval, float) else myval
            return len(str(myval))
    
        try:
            # Calculate widths based on content
            maxlen = {}
            for col in self.df.columns:
                try:
                    maxlen[col] = self.df[col].map(lambda y: 5 + 10 * carlen(y)).max()
                except:
                    maxlen[col] = 100  # Default width
            
            # Calculate widths based on column names
            cn_len = {c: 5 + 8 * len(str(c)) for c in self.df.columns}
    
            # Use the maximum of content width and column name width
            self.column_width = {c: max(maxlen.get(c, 100), cn_len.get(c, 100)) for c in self.df.columns}
            
            # Special case for recipe item column
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
        except:
            # Default if something goes wrong
            self.column_width = {c: 100 for c in self.df.columns}
    
    def setdf(self, mylookup):
        """Set the current DataFrame based on the lookup value"""
        self.last_lookup = mylookup
        mydf = self.cc.findframe(mylookup).reset_index(drop=True).copy()
        self.df = mydf
        self.findtype()
        
        if self.df_type == 'recipe':
            colorder = ['item', 'ingredient', 'quantity', 'cost', 'equ quant']
            
            # Add allergen column
            mydf['allergen'] = mydf['ingredient'].apply(lambda x: ', '.join(self.cc.findNset_allergens(x)))
            
            mydf = reorder_columns(mydf, colorder)
            mycolumns = [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            
            # Clear allergen for menus
            if mydf.at[0, 'ingredient'] in ['breakfast', 'lunch', 'dinner', 'deserts']:
                mydf.at[0, 'allergen'] = ''
            
            self.df = mydf
            self.update_column_width()
        else:
            mycolumns = mydf.columns
            if self.df_type == 'guide':
                mycolumns = ['description', 'brand', 'allergen']
            else:
                mycolumns = [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            self.df = mydf
            self.update_column_width()
    
    def update_display(self):
        """Update the display with widgets for each cell of the DataFrame"""
        def addweight(row):
            """Helper function to add weight to a row"""
            try:
                row['weight'] = self.cc.do_conversion(row['ingredient'], str(row['quantity']), '1 g')
            except:
                row['weight'] = None
            return row
        
        def ingredients_by_weight(ing, quant):
            """Get ingredients sorted by weight"""
            try:
                rdf = self.cc.flatten_recipe(ing, quant)
                rdf = rdf.apply(addweight, axis=1)
                return list(rdf.sort_values(by='weight', ascending=False)['ingredient'])
            except:
                return []
                    
        button_height = '33px'
        min_button_width = 120
        
        # Calculate maximum text length for each column
        max_lengths = {}
        for col in self.df.columns:
            try:
                max_lengths[col] = max(self.df[col].astype(str).map(len).max(), len(col)) * 8
            except:
                max_lengths[col] = min_button_width
        
        # Configure 'Back' button
        self.backbutton.layout = widgets.Layout(width=f'{max_lengths.get("ingredient", min_button_width)}px', height=button_height)
        if len(self.search_history) > 1:
            self.backbutton.on_click(self.on_back_click)
            self.backbutton.disabled = False
        else:
            self.backbutton.disabled = True
            
        # Create header labels for each column
        header_widgets = []
        header_widgets.append(widgets.Label(
            value="Item", 
            layout=widgets.Layout(width=f'{max_lengths.get("ingredient", min_button_width)}px', height=button_height, flex='0 0 auto')
        ))

        for col in self.df.columns:
            if col in ['allergen']:
                header_widgets.append(widgets.Label(
                    value=col.capitalize(), 
                    layout=widgets.Layout(width=f'{max_lengths.get(col, min_button_width)}px', height=button_height, flex='0 0 auto')
                ))
        
        # Add a header for the ingredients column
        header_widgets.append(widgets.Label(
            value="Ingredients", 
            layout=widgets.Layout(height=button_height, flex='1 1 auto')
        ))
        
        # Create a HBox for the header row
        header_hbox = widgets.HBox(header_widgets)
        
        # Create a list to hold row widgets
        rows = []
        
        # Get highlighted ingredients from the viewer
        highlighted_ingredients = []
        if self.viewer:
            highlighted_ingredients = self.viewer.highlighted_ingredients
        
        # Iterate through DataFrame rows and create widgets for each cell
        for index, row in self.df.iterrows():
            row_widgets = []
            item_widget = None
            allergen_widget = None
            inglist_widget = None
            
            if self.df_type in ['guide', None]:
                continue  # Skip processing for 'guide' and None types
            
            if self.df_type == 'recipe':
                recipe_title = False
                if index == 0:
                    if row['ingredient'] in ['breakfast', 'lunch', 'dinner', 'deserts']:
                        continue
                    
                    # Create recipe title
                    item_widget = widgets.HTML(value=f"<h2><i>{row['ingredient']}</i></h2>")
                
                ingredient = row['ingredient']
            elif self.df_type == 'mentions':
                ingredient = row['item']
            else:
                continue
            
            button_width = max(min_button_width, max_lengths.get('ingredient', min_button_width))
            label_width = button_width
            
            # Create a button for the ingredient if it's not already created
            if item_widget is None:
                # Standard button for all ingredients (no special highlighting in the button itself)
                item_widget = widgets.Button(
                    description=ingredient, 
                    layout=widgets.Layout(width=f'{button_width}px', height=button_height),
                    tooltip=f"View details for {ingredient}"
                )
                item_widget.on_click(self.make_on_click(ingredient))
            
            # Create labels for the other columns
            for col in self.df.columns:
                if col in ['ingredient', 'item', 'menu price']:
                    continue
                elif col in ['allergen']:
                    label_width = max(min_button_width, max_lengths.get(col, min_button_width))
                    
                    # Highlight allergens if the value starts with warning emoji
                    allergen_value = str(row[col])
                    label_style = {}
                    if allergen_value.startswith('⚠️'):
                        label_style = {'background_color': '#FFEEEE'}
                    
                    if len(allergen_value) > 0:
                        # HTML widget gives better formatting control and handles overflow better
                        allergen_widget = widgets.HTML(
                            value=allergen_value,
                            layout=widgets.Layout(
                                #width=f'{label_width}px',
                                style=label_style
                            )
                        )
                    else:
                        allergen_widget = None
            
            # Create ingredient list
            inglist = []
            clean_ingredient = ingredient
                
            if not self.cc.is_ingredient(clean_ingredient) and len(self.cc.get_children(clean_ingredient)) > 1:
                # Get ingredient list
                if 'ingredient list' in self.df.columns and isinstance(row.get('ingredient list'), str):
                    inglist = row['ingredient list'].split(',')
                else:
                    try:
                        inglist = ingredients_by_weight(clean_ingredient, row['quantity'])
                        if inglist:
                            self.cc.costdf.loc[self.cc.costdf['ingredient'] == clean_ingredient, 'ingredient list'] = ",".join(inglist)
                            self.df.loc[self.df['ingredient'] == clean_ingredient, 'ingredient list'] = ",".join(inglist)
                    except:
                        inglist = []
                
                if inglist:
                    # Format ingredients as HTML list with highlighting for specified ingredients
                    # Create a formatted list with bold and italics for matched ingredients
                    formatted_ingredients_parts = []
                    for ing in inglist:
                        if highlighted_ingredients and ing in highlighted_ingredients:
                            # Bold and italicize matched ingredients
                            formatted_ingredients_parts.append(f"<b><i>{ing}</i></b>")
                        else:
                            formatted_ingredients_parts.append(ing)
                    
                    formatted_ingredients = ", ".join(formatted_ingredients_parts)

                    # HTML widget gives better formatting control and handles overflow better
                    inglist_widget = widgets.HTML(
                        value=f'INGREDIENTS: {formatted_ingredients}',
                        layout=widgets.Layout(
                            width='60%',
                            overflow='auto',  # Allow scrolling if needed
                            flex='1 1 auto'   # Grow and shrink to fill available space
                        )
                    )
                    
                    if len(inglist) > 3:
                        if allergen_widget is None:
                            row_widgets.append(item_widget)
                        else:
                            row_widgets.append(widgets.VBox([item_widget, allergen_widget], layout=widgets.Layout(
                                width=f'{label_width}px'
                            )))
                        row_widgets.append(inglist_widget)
                    else:
                        if allergen_widget is None:
                            row_widgets = [item_widget]
                        else:
                            row_widgets = [item_widget, allergen_widget]
                        row_widgets.append(inglist_widget)
            
            # Ensure row_widgets has something in it
            if len(row_widgets) == 0:
                if allergen_widget is None:
                    row_widgets = [item_widget]
                else:
                    row_widgets = [item_widget, allergen_widget]
                
                # Add empty placeholder for simple ingredients
                row_widgets.append(widgets.Label(
                    layout=widgets.Layout(height=button_height, flex='1 1 auto')
                ))
            
            # Create a HBox for the row and add to rows list
            border_style = '2px dotted gray'
  
            highlight_row = False
            if row.get('highlight', False):
                highlight_row = True
            elif highlighted_ingredients and inglist:
                if any(ing in highlighted_ingredients for ing in inglist):
                    highlight_row = True
            
            # Create a border style based on whether the row should be highlighted
            border_style = '2px solid #FFD700' if highlight_row else '2px dotted gray'
            
            # Create box layout for the row without border
            box_layout = widgets.Layout(
                align_items='flex-start',
                display='flex',
                width='100%'
            )
            
            # Apply the border to the appropriate widget
            row_hbox = None
            if inglist_widget is None or highlight_row == False:
                # Apply border to the entire row's box layout if there's no ingredient list
                box_layout.border = border_style
                row_hbox = widgets.HBox(row_widgets, layout=box_layout)
            else:
                # Apply border just to the ingredient list widget
                row_widgets[-1].layout.border = border_style
                box_layout.border = '2px dotted gray'
                row_hbox = widgets.HBox(row_widgets, layout=box_layout)
                
            rows.append(row_hbox)
        
        # Create a VBox for all rows
        rows_vbox = widgets.VBox(rows)
        
        # Combine with the header row
        display_layout = widgets.VBox([header_hbox, rows_vbox])
        
        # Clear previous output and display the new layout
        with self.output:
            self.output.clear_output(wait=True)
            display(display_layout)
    
    def make_on_click(self, ingredient):
        """Create an on_click handler for a specific ingredient"""
        def on_click(button):
            # Add to search history
            self.search_history.append(ingredient)
            
            # Look up the ingredient
            self.lookup_name(ingredient)
            
            # If we have a trigger, call it to ensure allergen highlighting is applied
            if self.trigger:
                self.trigger(ingredient)
            else:
                # Update the display
                self.update_display()
            
        return on_click
    
    def on_back_click(self, button):
        """Handle back button click"""
        if len(self.search_history) > 1:
            self.search_history.pop()  # Remove current
            previous = self.search_history.pop()  # Get previous
            
            # Look up the previous item
            self.lookup_name(previous)
            
            # If we have a trigger, call it to ensure allergen highlighting is applied
            if self.trigger:
                self.trigger(previous)
            else:
                # Update the display
                self.update_display()
    
    def lookup_name(self, lookup):
        """Look up an ingredient or recipe by name"""
        # Set the DataFrame
        self.setdf(lookup)
        
        # Update search history
        if self.search_history:
            if lookup != self.search_history[-1]:
                self.search_history.append(lookup)


def main():
    """Main function to initialize and display the menu viewer"""
    # Create viewer
    viewer = MenuViewer()
    
    # Display the viewer
    viewer.display()

if __name__ == "__main__":
    main()
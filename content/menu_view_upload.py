import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display, clear_output, HTML
import os
from df_functions import *
from utils import get_xlsx_files
import io

allergen_icons = {
    'gluten': '<svg height="16" width="16"><polygon points="8,2 12,9 4,9" fill="#f5d742" stroke="#333" stroke-width="1"/><polygon points="8,7 13,15 3,15" fill="#f5d742" stroke="#333" stroke-width="1"/></svg>',
    'dairy': '<svg height="16" width="16"><rect x="2" y="2" width="12" height="12" fill="#ffffff" stroke="#333" stroke-width="1" rx="2"/></svg>',
    'egg': '<svg height="16" width="16"><ellipse cx="8" cy="8" rx="6" ry="8" fill="#ffefc1" stroke="#333" stroke-width="1"/><ellipse cx="8" cy="5" rx="3" ry="2" fill="#fffaf0" stroke="#333" stroke-width="0.5"/></svg>',
    'soy': '<svg height="16" width="16"><path d="M8,2 C10,2 12,4 12,7 C12,10 10,12 8,14 C6,12 4,10 4,7 C4,4 6,2 8,2 Z" fill="#9de24f" stroke="#333" stroke-width="1"/></svg>',
    'fish': '<svg height="16" width="16"><path d="M3,8 C5,4 9,4 12,8 C9,12 5,12 3,8 Z" fill="#a4dbf5" stroke="#333" stroke-width="1"/><polygon points="12,8 16,5 16,11" fill="#a4dbf5" stroke="#333" stroke-width="1"/></svg>',
    'shellfish': '<svg height="16" width="16"><path d="M2,10 C2,6 6,6 8,8 C10,6 14,6 14,10" fill="none" stroke="#ffb6c1" stroke-width="3" stroke-linecap="round"/></svg>',
    'tree-nut': '<svg height="16" width="16"><polygon points="8,2 14,14 2,14" fill="#d2b48c" stroke="#333" stroke-width="1"/></svg>',
    'peanut': '<svg height="16" width="16"><ellipse cx="5" cy="8" rx="4" ry="6" fill="#e6c98a" stroke="#333" stroke-width="1"/><ellipse cx="11" cy="8" rx="4" ry="6" fill="#e6c98a" stroke="#333" stroke-width="1"/></svg>',
    'poultry': '<svg height="16" width="16"><path d="M3,3 L13,8 L3,13 Z" fill="#ffd6a5" stroke="#333" stroke-width="1"/></svg>',
    'sesame': '<svg height="16" width="16"><circle cx="8" cy="8" r="7" fill="#f9e076" stroke="#333" stroke-width="1"/><circle cx="8" cy="8" r="3" fill="#e6ca46" stroke="#333" stroke-width="1"/></svg>'
}

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
        
        # Set up file selection UI with upload functionality
        self.setup_file_selector_with_upload()
        
        # Set up main UI components
        self.setup_menu_interface()
        
        # Try to load default database
        self.try_load_default_database()
    
    def setup_file_selector_with_upload(self):
        """Set up the file selection UI components with file upload functionality"""
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
        
        # Create file upload widget
        self.upload_widget = widgets.FileUpload(
            accept='.xlsx, .csv',
            multiple=False,
            description='Upload:',
            layout=widgets.Layout(width='300px')
        )
        self.upload_widget.observe(self.on_file_upload, names='value')
        
        # Create status label
        self.selected_file_label = widgets.Label()
        
        # Update dropdown with available files
        self.update_dropdown()
        
        # Assemble file selector with upload functionality
        self.file_selector = widgets.VBox([
            widgets.HTML(value="<h3>File Selection</h3>"),
            widgets.HBox([
                widgets.VBox([
                    widgets.HBox([self.dropdown, self.refresh_button]),
                    widgets.HBox([self.text_box])
                ]),
                widgets.VBox([
                    self.upload_widget
                ])
            ]),
            self.selected_file_label
        ], layout={'border': '1px solid lightgray', 'padding': '10px', 'margin': '5px'})
    
    def on_file_upload(self, change):
        """Handle file upload events"""
        if not change['new']:
            return
        
        # Get uploaded file content - fix for different FileUpload widget return types
        uploaded_files = change['new']
        
        # Check if it's a dictionary (some environments) or tuple/list (JupyterLite)
        if isinstance(uploaded_files, dict):
            # Dictionary format
            for file_key, file_data in uploaded_files.items():
                file_name = file_data['metadata']['name']
                file_content = file_data['content']
                
                # Process based on file extension
                if file_name.endswith('.xlsx'):
                    self.process_excel_upload(file_name, file_content)
                elif file_name.endswith('.csv'):
                    self.process_csv_upload(file_name, file_content)
                else:
                    self.selected_file_label.value = f'Unsupported file type: {file_name}'
                
                # Only process the first file if multiple files were uploaded
                break
        else:
            # List or tuple format in JupyterLite
            if len(uploaded_files) > 0:
                file_obj = uploaded_files[0]
                
                # Access file information directly from the object
                file_name = file_obj.name
                file_content = file_obj.content
                
                # Process based on file extension
                if file_name.endswith('.xlsx'):
                    self.process_excel_upload(file_name, file_content)
                elif file_name.endswith('.csv'):
                    self.process_csv_upload(file_name, file_content)
                else:
                    self.selected_file_label.value = f'Unsupported file type: {file_name}'
    
    def process_excel_upload(self, file_name, file_content):
        """Process uploaded Excel file"""
        try:
            # Save the uploaded file to the current directory
            with open(file_name, 'wb') as f:
                f.write(file_content)
            
            # Load the file using CostCalculator
            self.read_file(file_name)
            
            # Update dropdown to include the new file
            self.update_dropdown()
            
        except Exception as e:
            self.selected_file_label.value = f'Error processing Excel file: {str(e)}'
    
    def process_csv_upload(self, file_name, file_content):
        """Process uploaded CSV file and convert to Excel format"""
        try:
            # Convert CSV content to DataFrame
            csv_data = pd.read_csv(io.BytesIO(file_content))
            
            # Generate an Excel file name
            excel_file_name = file_name.rsplit('.', 1)[0] + '.xlsx'
            
            # Create Excel file from CSV data
            with pd.ExcelWriter(excel_file_name) as writer:
                csv_data.to_excel(writer, sheet_name='Sheet1', index=False)
            
            # Load the file using CostCalculator
            self.read_file(excel_file_name)
            
            # Update dropdown to include the new file
            self.update_dropdown()
            
        except Exception as e:
            self.selected_file_label.value = f'Error processing CSV file: {str(e)}'
    
    def setup_menu_interface(self):
        """Set up the main menu viewing interface"""
        # Create search input
        if self.cc and 'nickname' in self.cc.uni_g.columns:
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
        onlyrecipes = ingrs.difference(nicks)
        self.searchinput = widgets.Combobox(
            placeholder='ingredient/item',
            options=tuple(onlyrecipes),
            description='Search:',
            ensure_option=False,
            disabled=False,
            style=self.fontstyle
        )
        self.searchinput.observe(self.update_search, names='value')
        
        # Create main display area
        self.dfdisplay = widgets.Output(layout={'overflow': 'scroll', 'border': '1px solid black', 'min_height': '400px'})
        self.df_widget = MenuDisplayWidget(pd.DataFrame(), cc=self.cc, output=self.dfdisplay, trigger=self.trigger_update, viewer=self)
        
        # Get references to back button and ingredient accordion
        self.backbutton = self.df_widget.backbutton
        
        # Create top display area
        self.top_display = widgets.VBox([
            widgets.HBox([self.backbutton, self.searchinput]),
            self.dfdisplay
        ], layout={'border': '2px solid green'})
        
        self.allergen_title = widgets.HTML(value="<h3>Highlight by Allergens:</h3>")
        self.allergen_checkboxes = []
        self.allergen_icon_boxes = []

        # Create allergen checkboxes with icons
        for allergen in allergen_icons:
            # Create HTML widget with icon and text
            icon_html = widgets.HTML(
                value=f"{allergen_icons[allergen]} {allergen.capitalize()}",
                layout=widgets.Layout(width='120px', margin='0 5px')
            )
            
            # Create checkbox
            checkbox = widgets.Checkbox(
                value=False, 
                indent=False,
                layout=widgets.Layout(width='24px', margin='0 5px')
            )
            checkbox.observe(self.on_allergen_toggle, names='value')
            checkbox.description = allergen  # Store allergen name in description attribute
            
            # Create container for icon and checkbox
            container = widgets.HBox([
                checkbox, 
                icon_html
            ], layout=widgets.Layout(
                margin='0 15px 0 0',
                align_items='center'
            ))
            
            self.allergen_checkboxes.append(checkbox)
            self.allergen_icon_boxes.append(container)

        # Arrange checkboxes into rows with fewer items per row
        allergen_rows = [
            widgets.HBox(
                self.allergen_icon_boxes[i:i+3], 
                layout=widgets.Layout(flex_wrap='wrap', align_items='center')
            ) 
            for i in range(0, len(self.allergen_icon_boxes), 3)
        ]

        self.allergen_box = widgets.VBox(
            [self.allergen_title] + allergen_rows,
            layout=widgets.Layout(
                margin='0',
                padding='10px',
                border='1px solid lightgray'
            )
        )
        # Create ingredient highlighting section
        self.setup_ingredient_highlight_section()
        
        # Create menu buttons
        menulist = ['breakfast', 'lunch', 'dinner', 'desserts']
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
    # Add this method to the MenuViewer class
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
            continuous_update=True,  # Changed to True for dynamic matching
            layout=widgets.Layout(width='300px')
        )
        
        # Add observer for text changes to implement dynamic matching
        self.ingredient_input.observe(self.on_ingredient_input_change, names='value')
        
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
        
        # Create container for matching ingredient buttons
        self.matching_ingredients_container = widgets.Box(
            [], 
            layout=widgets.Layout(
                display='flex',
                flex_flow='row wrap',
                width='100%',
                margin='5px 0'
            )
        )
        
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
            self.matching_ingredients_container,  # Add the matching ingredients container
            self.ingredient_chips_container
        ], layout={'border': '1px solid lightgray', 'padding': '5px', 'margin': '5px'})
    
    def on_ingredient_input_change(self, change):
        """Handle changes to the ingredient input field and create matching buttons"""
        # Get the current input text
        input_text = change['new'].strip().lower()
        
        # Clear the matching ingredients container
        self.matching_ingredients_container.children = []
        
        # If input is empty or too short, don't show any matches
        if not input_text or len(input_text) < 2:
            return
        
        # Get valid ingredients that match the input text
        valid_ingredients = self.df_widget.simple_ingredients
        matching_ingredients = [ing for ing in self.df_widget.simple_ingredients
                            if input_text in ing.lower() ]
        
        # Only create buttons if there are between 1 and 10 matches (inclusive)
        if 1 <= len(matching_ingredients) <= 10:
            matching_buttons = []
            
            for ing in matching_ingredients:
                # Create button with ingredient name
                btn = widgets.Button(
                    description=ing,
                    layout=widgets.Layout(
                        margin='3px',
                        max_width='200px',
                        overflow='hidden',
                        text_overflow='ellipsis'
                    ),
                    tooltip=ing
                )
                
                # Set up click handler to add this ingredient
                btn.on_click(lambda b, ing=ing: self.add_highlighted_ingredient(ing))
                
                matching_buttons.append(btn)
            
            # Update the matching ingredients container
            self.matching_ingredients_container.children = matching_buttons


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
        
    def add_highlighted_ingredient(self, ingredient):
        """Add an ingredient to the highlighted ingredients list"""
        if ingredient not in self.highlighted_ingredients:
            self.highlighted_ingredients.append(ingredient)
            self.update_ingredient_chips()
            self.apply_ingredient_highlighting()
            
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
        self.ingredient_input.value = ""
    
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
            self.searchinput.options = tuple(ingrs.difference(nicks))
            self.df_widget.all_ingredients = self.allvals
            self.df_widget.simple_ingredients = nicks.intersection(ingrs)
            
            # Update ingredient input options
            self.ingredient_input.options = tuple(nicks.intersection(ingrs))
    
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
        # If we have a recipe displayed, update with highlighted ingredients
        if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
            # Store current recipe name
            recipe_name = self.df_widget.last_lookup
            
            # Reload the recipe to show all ingredients
            self.df_widget.lookup_name(recipe_name)
            
            # Make a copy of the current DataFrame
            highlighted_df = self.df_widget.df.copy()
            
            # Add highlighting flag for allergens and initialize as False
            highlighted_df['allergen_highlight'] = False
            
            # Initialize empty allergen ingredients set
            allergen_ingredients = set()
            
            # Only process allergen highlighting if there are selected allergens
            if self.selected_allergens:
                # Check each ingredient in the recipe
                for i, row in highlighted_df.iloc[1:].iterrows():
                    ingredient = row.get('ingredient', '')
                    ingredient_allergens = set()
                    
                    # Get allergens for this ingredient
                    if 'allergen' in row and isinstance(row['allergen'], str):
                        ingredient_allergens = {a.strip().lower() for a in row['allergen'].split(',')}
                    
                    # If any selected allergen is in this ingredient's allergens, mark for highlighting
                    if any(a.lower() in ingredient_allergens for a in self.selected_allergens):
                        highlighted_df.at[i, 'allergen_highlight'] = True
                        allergen_ingredients.add(ingredient)
                    
                    # Also check for sub-ingredients with allergens
                    if not self.cc.is_ingredient(ingredient) and len(self.cc.get_children(ingredient)) > 0:
                        # Get flattened ingredients
                        ing_list = []
                        try:
                            if isinstance(row.get('ingredient list'), str):
                                ing_list = row['ingredient list'].split(',')
                            else:
                                flat_ingredients = self.cc.flatten_recipe(ingredient, row['quantity'])
                                ing_list = flat_ingredients['ingredient'].tolist()
                            
                            # Get ingredients with allergens
                            sub_allergen_ingredients = self.df_widget.get_allergen_ingredients(
                                ing_list, self.selected_allergens)
                            
                            # If any sub-ingredients have allergens, highlight this row
                            if sub_allergen_ingredients:
                                highlighted_df.at[i, 'allergen_highlight'] = True
                                allergen_ingredients.update(sub_allergen_ingredients)
                        except:
                            pass
            
            # Store allergen ingredients for ingredient list highlighting
            # Even when empty, we need to set this to ensure previous highlighting is cleared
            highlighted_df['allergen_ingredients'] = str(allergen_ingredients)
            
            # Update the display widget with the highlighted DataFrame
            self.df_widget.df = highlighted_df
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
        self.simple_ingredients = set()
        if self.cc and 'nickname' in self.cc.uni_g.columns:
            nicks = set(self.cc.uni_g['nickname'].dropna().unique())
            ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
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
            if mydf.at[0, 'ingredient'] in ['breakfast', 'lunch', 'dinner', 'desserts']:
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

        # for col in self.df.columns:
        #     if col in ['allergen']:
        #         header_widgets.append(widgets.Label(
        #             value=col.capitalize(), 
        #             layout=widgets.Layout(width=f'{max_lengths.get(col, min_button_width)}px', height=button_height, flex='0 0 auto')
        #         ))
        for col in self.df.columns:
            if col in ['allergen']:
                header_widgets.append(widgets.HTML(
                    value=f"<strong>{col.capitalize()}</strong>", 
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
                    if row['ingredient'] in ['breakfast', 'lunch', 'dinner', 'desserts']:
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
                # For the allergen column (in the existing code)
                elif col in ['allergen']:
                    label_width = max(min_button_width, max_lengths.get(col, min_button_width))
                    
                    # Highlight allergens if the value starts with warning emoji
                    allergen_value = str(row[col])
                    label_style = {}
                    # if allergen_value.startswith('⚠️'):
                    #     label_style = {'background_color': '#FFEE22'}
                    
                    if len(allergen_value) > 0:
                        # Format the allergen text with icons
                        formatted_allergen = self.format_allergen_text(allergen_value)
                        
                        # HTML widget gives better formatting control and handles overflow better
                        allergen_widget = widgets.HTML(
                            value=formatted_allergen,
                            layout=widgets.Layout(
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
                            #self.cc.costdf.loc[self.cc.costdf['ingredient'] == clean_ingredient, 'ingredient list'] = ",".join(inglist)
                            if 'ingredient list' not in self.cc.costdf.columns:
                                self.cc.costdf['ingredient list'] = None
                            self.cc.costdf.loc[self.cc.costdf['ingredient'] == clean_ingredient, 'ingredient list'] = ",".join(inglist)
                            if 'ingredient list' not in self.df.columns:
                                self.df['ingredient list'] = None
                            self.df.loc[self.df['ingredient'] == clean_ingredient, 'ingredient list'] = ",".join(inglist)
                    except:
                        inglist = []
                        
                if inglist:
                    # Format ingredients as HTML list with highlighting
                    formatted_ingredients_parts = []
                    
                    # Get highlighted ingredients (from ingredient highlighting)
                    highlighted_ingredients = self.viewer.highlighted_ingredients if self.viewer else []
                    
                    # Get allergen ingredients
                    allergen_ingredients = set()
                    if 'allergen_ingredients' in self.df.columns:
                        allergen_str = row.get('allergen_ingredients', '').strip('{}')
                        if allergen_str:
                            allergen_ingredients = {ing.strip().strip("'") for ing in allergen_str.split(',')}
                    
                    # Format each ingredient with a unified highlighting style
                    for ing in inglist:
                        ing_formatted = ing
                        
                        # Check if ingredient should be highlighted (either by ingredient or allergen)
                        should_highlight = (highlighted_ingredients and ing in highlighted_ingredients) or \
                                        (allergen_ingredients and ing in allergen_ingredients)
                        
                        # Apply unified highlighting style: bold + highlighted background
                         # Apply unified highlighting style: bold + outline instead of background
                        if should_highlight:
                            style_attr = ' style="font-weight: bold; border: 2px solid #FFee22; border-radius: 3px; padding: 0 2px;"'
                            ing_formatted = f"<span{style_attr}>{ing}</span>"
                        
                        formatted_ingredients_parts.append(ing_formatted)
                    
                    formatted_ingredients = ", ".join(formatted_ingredients_parts)
                    
                    # Create the ingredient list widget
                    inglist_widget = widgets.HTML(
                        value=f'INGREDIENTS: {formatted_ingredients}',
                        layout=widgets.Layout(
                            width='70%',
                            overflow='auto',  # Allow scrolling if needed
                            flex='1 1 auto'   # Grow and shrink to fill available space
                        )
                    )
                    
                    if len(inglist) > 3:
                        if allergen_widget is None:
                            row_widgets.append(item_widget)
                        else:
                            row_widgets.append(widgets.VBox([item_widget, allergen_widget], layout=widgets.Layout(
                                #width=f'{label_width}px'
                                width='30%'
                            )))
                        row_widgets.append(inglist_widget)
                    else:
                        if allergen_widget is None:
                            row_widgets = [item_widget]
                        else:
                            #row_widgets = [item_widget, allergen_widget]
                            row_widgets = [widgets.HBox([item_widget, allergen_widget], 
                                   layout=widgets.Layout(width='30%'))]
                        row_widgets.append(inglist_widget)
            
            # Ensure row_widgets has something in it
            if len(row_widgets) == 0:
                if allergen_widget is None:
                    #row_widgets = [item_widget]
                    row_widgets = [widgets.HBox([item_widget], layout=widgets.Layout(width='30%'))]
                else:
                    #row_widgets = [item_widget, allergen_widget]
                    row_widgets = [widgets.HBox([item_widget, allergen_widget], layout=widgets.Layout(width='30%'))]
                
                # Add empty placeholder for simple ingredients
                row_widgets.append(widgets.Label(
                    #layout=widgets.Layout(height=button_height, flex='1 1 auto')
                    layout=widgets.Layout(height=button_height, flex='1 1 auto', width='70%')
                ))
            
            # Create a HBox for the row and add to rows list
            border_style = '2px dotted gray'
            
            highlight_row = False
            if row.get('highlight', False):
                # Ingredient highlighting
                highlight_row = True
            elif row.get('allergen_highlight', False):
                # Allergen highlighting
                highlight_row = True
            elif highlighted_ingredients and inglist:
                # Ingredient list matching
                if any(ing in highlighted_ingredients for ing in inglist):
                    highlight_row = True

            # Use a single consistent border style for all highlighted rows
            border_style = '2px dotted #FFEE22' if highlight_row else '2px dotted gray'
                                    
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
                
    # Add this function to the MenuDisplayWidget class
    def format_allergen_text(self, allergen_text):
        """Format allergen text with icons"""
        if not allergen_text or not isinstance(allergen_text, str):
            return ""
        
        # Split the allergen text into individual allergens
        allergens = [a.strip().lower() for a in allergen_text.split(',')]
        formatted_parts = []
        
        # Add icon for each allergen if it exists in our icon dictionary
        for allergen in allergens:
            allergen_clean = allergen.lower().strip()
            if allergen_clean in allergen_icons:
                formatted_parts.append(f"<span style='white-space: nowrap;'>{allergen_icons[allergen_clean]} {allergen.capitalize()}</span>")
                #formatted_parts.append(f"{allergen_icons[allergen_clean]} {allergen.capitalize()}")
            else:
                formatted_parts.append(allergen.capitalize())
        
        # Join with commas
        return ", ".join(formatted_parts)
    
    def get_allergen_ingredients(self, ingredients, selected_allergens):
        """Identify ingredients that contain selected allergens"""
        allergen_ingredients = set()
        
        # For each ingredient, check if it contains any of the selected allergens
        for ing in ingredients:
            # Get allergens for this ingredient
            ingredient_allergens = self.cc.findNset_allergens(ing)
            
            # Convert to lowercase for case-insensitive comparison
            ingredient_allergens_lower = [a.strip().lower() for a in ingredient_allergens]
            
            # If any selected allergen is in this ingredient's allergens, add to set
            if any(a.lower() in ingredient_allergens_lower for a in selected_allergens):
                allergen_ingredients.add(ing)
            
        return allergen_ingredients

def main():
    """Main function to initialize and display the menu viewer"""
    # Create viewer
    viewer = MenuViewer()
    
    # Display the viewer
    viewer.display()

if __name__ == "__main__":
    main()
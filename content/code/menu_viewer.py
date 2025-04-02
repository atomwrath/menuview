import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
import os
import io
from df_functions import *
from utils import get_xlsx_files
from menu_styles_components import *
from menu_display_widget import MenuDisplayWidget

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
        
        # Create refresh button
        self.refresh_button = create_styled_button(
            'Refresh',
            self.on_refresh_button_clicked,
            tooltip='Refresh file list',
            style=''
        )
        self.refresh_button.icon = 'refresh'
        
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
            widgets.HTML(value=HTML_TEMPLATES['heading'].format(
                style=HTML_STYLES['heading'], 
                text="File Selection"
            )),
            widgets.HBox([
                widgets.VBox([
                    widgets.HBox([self.dropdown, self.refresh_button])
                ]),
                widgets.VBox([
                    self.upload_widget
                ])
            ]),
            self.selected_file_label
        ], layout=LAYOUTS['file_selector'])
    
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
                style=WIDGET_STYLES['standard_font']
            )
            self.searchinput.observe(self.update_search, names='value')
        else:
            self.searchinput = widgets.Combobox(
                placeholder='ingredient/item',
                options=tuple([]),
                description='Search:',
                ensure_option=False,
                disabled=False,
                style=WIDGET_STYLES['standard_font']
            )
            self.searchinput.observe(self.update_search, names='value')
        
        # Create main display area
        self.dfdisplay = widgets.Output(layout=LAYOUTS['output_display'])
        self.df_widget = MenuDisplayWidget(pd.DataFrame(), cc=self.cc, output=self.dfdisplay, trigger=self.trigger_update, viewer=self)
        
        # Get references to back button and ingredient accordion
        self.backbutton = self.df_widget.backbutton
        
        # Create top display area
        self.top_display = widgets.VBox([
            widgets.HBox([self.backbutton, self.searchinput]),
            self.dfdisplay
        ], layout=LAYOUTS['top_display'])
        
        # Setup combined highlighting section (combines allergen and ingredient highlighting)
        self.setup_highlighting_section()
        
        # Create menu buttons
        menulist = ['breakfast', 'lunch', 'dinner', 'desserts']
        menubuttons = []
        for menu in menulist:
            button = create_styled_button(
                menu.capitalize(), 
                self.df_widget.make_on_click(menu),
                style='primary',
                styledict=dict(font_weight='bold', font_variant="small-caps")
            )
            menubuttons.append(button)
        
        self.menubutton_hbox = widgets.HBox(menubuttons, layout=widgets.Layout(width='auto'))
        
        # Create title
        self.title = widgets.HTML(value=HTML_TEMPLATES['title'].format(text="Menu Viewer"))
        
        # Assemble the whole interface
        self.vbox = widgets.VBox([
            self.file_selector,
            self.title,
            self.highlighting_container,  # Use the combined highlighting container
            self.menubutton_hbox,
            self.top_display
        ])
        
    def setup_highlighting_section(self):
        """Set up the combined highlighting section (allergens and ingredients)"""
        # Create highlighting section title
        self.highlighting_title = widgets.HTML(
            value=HTML_TEMPLATES['heading'].format(
                style=HTML_STYLES['heading'], 
                text="Highlight Items:"
            )
        )
        
        # Create allergen title
        self.allergen_title = widgets.HTML(
            value=HTML_TEMPLATES['subheading'].format(
                style=HTML_STYLES['subheading'], 
                text="By Allergen:"
            )
        )
        # Create clear button
        self.clear_highlights_button = create_styled_button(
            'Clear All Highlights',
            self.on_clear_all_highlights,
            style='warning'
        )
        
         # Title row with clear button
        title_row = widgets.HBox([
            self.highlighting_title,
            self.clear_highlights_button
        ], layout=widgets.Layout(
            justify_content='space-between',
            align_items='center',
            width='100%'
        ))
        
        self.allergen_checkboxes = []
        self.allergen_icon_boxes = []
        
        # Create allergen checkboxes with icons in a single row that wraps
        for allergen in my_allergens:
            # Create allergen checkbox components
            checkbox, icon_html, container = create_allergen_checkbox(allergen)
            
            # Define observer that updates the text style when toggled
            def on_checkbox_toggle(change, allergen=allergen, icon_html=icon_html):
                if change['new']:  # Checkbox is checked
                    icon_html.value = HTML_TEMPLATES['highlighted_allergen'].format(
                        style=HTML_STYLES['allergen'],
                        icon=allergen_icons[allergen],
                        text=allergen.capitalize()
                    )
                else:  # Checkbox is unchecked
                    icon_html.value = HTML_TEMPLATES['normal_allergen'].format(
                        style=HTML_STYLES['nowrap'],
                        icon=allergen_icons[allergen],
                        text=allergen.capitalize()
                    )
            
            # Observe both the allergen toggle for filtering and our custom toggle for styling
            checkbox.observe(on_checkbox_toggle, names='value')
            checkbox.observe(self.on_allergen_toggle, names='value')
            
            self.allergen_checkboxes.append(checkbox)
            self.allergen_icon_boxes.append(container)

        # Create a single row container for allergen checkboxes that wraps
        self.allergen_box = widgets.Box(
            self.allergen_icon_boxes,
            layout=LAYOUTS['allergen_chips']
        )
        
        # Create ingredient highlighting section
        self.ingredient_title = widgets.HTML(
            value=HTML_TEMPLATES['subheading'].format(
                style=HTML_STYLES['subheading'], 
                text="By Ingredient:"
            )
        )
        
        # # Create ingredient input with autocomplete
        self.ingredient_input = widgets.Combobox(
            placeholder='Enter ingredient to highlight',
            options=tuple(), # Will be populated after loading data
            description='Ingredient:',
            ensure_option=False,
            continuous_update=True,
            layout=widgets.Layout(width='300px')
        )

        # Add observer for text changes to implement dynamic matching
        self.ingredient_input.observe(self.on_ingredient_input_change, names='value')
        
        # Create container for ingredient chips
        self.ingredient_chips_container = widgets.HBox([], layout=widgets.Layout(flex_wrap='wrap'))
        
        # Create container for matching ingredient buttons
        self.matching_ingredients_container = widgets.Box(
            [], 
            layout=LAYOUTS['matching_ingredients']
        )
        
        # Assemble input row
        ingredient_input_row = widgets.HBox([
            self.ingredient_input
            #self.add_ingredient_button,
        ])
        
        # Assemble ingredient section
        ingredient_section = widgets.VBox([
            self.ingredient_title,
            ingredient_input_row,
            self.matching_ingredients_container,
            self.ingredient_chips_container
        ], layout=LAYOUTS['ingredient_container_box'])
        
        # Assemble allergen section
        allergen_section = widgets.VBox([
            self.allergen_title,
            self.allergen_box
        ], layout=LAYOUTS['allergen_container'])
        
        # Create the combined highlighting container with tighter spacing
        self.highlighting_container = widgets.VBox([
            title_row,
            allergen_section,
            ingredient_section
        ], layout=LAYOUTS['highlighting_container'])
        
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
        matching_ingredients = [ing for ing in self.df_widget.simple_ingredients
                            if input_text in ing.lower() and ing not in self.highlighted_ingredients]
        
        # Only create buttons if there are between 1 and 10 matches (inclusive)
        if 1 <= len(matching_ingredients) <= 10:
            matching_buttons = []
            
            for ing in matching_ingredients:
                # Create matching ingredient button with dynamic handler
                def get_handler(ingredient):
                    return lambda b: self.add_highlighted_ingredient(ingredient)
                
                btn = create_matching_ingredient_button(
                    ing, 
                    False,  # Not highlighted since we filtered these out above
                    get_handler(ing)
                )
                
                matching_buttons.append(btn)
            
            # Update the matching ingredients container
            self.matching_ingredients_container.children = matching_buttons
        
            
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
            self.ingredient_input.style = WIDGET_STYLES['warning_text']
            
            # Reset after 2 seconds
            import threading
            def reset_description():
                self.ingredient_input.description = original_description
                self.ingredient_input.style = {}
            
            timer = threading.Timer(2.0, reset_description)
            timer.start()
    
    def update_ingredient_chips(self):
        """Update the ingredient chips display"""
        chips = []
        for ing in self.highlighted_ingredients:
            # Create remove handler for this ingredient
            def get_remove_handler(ingredient):
                return lambda b: self.remove_highlighted_ingredient(ingredient)
                
            chip = create_ingredient_chip(ing, get_remove_handler(ing))
            chips.append(chip)
            
        self.ingredient_chips_container.children = chips
        self.apply_ingredient_highlighting()
        
    def remove_highlighted_ingredient(self, ingredient):
        """Remove an ingredient from the highlighted ingredients list"""
        if ingredient in self.highlighted_ingredients:
            self.highlighted_ingredients.remove(ingredient)
            self.update_ingredient_chips()
            
            # Check if this ingredient should be added back to the matching ingredients 
            # if it matches the current search
            input_text = self.ingredient_input.value.strip().lower()
            if input_text and len(input_text) >= 2 and input_text in ingredient.lower():
                # Update the matching ingredients display to include this ingredient
                self.on_ingredient_input_change({'new': input_text})
            
            self.apply_ingredient_highlighting()
        
    def add_highlighted_ingredient(self, ingredient):
        """Add an ingredient to the highlighted ingredients list"""
        if ingredient not in self.highlighted_ingredients:
            # Add to highlighted ingredients list
            self.highlighted_ingredients.append(ingredient)
            self.update_ingredient_chips()
            self.apply_ingredient_highlighting()
            
            # Remove this ingredient from the matching ingredients buttons
            current_buttons = list(self.matching_ingredients_container.children)
            updated_buttons = [btn for btn in current_buttons if btn.description != ingredient]
            self.matching_ingredients_container.children = updated_buttons
    
    def on_clear_all_highlights(self, b):
        """Handle clearing all highlighted ingredients"""
        # Update selected allergens list
        for cb in self.allergen_checkboxes:
            cb.value = False
        # Apply the filtering
        self.highlighted_ingredients = []
        self.update_ingredient_chips()
        # Check if there's a current search text to refresh matching ingredients
        input_text = self.ingredient_input.value.strip().lower()
        if input_text and len(input_text) >= 2:
            # This will refresh the matching ingredients display
            self.on_ingredient_input_change({'new': input_text})
        self.apply_ingredient_highlighting()
        #self.ingredient_input.value = ""
    
    def get_valid_ingredients(self):
        """Get set of valid ingredients for highlighting"""
        return set(self.cc.costdf['ingredient'].dropna().unique())
    
    def update_dropdown(self):
        """Update dropdown options with available Excel files"""
        xlsx_files = get_xlsx_files()
        if xlsx_files:
            self.dropdown.options = xlsx_files
            self.dropdown.disabled = False
        else:
            self.dropdown.options = ['No .xlsx files found']
            self.dropdown.disabled = True
    
    def on_refresh_button_clicked(self, b):
        """Handle refresh button click"""
        self.update_dropdown()
    
    def on_dropdown_change(self, change):
        """Handle dropdown selection change"""
        if change['new'] != 'No .xlsx files found':
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
            change['owner'].style = WIDGET_STYLES['normal_text']  # Reset color if valid
            iname = change['new']
            self.df_widget.lookup_name(iname)
            
            # Apply allergen and ingredient highlighting to the new search result
            self.apply_allergen_highlighting()
            self.apply_ingredient_highlighting()
            
            self.df_widget.update_display()
        else:
            change['owner'].style = WIDGET_STYLES['warning_text']  # Show red if invalid
    
    def trigger_update(self, iname):
        """Handle updates triggered from the widget"""
        self.searchinput.value = iname
    
    def on_allergen_toggle(self, change):
        """Handle allergen checkbox toggles"""
        # Update selected allergens list
        self.selected_allergens = [cb.description for cb in self.allergen_checkboxes if cb.value]
        
        # Apply the filtering
        self.apply_allergen_highlighting()
    
    def apply_ingredient_highlighting(self):
        """Apply highlighting for selected ingredients"""
        # Skip if no ingredients to highlight
        if not self.highlighted_ingredients:
            # If there are no highlighted ingredients, we need to ensure any existing
            # highlighting is cleared but allergen highlighting remains
            if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
                filtered_df = self.df_widget.df.copy()
                filtered_df['highlight'] = False
                self.df_widget.df = filtered_df
                self.df_widget.update_display()
            return

        # If we have a recipe displayed, update with highlighted ingredients
        if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
            recipe_name = self.df_widget.last_lookup
            
            # Make a copy of the current DataFrame and add a highlighting flag
            # But preserve existing allergen highlighting
            filtered_df = self.df_widget.df.copy()
            
            # Initialize ingredient highlighting to false
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
    
    def apply_allergen_highlighting(self):
        """Apply allergen highlighting based on selected allergens"""
        # If we have a recipe displayed, update with highlighted ingredients
        if self.df_widget.df_type == 'recipe' and self.df_widget.last_lookup:
            # Store current recipe name
            recipe_name = self.df_widget.last_lookup
            
            # We need to carefully preserve any existing ingredient highlighting
            # Get the current DataFrame with any existing ingredient highlighting
            current_df = self.df_widget.df.copy()
            
            # Reload the recipe to get a clean copy with allergens
            self.df_widget.lookup_name(recipe_name)
            
            # Make a copy of the clean DataFrame
            highlighted_df = self.df_widget.df.copy()
            
            # Restore any existing ingredient highlighting
            if 'highlight' in current_df.columns:
                highlighted_df['highlight'] = current_df['highlight']
            else:
                highlighted_df['highlight'] = False
            
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
                    # We want unified highlighting between allergens and ingredients
                    if any(a.lower() in ingredient_allergens for a in self.selected_allergens):
                        highlighted_df.at[i, 'allergen_highlight'] = True
                        allergen_ingredients.add(ingredient)
                        
                        # Store specific matching allergens for bold highlighting
                        matching_allergens = [a for a in self.selected_allergens if a.lower() in ingredient_allergens]
                        if 'highlighted_allergens' not in highlighted_df.columns:
                            highlighted_df['highlighted_allergens'] = None
                        highlighted_df.at[i, 'highlighted_allergens'] = ','.join(matching_allergens)
                    
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


def main():
    """Main function to initialize and display the menu viewer"""
    # Create viewer
    viewer = MenuViewer()
    
    # Display the viewer
    viewer.display()

if __name__ == "__main__":
    main()
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
from df_functions import *
from menu_styles_components import *

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
        self.backbutton = create_styled_button('Back', disabled=True)
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
                    maxlen[col] = MIN_BUTTON_WIDTH  # Default width
            
            # Calculate widths based on column names
            cn_len = {c: 5 + 8 * len(str(c)) for c in self.df.columns}
    
            # Use the maximum of content width and column name width
            self.column_width = {c: max(maxlen.get(c, MIN_BUTTON_WIDTH), cn_len.get(c, MIN_BUTTON_WIDTH)) for c in self.df.columns}
            
            # Special case for recipe item column
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
        except:
            # Default if something goes wrong
            self.column_width = {c: MIN_BUTTON_WIDTH for c in self.df.columns}
    
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
        
        # Calculate maximum text length for each column
        max_lengths = {}
        for col in self.df.columns:
            try:
                max_lengths[col] = max(self.df[col].astype(str).map(len).max(), len(col)) * 8
            except:
                max_lengths[col] = MIN_BUTTON_WIDTH
        
        # Configure 'Back' button
        self.backbutton.layout.width = f'{max_lengths.get("ingredient", MIN_BUTTON_WIDTH)}px'
        if len(self.search_history) > 1:
            self.backbutton.on_click(self.on_back_click)
            self.backbutton.disabled = False
        else:
            self.backbutton.disabled = True
            
        # Create header row with standardized styling
        header_hbox = create_header_row(self.df.columns, max_lengths)
        
        # Create a list to hold row widgets
        rows = []
        
        # Get highlighted ingredients from the viewer
        highlighted_ingredients = []
        if self.viewer:
            highlighted_ingredients = self.viewer.highlighted_ingredients
        
        # First, calculate the maximum button width based on ingredients
        max_button_width = MIN_BUTTON_WIDTH
        for index, row in self.df.iterrows():
            if self.df_type == 'recipe':
                if index == 0:
                    continue  # Skip recipe title
                ingredient = row['ingredient']
            elif self.df_type == 'mentions':
                ingredient = row['item']
            else:
                continue
            
            # Calculate width needed for this ingredient text
            text_width = len(ingredient) * 8  # Approximate pixels per character
            max_button_width = max(max_button_width, text_width)
        # Add some padding to ensure no truncation
        max_button_width += 20
        # Use this width for all buttons
        button_width = max_button_width
        
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
                    item_widget = widgets.HTML(
                        value=HTML_TEMPLATES['recipe_title'].format(text=row['ingredient']),
                        layout=widgets.Layout(width=f'{button_width}px')
                    )
                ingredient = row['ingredient']
            elif self.df_type == 'mentions':
                ingredient = row['item']
            else:
                continue

            # Create ingredient list
            inglist = []
            
            if item_widget is None:
                # Determine if this row should be highlighted
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
                
                # Create the button with appropriate style
                button_click_handler = self.make_on_click(ingredient)
                item_widget = create_styled_button(
                    ingredient,
                    button_click_handler, 
                    f"View details for {ingredient}",
                    width=f'{button_width}px'
                )
                
                # Highlight if either ingredient or allergen highlighting is active
                if row.get('highlight', False) or row.get('allergen_highlight', False):
                    item_widget.style.button_color = HIGHLIGHT_COLOR

            row_widgets.append(item_widget)

            # Create labels for the other columns
            for col in self.df.columns:
                if col in ['ingredient', 'item', 'menu price']:
                    continue
                # For the allergen column
                elif col in ['allergen']:
                    allergen_value = str(row[col])
                    
                    if len(allergen_value) > 0:
                        # Get selected allergens from viewer
                        selected_allergens = self.viewer.selected_allergens if self.viewer else []
                        
                        # Format the allergen text with icons
                        formatted_allergen = format_allergen_text(allergen_value, selected_allergens)
                        
                        # HTML widget gives better formatting control and handles overflow better
                        allergen_widget = widgets.HTML(
                            value=formatted_allergen,
                            layout=widgets.Layout(
                                width='auto',
                                min_width='150px',
                                margin='0 10px',
                                height='auto'
                            )
                        )
                    else:
                        allergen_widget = None
            
            # Create ingredient list
            inglist = []
            ingredients_container = []
            if allergen_widget is not None:
                ingredients_container.append(allergen_widget)
            clean_ingredient = ingredient
                
            if not self.cc.is_ingredient(clean_ingredient) and len(self.cc.get_children(clean_ingredient)) > 1:
                # Get ingredient list
                if 'ingredient list' in self.df.columns and isinstance(row.get('ingredient list'), str):
                    inglist = row['ingredient list'].split(',')
                else:
                    try:
                        inglist = ingredients_by_weight(clean_ingredient, row['quantity'])
                        if inglist:
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
                        # Check if ingredient should be highlighted (either by ingredient or allergen)
                        should_highlight = (highlighted_ingredients and ing in highlighted_ingredients) or \
                                        (allergen_ingredients and ing in allergen_ingredients)
                        
                        # Get formatted HTML for this ingredient
                        formatted_ingredients_parts.append(get_highlighted_ingredient_html(ing, should_highlight))
                    
                    formatted_ingredients = ", ".join(formatted_ingredients_parts)
                    
                    inglist_widget = widgets.HTML(
                        value=HTML_TEMPLATES['ingredient_list'].format(ingredients=formatted_ingredients),
                        layout=LAYOUTS['ingredient_list']
                    )
                    ingredients_container.append(inglist_widget)
                # Add empty placeholder for simple ingredients
                else:
                    ingredients_container.append(widgets.Label(
                        layout=widgets.Layout(height=BUTTON_HEIGHT, flex='1 1 auto')
                    ))   
            else:
                # Add empty placeholder for simple ingredients
                ingredients_container.append(widgets.Label(
                    layout=widgets.Layout(height=BUTTON_HEIGHT, flex='1 1 auto')
                ))
            # Create VBox for ingredients with allergens above
            ingredients_vbox = widgets.VBox(
                ingredients_container,
                layout=LAYOUTS['ingredient_container']
            )
            row_widgets.append(ingredients_vbox)

            # Determine if this row should be highlighted
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

            # Use appropriate layout based on highlighting
            row_layout = LAYOUTS['highlighted_row'] if highlight_row else LAYOUTS['row']
                                        
            row_hbox = widgets.HBox(row_widgets, layout=row_layout)
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
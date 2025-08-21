import pandas as pd
import requests
import re
import json
import os
from costcalulator import CostCalculator

class ProductDataFetcher:
    """
    Class to fetch product information from Shamrock's website
    and integrate it with the CostCalculator
    """
    
    def __init__(self, cc=None):
        self.cc = cc if cc else CostCalculator()
        # Base URL
        self.base_url = "https://shop.shamrockfoodservice.com"
        # Headers for HTTP requests
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        
    def extract_product_data_from_html(self, html_content, product_id):
        """
        Extract product data from Shamrock's HTML page by looking for specific attribute patterns
        """
        # Initialize product info dictionary
        product_info = {
            'product_id': product_id,
            'name': None,
            'description': None,
            'ingredients': None,
            'allergens': None,
            'nutritional_info': None,
            'additional_info': {},
            'images': [],
            'categories': []
        }
        
        
        # Extract ingredients
        ingredients_match = re.search(r'"shamrock-standard_ingredients":"([^"]+)"', html_content)
        if ingredients_match:
            product_info['ingredients'] = ingredients_match.group(1).replace('\\u0026', '&')
        
        # Extract allergens - this is in JSON format within the HTML
        allergens_match = re.search(r'"shamrock-standard_allergens":"(\[[^"]+\])"', html_content)
        if allergens_match:
            allergens_json = allergens_match.group(1).replace('\\', '')
            try:
                allergens_data = json.loads(allergens_json)
                allergens_text = []
                for allergen_group in allergens_data:
                    if 'type' in allergen_group and 'items' in allergen_group:
                        allergen_type = allergen_group['type']
                        if isinstance(allergen_group['items'], dict) and 'en' in allergen_group['items']:
                            allergen_items = allergen_group['items']['en']
                            allergens_text.append(f"{allergen_type}: {allergen_items}")
                product_info['allergens'] = "; ".join(allergens_text)
            except json.JSONDecodeError:
                product_info['allergens'] = allergens_match.group(1)
        
        # Extract nutrition facts - also in JSON format
        nutrition_match = re.search(r'"shamrock-standard_nutrition_facts":"({[^"]+})"', html_content)
        if nutrition_match:
            try:
                nutrition_json = nutrition_match.group(1).replace('\\', '')
                nutrition_data = json.loads(nutrition_json)
                product_info['nutritional_info'] = nutrition_data
            except json.JSONDecodeError:
                product_info['nutritional_info'] = nutrition_match.group(1)
        
        # Extract additional information fields
        additional_fields = {
            'Brand': r'"shamrock-standard_brand_long_description":"([^"]+)"',
            'Pack Size': r'"shamrock-standard_pack_size":"([^"]+)"',
            'UPC': r'"shamrock-standard_upc":"([^"]+)"',
            'Weight': r'"shamrock-standard_net_weight":([^,]+)',
            'Weight UOM': r'"shamrock-standard_weight_uom":"([^"]+)"',
            'Additional Info': r'"shamrock-standard_additional_info":"([^"]+)"',
            'Storage': r'"shamrock-standard_storage":\["([^"]+)"\]',
            'Temperature Zone': r'"shamrock-standard_temperature_zone":"([^"]+)"',
            'Shelf Life': r'"shamrock-standard_shelf_life":([^,]+)'
        }
        
        for field_name, pattern in additional_fields.items():
            match = re.search(pattern, html_content)
            if match:
                product_info['additional_info'][field_name] = match.group(1).replace('\\u0026', '&')
        
        # Remove any empty fields
        for key in list(product_info.keys()):
            if not product_info[key] and key != 'product_id':
                del product_info[key]
        
        for key in list(product_info['additional_info'].keys()):
            if not product_info['additional_info'][key]:
                del product_info['additional_info'][key]
        
        return product_info

    def fetch_product_by_id(self, product_id):
        """
        Fetch product page and extract information
        """
        url = f"https://shop.shamrockfoodservice.com/product/{product_id}"
        
        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        try:
            print(f"Fetching product page for ID: {product_id}...")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                return {
                    'error': f"HTTP error: {response.status_code}",
                    'product_id': product_id
                }
            
            # Check if we were redirected to a login page
            if 'login' in response.url.lower() or 'signin' in response.url.lower():
                return {
                    'error': 'Redirected to login page. Authentication required.',
                    'product_id': product_id
                }
            
            # Save the HTML for debugging if needed
            html_file = f"product_{product_id}_page.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
            print(f"HTML saved to {html_file}")
            
            # Extract product information
            product_info = self.extract_product_data_from_html(response.text, product_id)
            
            return product_info
            
        except requests.exceptions.RequestException as e:
            return {
                'error': f"Request error: {str(e)}",
                'product_id': product_id
            }
        except Exception as e:
            return {
                'error': f"Unexpected error: {str(e)}",
                'product_id': product_id
            }

    
    def update_ingredient_info(self, ingredient_nick, product_id=None):
        """
        Update the ingredient info in CostCalculator with data from Shamrock
        
        Args:
            ingredient_nick: Nickname of the ingredient to update
            product_id: Product ID to fetch (if None, will look in 'number' column)
        """
        # Check if ingredient exists
        ingredient_rows = self.cc.uni_g[self.cc.uni_g['nickname'] == ingredient_nick]
        
        if ingredient_rows.empty:
            print(f"Ingredient {ingredient_nick} not found in database")
            return False
        
        # Filter rows to only those with supplier = "SR"
        sr_rows = ingredient_rows[ingredient_rows['supplier'] == 'SR']
        
        if sr_rows.empty:
            print(f"No 'SR' supplier rows found for {ingredient_nick}")
            return False
            
        # Get unique product IDs from the 'number' column in SR rows
        product_ids = []
        if 'number' in self.cc.uni_g.columns:
            product_ids = sr_rows['number'].dropna().unique().tolist()
            
        # If a specific product_id was provided, use only that one
        if product_id:
            product_ids = [product_id]
            
        if not product_ids:
            print(f"No product numbers found for {ingredient_nick} with supplier 'SR'")
            return False
        
        # Create allergen_info column if it doesn't exist
        if 'allergen_info' not in self.cc.uni_g.columns:
            self.cc.uni_g['allergen_info'] = None
            
        if 'ingredients' not in self.cc.uni_g.columns:
            self.cc.uni_g['ingredients'] = None
            
        updated_rows = 0
        
        # Process each product ID
        for id in product_ids:
            print(f"Fetching information for product ID {id}...")
            product_info = self.fetch_product_by_id(int(id))
            
            if 'error' in product_info:
                print(f"Error fetching product {id}: {product_info['error']}")
                continue
                
            # Update only rows that match both nickname and number
            matching_rows = self.cc.uni_g[
                (self.cc.uni_g['nickname'] == ingredient_nick) & 
                (self.cc.uni_g['number'] == id) &
                (self.cc.uni_g['supplier'] == 'SR')
            ]
            
            if matching_rows.empty:
                print(f"No rows found matching nickname={ingredient_nick}, number={id}, supplier=SR")
                continue
                
            # Update allergen information
            if product_info.get('allergens'):
                self.cc.uni_g.loc[
                    (self.cc.uni_g['nickname'] == ingredient_nick) & 
                    (self.cc.uni_g['number'] == id) &
                    (self.cc.uni_g['supplier'] == 'SR'), 
                    'allergen_info'
                ] = product_info['allergens']
                print(f"Updated allergen_info for product {id}: {product_info['allergens']}")
                
            # Update ingredients information
            if product_info.get('ingredients'):
                self.cc.uni_g.loc[
                    (self.cc.uni_g['nickname'] == ingredient_nick) & 
                    (self.cc.uni_g['number'] == id) &
                    (self.cc.uni_g['supplier'] == 'SR'), 
                    'ingredients'
                ] = product_info['ingredients']
                print(f"Updated ingredients for product {id}: {product_info['ingredients']}")
                
            updated_rows += len(matching_rows)
            
        print(f"Updated {updated_rows} rows for {ingredient_nick}")
        
        # Return the updated ingredient information
        return self.cc.uni_g[self.cc.uni_g['nickname'] == ingredient_nick]
    
    def batch_update_ingredients(self, ingredient_list=None):
        """
        Update multiple ingredients at once
        
        Args:
            ingredient_list: List of ingredient nicknames to update
                             If None, will update all ingredients with product numbers that have supplier 'SR'
        """
        if not ingredient_list:
            # Filter ingredients that have product numbers AND supplier = 'SR'
            if 'number' in self.cc.uni_g.columns and 'supplier' in self.cc.uni_g.columns:
                sr_ingredients = self.cc.uni_g[
                    (self.cc.uni_g['number'].notna()) & 
                    (self.cc.uni_g['supplier'] == 'SR')
                ]
                
                if sr_ingredients.empty:
                    print("No ingredients found with 'SR' supplier and product numbers")
                    return False
                    
                ingredient_list = sr_ingredients['nickname'].unique()
            else:
                print("Required columns 'number' or 'supplier' not found in database")
                return False
        
        total_count = len(ingredient_list)
        updated_count = 0
        failed_count = 0
        
        print(f"Found {total_count} ingredients to update")
        
        for i, ingredient in enumerate(ingredient_list):
            print(f"\nUpdating {ingredient} ({i+1}/{total_count})...")
            result = self.update_ingredient_info(ingredient)
            
            if isinstance(result, pd.DataFrame) and not result.empty:
                updated_count += 1
            else:
                failed_count += 1
        
        print(f"\nUpdate complete: {updated_count} ingredients updated, {failed_count} failed")
        return updated_count > 0
    
    def save_database(self, filename=None):
        """
        Save the updated database
        """
        if not filename:
            filename = 'amc_menu_database_updated.xlsx'
        
        print(f"Saving updated database to {filename}...")
        self.cc.write_cc(filename)
        return True

# Integration with DataFrameExplorer class
def integrate_fetcher_with_explorer(explorer_class):
    """
    Add product fetcher functionality to the DataFrameExplorer class
    """
    # Create a method to update ingredient information from Shamrock
    def update_from_shamrock(self, ingredient=None):
        """
        Update ingredient information from Shamrock website
        
        Args:
            ingredient: Ingredient nickname to update (if None, uses current displayed ingredient)
        """
        if not hasattr(self, 'product_fetcher'):
            self.product_fetcher = ProductDataFetcher(self.cc)
        
        if not ingredient:
            # Use the currently displayed ingredient
            if hasattr(self.df_widget, 'last_lookup'):
                ingredient = self.df_widget.last_lookup
        
        if not ingredient:
            print("No ingredient selected")
            return
        
        # Update the ingredient information
        updated = self.product_fetcher.update_ingredient_info(ingredient)
        
        if isinstance(updated, pd.DataFrame) and not updated.empty:
            # Refresh the display
            self.df_widget.lookup_name(ingredient)
            self.df_widget.update_display()
            print(f"Successfully updated {ingredient} information")
        else:
            print(f"Failed to update {ingredient} information")
    
    # Create a method to batch update ingredients
    def batch_update_from_shamrock(self):
        """
        Batch update ingredient information from Shamrock website
        """
        if not hasattr(self, 'product_fetcher'):
            self.product_fetcher = ProductDataFetcher(self.cc)
        
        print("Starting batch update of ingredients from Shamrock...")
        success = self.product_fetcher.batch_update_ingredients()
        
        if success:
            print("Batch update completed successfully")
            # Refresh the display
            if hasattr(self.df_widget, 'last_lookup'):
                self.df_widget.lookup_name(self.df_widget.last_lookup)
                self.df_widget.update_display()
        else:
            print("Batch update failed")
    
    # Add a button to update ingredient from Shamrock
    def add_shamrock_buttons(self):
        """
        Add Shamrock update buttons to the interface
        """
        import ipywidgets as widgets
        
        # Create update button
        update_button = widgets.Button(
            description='Update from Shamrock',
            button_style='info',
            tooltip='Update current ingredient info from Shamrock'
        )
        update_button.on_click(lambda b: self.update_from_shamrock())
        
        # Create batch update button
        batch_update_button = widgets.Button(
            description='Batch Update',
            button_style='warning',
            tooltip='Update all ingredients with product numbers'
        )
        batch_update_button.on_click(lambda b: self.batch_update_from_shamrock())
        
        # Create save button
        save_button = widgets.Button(
            description='Save Database',
            button_style='success',
            tooltip='Save the updated database'
        )
        save_button.on_click(lambda b: self.product_fetcher.save_database() if hasattr(self, 'product_fetcher') else print("Product fetcher not initialized"))
        
        # Create a container for the buttons
        button_container = widgets.HBox([update_button, batch_update_button, save_button])
        
        # Add the container to the interface
        if hasattr(self, 'vbox') and isinstance(self.vbox, widgets.VBox):
            # Find a good position to insert the buttons
            children_list = list(self.vbox.children)
            
            # Insert after database display
            if hasattr(self, 'database_display'):
                try:
                    index = children_list.index(self.database_display) + 1
                    children_list.insert(index, button_container)
                    self.vbox.children = tuple(children_list)
                    return True
                except ValueError:
                    pass
            
            # Fallback: add to the beginning
            children_list.insert(0, button_container)
            self.vbox.children = tuple(children_list)
            return True
            
        return False
    
    # Add the methods to the class
    explorer_class.update_from_shamrock = update_from_shamrock
    explorer_class.batch_update_from_shamrock = batch_update_from_shamrock
    explorer_class.add_shamrock_buttons = add_shamrock_buttons
    
    # Enhance the display method to add the buttons
    original_display = explorer_class.display
    
    def enhanced_display(self):
        original_display(self)
        self.add_shamrock_buttons()
    
    explorer_class.display = enhanced_display
    
    return explorer_class

# Example usage
if __name__ == "__main__":
    # Demonstrate standalone usage
    fetcher = ProductDataFetcher()
    
    # Test with a specific product ID
    product_id = input("Enter product ID to fetch (default: 9806641): ")
    if not product_id:
        product_id = "9806641"
    
    product_info = fetcher.fetch_product_by_id(product_id)
    print(json.dumps(product_info, indent=2))
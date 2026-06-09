import os
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output
import re
from datetime import datetime
import numpy as np

class OrderGuideReader:
    """
    A class to read order guide XLS files and process them for use in the menu cost calculator.
    Handles both order guide price lists and order confirmations with different formats.
    """
    
    def __init__(self, cc=None):
        """Initialize the reader with an optional CostCalculator instance"""
        self.cc = cc  # CostCalculator instance
        self.order_data = None  # Processed order guide data
        self.all_found_dates = []
        self.order_date = None  # Date from the order guide
        self.nickname_widgets = {}  # Store nickname input widgets
        self.file_type = None  # Store the type of file ('guide' or 'confirmation')
        self.setup_interface()
        
    def setup_interface(self):
        """Set up the user interface with dropdown and buttons"""
        # Create dropdown for file selection
        self.file_dropdown = widgets.Dropdown(
            options=self.get_order_files(),
            description='Order file:',
            disabled=False,
            layout=widgets.Layout(width='350px')
        )
        
        # Create refresh button
        self.refresh_button = widgets.Button(
            description='🔄 Refresh',
            tooltip='Refresh file list',
            layout=widgets.Layout(width='100px')
        )
        self.refresh_button.on_click(self.refresh_files)
        
        # Create process button
        self.process_button = widgets.Button(
            description='Process File',
            tooltip='Process the selected order file',
            button_style='primary',
            layout=widgets.Layout(width='150px')
        )
        self.process_button.on_click(self.process_selected_file)
        
        # Create update button (disabled until processing is done)
        self.update_button = widgets.Button(
            description='Update Prices',
            tooltip='Update prices in the database',
            button_style='success',
            layout=widgets.Layout(width='150px'),
            disabled=True
        )
        self.update_button.on_click(self.update_prices)
        
        # Create save button
        self.save_button = widgets.Button(
            description='Save Database',
            tooltip='Save changes to the database file',
            button_style='danger',
            layout=widgets.Layout(width='150px'),
            disabled=True
        )
        self.save_button.on_click(self.save_database)
        
        # Date selection interface
        self.date_label = widgets.HTML(value="<b>Order Date:</b>")
        self.date_picker = widgets.DatePicker(
            description='',
            disabled=False,
            layout=widgets.Layout(width='200px')
        )
        self.date_dropdown = widgets.Dropdown(
            options=[],
            description='Found dates:',
            disabled=False,
            layout=widgets.Layout(width='300px')
        )
        self.date_dropdown.observe(self.on_date_selected, names='value')
        self.date_area = widgets.HBox([
            self.date_label, 
            self.date_picker, 
            self.date_dropdown
        ], layout=widgets.Layout(
            width='100%',
            display='none'
        ))
        
        # Status output
        self.status_output = widgets.Output(
            layout=widgets.Layout(width='100%', height='150px', border='1px solid #ddd', padding='5px', overflow='auto')
        )
        
        # Nickname assignment area
        self.nickname_area = widgets.VBox([
            widgets.HTML(value="<h4>Assign Nicknames</h4><p>Items without nicknames will not be added to the database unless you assign a nickname below:</p>")
        ], layout=widgets.Layout(
            width='100%', 
            border='1px solid #ccc',
            padding='10px',
            margin='10px 0',
            display='none'  # Hidden initially
        ))
        
        # Assemble the interface
        self.file_selector = widgets.HBox([self.file_dropdown, self.refresh_button])
        self.button_row = widgets.HBox([self.process_button, self.update_button, self.save_button])
        # self.container = widgets.VBox([
        #     widgets.HTML(value="<h3>Order File Price/Quantity Updater</h3>"),
        #     self.file_selector,
        #     self.button_row,
        #     self.status_output,
        #     self.nickname_area
        # ])
        self.container = widgets.VBox([
            widgets.HTML(value="<h3>Update from order guide/confirmation</h3>"),
            self.file_selector,
            self.date_area,  # Add date area here
            self.button_row,
            self.status_output,
            self.nickname_area
        ])
        
    def on_date_selected(self, change):
        """Handle date selection from dropdown"""
        if change['new']:
            # Update the date picker with the selected date
            self.date_picker.value = change['new']
    
    def get_order_files(self):
        """Get a list of XLS files in the orders directory"""
        orders_dir = 'orders'
        
        # Create the directory if it doesn't exist
        if not os.path.exists(orders_dir):
            os.makedirs(orders_dir)
            
        # Get all XLS and XLSX files
        files = [f for f in os.listdir(orders_dir) 
                if f.lower().endswith(('.xls', '.xlsx'))]
        
        # Add directory prefix
        file_paths = [os.path.join(orders_dir, f) for f in files]
        
        return file_paths if file_paths else ['No order files found']
    
    def refresh_files(self, button):
        """Refresh the list of available files"""
        self.file_dropdown.options = self.get_order_files()
        
        with self.status_output:
            self.status_output.clear_output()
            print("File list refreshed.")
    
    def determine_file_type(self, filename):
        """Determine the type of file based on the filename"""
        filename_lower = filename.lower()
        if 'fporder' in filename_lower or 'freshpoint' in filename_lower:
            return 'freshpoint_confirmation'
        elif 'order-confirmation' in filename_lower or 'orderconfirmation' in filename_lower:
            return 'confirmation'
        elif 'order-guide' in filename_lower or 'orderguidepricelist' in filename_lower:
            return 'guide'
        else:
            # Try to guess based on the file content
            return None
    
    def normalize_product_number(self, number):
        """
        Normalize product numbers to handle different formats
        Converts to integer if possible, otherwise returns string
        """
        if pd.isna(number):
            return None
            
        # Convert to string first
        number_str = str(number).strip()
        
        # Try to extract just the digits
        digits_match = re.search(r'(\d+)', number_str)
        if digits_match:
            number_str = digits_match.group(1)
            
        # Try to convert to integer
        try:
            return int(float(number_str))
        except (ValueError, TypeError):
            return number_str
    
    def normalize_price(self, price):
        """
        Normalize price values by removing '$' and converting to float
        """
        if pd.isna(price):
            return None
            
        # Convert to string first
        price_str = str(price).strip()
        
        # Remove $ symbol
        price_str = price_str.replace('$', '')
        
        # Try to convert to float
        try:
            return float(price_str)
        except (ValueError, TypeError):
            return None
    
    def process_selected_file(self, button):
        """Process the selected order file"""
        selected_file = self.file_dropdown.value
        
        if selected_file == 'No order files found':
            with self.status_output:
                self.status_output.clear_output()
                print("No file selected. Please add files to the 'orders' directory.")
            return
        
        with self.status_output:
            self.status_output.clear_output()
            
            # Determine file type
            self.file_type = self.determine_file_type(selected_file)
            
            if self.file_type == 'guide':
                print(f"Processing Order Guide Price List: {os.path.basename(selected_file)}...")
            elif self.file_type == 'confirmation':
                print(f"Processing Order Confirmation: {os.path.basename(selected_file)}...")
            elif self.file_type == 'freshpoint_confirmation':
                print(f"Processing FreshPoint Order Confirmation: {os.path.basename(selected_file)}...")
            else:
                print(f"Processing file (unknown type): {os.path.basename(selected_file)}...")
            
            try:
                # Process the order file
                self.order_data = self.read_order_file(selected_file)
                self.update_button.disabled = False
                
                # Update date picker with the found date
                self.date_picker.value = datetime.strptime(self.order_date, '%Y-%m-%d')
                
                # Update date dropdown with all found dates
                date_options = []
                if hasattr(self, 'all_found_dates') and self.all_found_dates:
                    date_options = [(d.strftime('%Y-%m-%d'), d) for d in self.all_found_dates]
                
                self.date_dropdown.options = date_options
                
                # Show the date selection area
                self.date_area.layout.display = 'flex'
                
                # Display summary
                print(f"Date: {self.order_date}")
                print(f"Processed {len(self.order_data)} items from file.")
                
                # Show number of items with and without nicknames
                with_nickname = self.order_data['nickname'].notna().sum()
                without_nickname = len(self.order_data) - with_nickname
                print(f"Items with matched nicknames: {with_nickname}")
                print(f"Items without nicknames: {without_nickname}")
                
                # Create nickname assignment interface
                if without_nickname > 0:
                    self.create_nickname_interface()
                    print("Please assign nicknames to items below or they will be skipped during import.")
                else:
                    self.nickname_area.layout.display = 'none'
                    print("Ready to update prices in database.")
                
            except Exception as e:
                print(f"Error processing file: {str(e)}")
                import traceback
                traceback.print_exc()
                self.update_button.disabled = True
    
    def create_nickname_interface(self):
        """Create interface for assigning nicknames to items without them"""
        # Clear previous widgets
        self.nickname_area.children = [
            widgets.HTML(value="<h4>Assign Nicknames</h4><p>Items without nicknames will not be added to the database unless you assign a nickname below:</p>")
        ]
        self.nickname_widgets = {}
        
        # Get items without nicknames
        items_without_nickname = self.order_data[self.order_data['nickname'].isna()].copy()
        
        if len(items_without_nickname) == 0:
            self.nickname_area.layout.display = 'none'
            return
            
        # Sort by description for easier reading
        items_without_nickname = items_without_nickname.sort_values('description')
        
        # Create widgets for each item
        for idx, row in items_without_nickname.iterrows():
            # Product description and number
            description = row['description'] if pd.notna(row['description']) else "No description"
            product_num = row['number'] if pd.notna(row['number']) else "No number"
            
            # Create text input for nickname
            nickname_input = widgets.Text(
                value='',
                placeholder='Enter nickname',
                description='',
                layout=widgets.Layout(width='200px')
            )
            
            # Store reference to widget
            self.nickname_widgets[idx] = nickname_input
            
            # Prepare item details
            size_info = f", {row['size']}" if pd.notna(row['size']) else ""
            price_info = f", ${row['price']}" if pd.notna(row['price']) else ""
            order_info = f", Qty: {row['order']}" if pd.notna(row['order']) and row['order'] != 0 else ""
            
            # Create row with description and input
            row_widget = widgets.HBox([
                widgets.HTML(
                    value=f"<b>{description}</b> (#{product_num}{size_info}{price_info}{order_info})",
                    layout=widgets.Layout(width='500px', overflow='hidden')
                ),
                nickname_input
            ])
            
            # Add to nickname area
            self.nickname_area.children = list(self.nickname_area.children) + [row_widget]
        
        # Add "apply all" button for convenience
        apply_button = widgets.Button(
            description='Apply Nicknames',
            button_style='info',
            layout=widgets.Layout(width='150px')
        )
        apply_button.on_click(self.apply_nicknames)
        
        self.nickname_area.children = list(self.nickname_area.children) + [apply_button]
        
        # Show the nickname area
        self.nickname_area.layout.display = 'block'
    
    def apply_nicknames(self, button):
        """Apply the entered nicknames to the order data"""
        nickname_count = 0
        
        # Update the DataFrame with nicknames
        for idx, widget in self.nickname_widgets.items():
            nickname = widget.value.strip()
            if nickname:
                self.order_data.at[idx, 'nickname'] = nickname
                nickname_count += 1
                
                # Update the widget style to show it's been applied
                widget.style.background = '#d4edda'
        
        # Update status
        with self.status_output:
            print(f"Applied {nickname_count} nicknames.")
            
            # Count remaining items without nicknames
            remaining = len(self.nickname_widgets) - nickname_count
            if remaining > 0:
                print(f"{remaining} items still need nicknames or will be skipped.")
            else:
                print("All items now have nicknames. Ready to update prices.")
    
    def read_order_file(self, file_path):
        """
        Read and process an order file (either guide or confirmation)
        
        Parameters:
        file_path (str): Path to the XLS file
        
        Returns:
        pd.DataFrame: Processed order data
        """
        # Determine the file type if not already set
        if not self.file_type:
            self.file_type = self.determine_file_type(file_path)
        
        # Read the entire Excel file without specifying headers
        df_raw = pd.read_excel(file_path, header=None)
        
        # Process based on file type
        if self.file_type == 'confirmation':
            return self.process_order_confirmation(df_raw, file_path)
        elif self.file_type == 'freshpoint_confirmation':
            return self.process_freshpoint_confirmation(df_raw, file_path)
        else:
            # Default to guide processing
            return self.process_order_guide(df_raw, file_path)
    
    def process_order_confirmation(self, df_raw, file_path):
        """Process an order confirmation file"""
        # Find the date in the file (ship date for confirmations)
        self.order_date, self.all_found_dates = self.find_all_dates_in_data(df_raw)
        
        # Look for header row based on Product # or Item #
        try:
            header_row_index = df_raw[df_raw.apply(lambda row: row.astype(str).str.contains('Product #').any(), axis=1)].index[0]
        except IndexError:
            try:
                header_row_index = df_raw[df_raw.apply(lambda row: row.astype(str).str.contains('Item #').any(), axis=1)].index[0]
            except IndexError:
                raise ValueError("Could not find header row with 'Product #' or 'Item #'")
        
        # Re-read the Excel file starting from the header row
        df = pd.read_excel(file_path, header=header_row_index)
        
        # Remove columns without a header value
        df = df.dropna(axis=1, how='all')
        
        # Map column names
        columnmap = {
            'Product #': 'number', 
            'Item #': 'number',
            'Description': 'description', 
            'Pack': 'size', 
            'Pack Size': 'size',
            'Brand': 'brand', 
            'Ship Qty': 'order',
            'Quantity': 'order',
            'Ordered Qty': 'order',
            'Pack Price': 'price',
            'Price': 'price',
            'Unit Price': 'price',
            'Unit':'unit'
        }
        
        mymap = {key: value for key, value in columnmap.items() if key in df.columns}
        df = df.rename(columns=mymap)
        
        # Drop unnecessary columns
        dropcolumns = [
            'Ship Weight', 'Cube Volume', 'Manufacturer Id', 'Tags', '#',
            'Description Ext', 'Net Weight', 'Shamrock Brand', 'JIT', 
            'Kosher', 'Pallet Quantity', 'Line Amount', 'Amount', 'Total'
        ]
        mydrop = [x for x in dropcolumns if x in df.columns]
        df = df.drop(columns=mydrop)
        
        # Normalize product numbers and prices
        df['number_normalized'] = df['number'].apply(self.normalize_product_number)
        if 'price' in df.columns:
            df['price'] = df['price'].apply(self.normalize_price)
        
        # Assign nicknames if we have a cost calculator instance
        if self.cc is not None and hasattr(self.cc, 'uni_g'):
            self.assign_nicknames_and_metadata(df)
        else:
            df['nickname'] = None
            df['allergen'] = ''
            df['conversion'] = ''
        
        if 'order' not in df.columns:
            df['order'] = 1
        # Add remaining missing columns
        df['supplier'] = 'SR'  # Assuming SR as default supplier
        df['note'] = ''
        df['date'] = self.order_date if self.order_date else datetime.now().strftime('%Y-%m-%d')
        
        # Remove temporary column
        df = df.drop(columns=['number_normalized'])
        
        return df
    
    def process_freshpoint_confirmation(self, df_raw, file_path):
        """Process a FreshPoint order confirmation file"""
        # Find the date in the file
        self.order_date, self.all_found_dates = self.find_all_dates_in_data(df_raw)
        
        # Find the header row - look for 'Item#' in FreshPoint format
        try:
            header_row_index = df_raw[df_raw.apply(lambda row: row.astype(str).str.contains('Item#', case=False).any(), axis=1)].index[0]
        except IndexError:
            raise ValueError("Could not find header row with 'Item#' in FreshPoint confirmation")
        
        # Re-read the Excel file starting from the header row
        df = pd.read_excel(file_path, header=header_row_index)
        
        # Remove rows after "Order Summary" which marks the end of items
        if 'Item#' in df.columns:
            summary_idx = df[df['Item#'].astype(str).str.contains('Order Summary', case=False, na=False)].index
            if len(summary_idx) > 0:
                df = df.iloc[:summary_idx[0]]
        
        # Remove columns without a header value and empty rows
        df = df.dropna(axis=1, how='all')
        df = df.dropna(axis=0, how='all')
        
        # Remove rows where Item# is NaN (these are not actual items)
        df = df[df['Item#'].notna()]
        
        # Map FreshPoint column names to standard names
        columnmap = {
            'Item#': 'number',
            'Product': 'description',
            'Size': 'size',
            'Qty': 'order',
            'Price': 'price'
        }
        
        mymap = {key: value for key, value in columnmap.items() if key in df.columns}
        df = df.rename(columns=mymap)
        
        # Clean up the size column - remove non-breaking spaces and extra whitespace
        if 'size' in df.columns:
            df['size'] = df['size'].astype(str).str.replace('\xa0', ' ').str.strip()
            # Remove unit codes from the end (any 2-3 letter uppercase code, optionally followed by *)
            # This catches BG, CS, BX, BUS, FL, and any other similar codes
            df['size'] = df['size'].str.replace(r'\s+[A-Z]{2,3}\*?$', '', regex=True)
        
        # Normalize product numbers and prices
        df['number_normalized'] = df['number'].apply(self.normalize_product_number)
        if 'price' in df.columns:
            df['price'] = df['price'].apply(self.normalize_price)
        
        # Assign nicknames if we have a cost calculator instance
        if self.cc is not None and hasattr(self.cc, 'uni_g'):
            self.assign_nicknames_and_metadata(df)
        else:
            df['nickname'] = None
            df['allergen'] = ''
            df['conversion'] = ''
        
        # Ensure order column exists and has proper values
        if 'order' not in df.columns:
            df['order'] = 1
        else:
            # Convert order quantities to numeric, default to 1 if not valid
            df['order'] = pd.to_numeric(df['order'], errors='coerce').fillna(1)
        
        # Add remaining missing columns - use 'FP' for FreshPoint supplier
        df['supplier'] = 'FP'
        df['unit'] = 'ea'  # FreshPoint typically uses 'ea' (each) as the unit
        df['brand'] = ''
        df['note'] = ''
        df['date'] = self.order_date if self.order_date else datetime.now().strftime('%Y-%m-%d')
        
        # Remove temporary column
        df = df.drop(columns=['number_normalized'])
        
        return df
    
    def process_order_guide(self, df_raw, file_path):
        """Process an order guide price list file"""
        # Find the date in the file
        self.order_date, self.all_found_dates = self.find_all_dates_in_data(df_raw)
        
        # Identify the row containing 'Product #'
        try:
            header_row_index = df_raw[df_raw.apply(lambda row: row.astype(str).str.contains('Product #').any(), axis=1)].index[0]
        except IndexError:
            # Try alternative header names
            try:
                header_row_index = df_raw[df_raw.apply(lambda row: row.astype(str).str.contains('Item #').any(), axis=1)].index[0]
            except IndexError:
                raise ValueError("Could not find header row with 'Product #' or 'Item #'")
        
        # Re-read the Excel file starting from the header row
        df = pd.read_excel(file_path, header=header_row_index)
        
        # Remove columns without a header value
        df = df.dropna(axis=1, how='all')
        
        # Map column names
        columnmap = {
            'Product #': 'number', 
            'Item #': 'number',
            'Description': 'description', 
            'Pack': 'size', 
            'Pack Size': 'size',
            'Brand': 'brand', 
            'CWT': 'LB', 
            'Kosher Indicator': 'kosher', 
            'Gluten Free': 'gf', 
            'Organic': 'organic', 
            'Temp Zone': 'temp zone', 
            'Unit': 'unit', 
            'UOM': 'unit', 
            'Quantity': 'order', 
            'Price': 'price'
        }
        
        mymap = {key: value for key, value in columnmap.items() if key in df.columns}
        df = df.rename(columns=mymap)
        
        # Drop unnecessary columns
        dropcolumns = [
            'Ship Weight', 'Cube Volume', 'Manufacturer Id', 'Tags', '#',
            'Description Ext', 'Net Weight', 'Shamrock Brand', 'JIT', 
            'Kosher', 'Pallet Quantity'
        ]
        mydrop = [x for x in dropcolumns if x in df.columns]
        df = df.drop(columns=mydrop)
        
        # Normalize product numbers and prices
        df['number_normalized'] = df['number'].apply(self.normalize_product_number)
        if 'price' in df.columns:
            df['price'] = df['price'].apply(self.normalize_price)
        
        # Assign nicknames if we have a cost calculator instance
        if self.cc is not None and hasattr(self.cc, 'uni_g'):
            self.assign_nicknames_and_metadata(df)
        else:
            df['nickname'] = None
            df['allergen'] = ''
            df['conversion'] = ''
        
        # Add remaining missing columns
        df['supplier'] = 'SR'  # Assuming SR as default supplier
        df['note'] = ''
        df['order'] = 0
        df['date'] = self.order_date if self.order_date else datetime.now().strftime('%Y-%m-%d')
        
        # Remove temporary column
        df = df.drop(columns=['number_normalized'])
        
        return df
    
    def assign_nicknames_and_metadata(self, df):
        """Assign nicknames, allergens, and conversion data from existing database"""
        # Normalize the product numbers in the unified guide
        number_to_nickname = {}
        
        # Create a new column in uni_g temporarily for matching
        temp_uni_g = self.cc.uni_g.copy()
        temp_uni_g['number_normalized'] = temp_uni_g['number'].apply(self.normalize_product_number)
        
        # Create mapping from normalized numbers to nicknames
        for _, row in temp_uni_g[temp_uni_g['number_normalized'].notna()].iterrows():
            if pd.notna(row['nickname']):
                number_to_nickname[row['number_normalized']] = row['nickname']
        
        # Apply the mapping to assign nicknames
        df['nickname'] = df['number_normalized'].map(number_to_nickname)
        
        # Also map allergen and conversion information from existing entries
        allergen_map = {}
        conversion_map = {}
        
        for _, row in temp_uni_g[temp_uni_g['number_normalized'].notna()].iterrows():
            if pd.notna(row['number_normalized']):
                if pd.notna(row['allergen']):
                    allergen_map[row['number_normalized']] = row['allergen']
                if pd.notna(row['conversion']):
                    conversion_map[row['number_normalized']] = row['conversion']
        
        # Apply mappings
        df['allergen'] = df['number_normalized'].map(allergen_map).fillna('')
        df['conversion'] = df['number_normalized'].map(conversion_map).fillna('')
    
    # Add this as a new method
    def find_all_dates_in_data(self, df):
        """Find all dates in the raw data frame and return the oldest"""
        found_dates = []
        
        # Convert all data to string and search for date patterns
        for i in range(min(30, len(df))):  # Search first 30 rows
            for j in range(min(30, len(df.columns))):  # Search first 15 columns
                cell_value = str(df.iloc[i, j])
                
                # Look for date patterns in the cell
                date_pattern = r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|(\d{2,4}[/-]\d{1,2}[/-]\d{1,2})'
                date_matches = re.finditer(date_pattern, cell_value)
                
                for date_match in date_matches:
                    date_str = date_match.group(0)
                    try:
                        # Try different date formats
                        for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%Y-%m-%d', '%m/%d/%y', '%m-%d-%y']:
                            try:
                                date_obj = datetime.strptime(date_str, fmt)
                                found_dates.append(date_obj)
                                break  # Break once we successfully parse with one format
                            except ValueError:
                                continue
                    except:
                        pass
        
        if found_dates:
            # Sort dates and use the oldest one
            found_dates.sort()
            return found_dates[0].strftime('%Y-%m-%d'), found_dates
        else:
            # If no date found, use current date
            current_date = datetime.now().strftime('%Y-%m-%d')
            return current_date, []
    
    def update_prices(self, button):
        """Update prices in the database using the processed order data"""
        if self.order_data is None or self.cc is None:
            with self.status_output:
                self.status_output.clear_output()
                print("No data to update or Cost Calculator not available.")
            return
        
        # Update the order date from the date picker
        if self.date_picker.value:
            selected_date = self.date_picker.value.strftime('%Y-%m-%d')
            # Update the order_date and all rows in the order_data
            self.order_date = selected_date
            self.order_data['date'] = selected_date
        
        with self.status_output:
            self.status_output.clear_output()
            print(f"Updating database with date: {self.order_date}")
            
            try:
                # Count updates
                new_items = 0
                updated_items = 0
                skipped_items = 0
                duplicate_items = 0
                overwritten_items = 0
                
                # Create a copy of the guide for processing
                temp_uni_g = self.cc.uni_g.copy()
                
                # Normalize product numbers for matching
                temp_uni_g['number_normalized'] = temp_uni_g['number'].apply(self.normalize_product_number)
                
                # Process each row in the order data
                for _, row in self.order_data.iterrows():
                    product_num = row['number']
                    current_date = row['date']
                    
                    # Skip rows without a valid product number
                    if pd.isna(product_num) or product_num == '' or product_num == 'nan':
                        skipped_items += 1
                        continue
                    
                    # Skip rows without a nickname
                    if pd.isna(row['nickname']) or row['nickname'] == '':
                        skipped_items += 1
                        continue
                    
                    # Normalize the product number
                    norm_num = self.normalize_product_number(product_num)
                    
                    # Check if an entry with the same product number and date already exists
                    duplicate_entries = temp_uni_g[
                        (temp_uni_g['number_normalized'] == norm_num) & 
                        (temp_uni_g['date'] == current_date)
                    ]
                    
                    if not duplicate_entries.empty:
                        # For order confirmations (both SR and FreshPoint), overwrite existing entries instead of skipping
                        if self.file_type in ['confirmation', 'freshpoint_confirmation']:
                            # Get indices of duplicate entries in the original uni_g
                            dup_indices = self.cc.uni_g[
                                (self.cc.uni_g['number'].apply(self.normalize_product_number) == norm_num) & 
                                (self.cc.uni_g['date'] == current_date)
                            ].index
                            
                            # Remove the duplicate entries
                            self.cc.uni_g = self.cc.uni_g.drop(dup_indices)
                            
                            # Add the new row
                            self.cc.uni_g = pd.concat([self.cc.uni_g, pd.DataFrame([row])], ignore_index=True)
                            overwritten_items += 1
                        else:
                            # Skip this entry as a duplicate for price guides
                            duplicate_items += 1
                            continue
                    else:
                        # Create a new row for the guide
                        new_row = row.copy()
                        
                        # Check if this product number exists in the database
                        existing_entries = temp_uni_g[temp_uni_g['number_normalized'] == norm_num]
                        
                        if not existing_entries.empty:
                            # Product exists but with different date - add as update
                            self.cc.uni_g = pd.concat([self.cc.uni_g, pd.DataFrame([new_row])], ignore_index=True)
                            updated_items += 1
                        else:
                            # This is a new product with a nickname
                            self.cc.uni_g = pd.concat([self.cc.uni_g, pd.DataFrame([new_row])], ignore_index=True)
                            new_items += 1
                
                # Clear all costs to force recalculation
                if hasattr(self.cc, 'costdf'):
                    self.cc.costdf['cost'] = 0
                
                # Report based on file type
                if self.file_type in ['confirmation', 'freshpoint_confirmation']:
                    supplier_name = "FreshPoint" if self.file_type == 'freshpoint_confirmation' else "SR"
                    print(f"Updated {updated_items} items from {supplier_name} order confirmation.")
                    print(f"Added {new_items} new items.")
                    print(f"Overwritten {overwritten_items} duplicate items.")
                    print(f"Recorded quantities for {updated_items + new_items + overwritten_items} items.")
                else:
                    print(f"Updated {updated_items} existing prices.")
                    print(f"Added {new_items} new items with prices.")
                    print(f"Skipped {duplicate_items} duplicate items (same product number and date).")
                
                print(f"Skipped {skipped_items} items (no product number or nickname).")
                print("Database updated successfully.")
                
                # Enable save button
                self.save_button.disabled = False
                
            except Exception as e:
                print(f"Error updating database: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def save_database(self, button):
        """Save the updated database"""
        if self.cc is None:
            with self.status_output:
                self.status_output.clear_output()
                print("No Cost Calculator available to save.")
            return
        
        with self.status_output:
            self.status_output.clear_output()
            print("Saving database...")
            
            try:
                self.cc.write_cc('amc_menu_database.xlsx')
                print("Database saved successfully to amc_menu_database.xlsx")
            except Exception as e:
                print(f"Error saving database: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def display(self):
        """Display the OrderGuideReader interface"""
        display(self.container)
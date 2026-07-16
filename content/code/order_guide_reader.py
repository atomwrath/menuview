import os
import csv
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output
import re
from datetime import datetime
import numpy as np
from utils import _try_parse_size, Q_, parse_unit_conversion, quantity_cost_and_conv

class OrderGuideReader:
    """
    A class to read order guide files (.xls, .xlsx, or .csv) and process
    them for use in the menu cost calculator. Handles order guide price
    lists, order confirmations, FreshPoint confirmations, and plain
    item/price-list exports (no order quantities, no filename convention)
    with different formats.
    """
    
    def __init__(self, cc=None, explorer=None):
        """Initialize the reader with an optional CostCalculator instance.

        explorer, if provided, is the DataFrameExplorer sharing this same cc.
        It's used for two things: looking up the database's actual current
        filename (so Save Database writes to whatever's loaded, not a
        hardcoded default) and refreshing the Explorer's on-screen grid
        after prices are updated in place -- self.cc is the same object the
        Explorer holds, but nothing pushes changes to its display on its
        own.
        """
        self.cc = cc  # CostCalculator instance
        self.explorer = explorer
        self.order_data = None  # Processed order guide data
        self.all_found_dates = []
        self.order_date = None  # Date from the order guide
        self.nickname_widgets = {}  # Store nickname input widgets
        self.size_review_widgets = {}  # Store size/price correction widgets
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

        # Size/price review area
        self.size_review_area = widgets.VBox([
            widgets.HTML(value="<h4>Review Sizes</h4>")
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
        self.container = widgets.VBox([
            widgets.HTML(value="<h3>Update from order guide/confirmation</h3>"),
            self.file_selector,
            self.date_area,  # Add date area here
            self.button_row,
            self.status_output,
            self.nickname_area,
            self.size_review_area
        ])
        
    def on_date_selected(self, change):
        """Handle date selection from dropdown"""
        if change['new']:
            # Update the date picker with the selected date
            self.date_picker.value = change['new']
    
    def get_order_files(self):
        """Get a list of XLS/XLSX/CSV files in the orders directory"""
        orders_dir = 'orders'
        
        # Create the directory if it doesn't exist
        if not os.path.exists(orders_dir):
            os.makedirs(orders_dir)
            
        # Get all XLS, XLSX, and CSV files
        files = [f for f in os.listdir(orders_dir) 
                if f.lower().endswith(('.xls', '.xlsx', '.csv'))]
        
        # Add directory prefix
        file_paths = [os.path.join(orders_dir, f) for f in files]
        
        return file_paths if file_paths else ['No order files found']
    
    def refresh_files(self, button):
        """Refresh the list of available files"""
        self.file_dropdown.options = self.get_order_files()
        
        with self.status_output:
            self.status_output.clear_output()
            print("File list refreshed.")
    
    def determine_file_type(self, filename, df_raw=None):
        """Determine the type of file. The filename's own naming
        convention is checked first (fastest, and how every file has been
        named so far); if that's inconclusive (a generic export name) and
        the file's own raw contents are available, fall back to sniffing
        its header row: an 'Item#' (no space) column with no order-
        quantity column alongside it is the same convention FreshPoint's
        confirmations use, minus the quantities -- a plain price-list/
        catalog export rather than a confirmed order.
        """
        filename_lower = filename.lower()
        if 'fporder' in filename_lower or 'freshpoint' in filename_lower:
            return 'freshpoint_confirmation'
        elif 'order-confirmation' in filename_lower or 'orderconfirmation' in filename_lower:
            return 'confirmation'
        elif 'order-guide' in filename_lower or 'orderguidepricelist' in filename_lower:
            return 'guide'

        if df_raw is not None:
            nospace_mask = df_raw.apply(
                lambda row: row.astype(str).str.contains(r'\bItem#', case=False, regex=True).any(),
                axis=1)
            if nospace_mask.any():
                header_row = df_raw.loc[nospace_mask.idxmax()].astype(str)
                has_qty = header_row.str.contains(
                    r'^\s*(?:Qty|Quantity|Ship Qty|Ordered Qty)\s*$', case=False, regex=True).any()
                if not has_qty:
                    return 'item_pricelist'

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
            
            # Determine file type from the filename alone, for now -- a
            # generically-named file (no naming convention to go on) isn't
            # resolved until read_order_file below can sniff its contents.
            self.file_type = self.determine_file_type(selected_file)
            
            if self.file_type == 'guide':
                print(f"Processing Order Guide Price List: {os.path.basename(selected_file)}...")
            elif self.file_type == 'confirmation':
                print(f"Processing Order Confirmation: {os.path.basename(selected_file)}...")
            elif self.file_type == 'freshpoint_confirmation':
                print(f"Processing FreshPoint Order Confirmation: {os.path.basename(selected_file)}...")
            else:
                print(f"Processing file: {os.path.basename(selected_file)}...")
            
            try:
                # Process the order file
                self.order_data = self.read_order_file(selected_file)
                # Discard fully-blank rows (e.g. trailing blank rows picked up
                # from the source spreadsheet) before counting/reporting/flagging.
                self.order_data = self._drop_blank_rows(self.order_data)
                self.update_button.disabled = False

                # self.file_type may have just been resolved by content-
                # sniffing inside read_order_file (a generically-named file
                # gets no type from the filename alone) -- confirm what was
                # actually detected, since it's not always what was
                # printed above.
                type_labels = {
                    'guide': 'Order Guide Price List',
                    'confirmation': 'Order Confirmation',
                    'freshpoint_confirmation': 'FreshPoint Order Confirmation',
                    'item_pricelist': 'Item Price List (no order quantities)',
                }
                print(f"Detected type: {type_labels.get(self.file_type, 'unknown -- treated as a price guide')}")
                
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

                # Check for suspicious/unparseable sizes and let the user fix them
                self.create_size_review_interface()
                if self.size_review_area.layout.display != 'none':
                    print("Please review flagged sizes/prices below before updating.")
                elif without_nickname == 0:
                    print("Ready to update prices in database.")
                
            except Exception as e:
                print(f"Error processing file: {str(e)}")
                import traceback
                traceback.print_exc()
                self.update_button.disabled = True
                
    def _drop_blank_rows(self, df):
        ''' Discard rows with no real content -- no product number,
            description, size, or price. These are typically trailing blank
            rows from the source spreadsheet and shouldn't be treated as
            items needing a nickname or a size correction.
        '''
        if df is None or df.empty:
            return df
        check_cols = [c for c in ('number', 'description', 'size', 'price') if c in df.columns]
        if not check_cols:
            return df
        is_blank = df[check_cols].apply(
            lambda col: col.isna() | col.astype(str).str.strip().isin(['', 'nan', 'None'])
        ).all(axis=1)
        return df.loc[~is_blank].reset_index(drop=True)
    
    def create_nickname_interface(self):
        """Create interface for assigning nicknames to items without them"""
        self.nickname_widgets = {}
        try:
            self._build_nickname_interface()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            # Surface the error directly in the area itself -- this box doesn't
            # scroll/hide the way status_output can, so it can't get missed.
            self.nickname_area.children = [
                widgets.HTML(value=(
                    f"<h4>Assign Nicknames</h4>"
                    f"<p style='color:#b00'>Error building the nickname list: {e}</p>"
                    f"<pre style='font-size:11px; white-space:pre-wrap'>{tb}</pre>"
                ))
            ]
            self.nickname_area.layout.display = 'flex'

    def _build_nickname_interface(self):
        # Clear previous widgets
        self.nickname_area.children = [
            widgets.HTML(value=(
                "<h4>Assign Nicknames</h4>"
            ))
        ]

        # Get items without nicknames
        items_without_nickname = self.order_data[self.order_data['nickname'].isna()].copy()

        if len(items_without_nickname) == 0:
            self.nickname_area.layout.display = 'none'
            return

        # Sort by description for easier reading
        items_without_nickname = items_without_nickname.sort_values('description')

        # Existing nicknames, used for autocomplete hints. Cast to str before
        # sorting/comparing -- a non-string nickname would otherwise raise a
        # TypeError and abort this whole method before it ever displays anything.
        if self.cc is not None and hasattr(self.cc, 'uni_g') and 'nickname' in self.cc.uni_g.columns:
            existing_nicknames = tuple(sorted({str(n) for n in self.cc.uni_g['nickname'].dropna().unique()}))
        else:
            existing_nicknames = tuple()
        known_nicknames = set(existing_nicknames)

        # Create widgets for each item
        for idx, row in items_without_nickname.iterrows():
            description = row['description'] if pd.notna(row['description']) else "No description"
            product_num = row['number'] if pd.notna(row['number']) else "No number"

            nickname_input = widgets.Combobox(
                value='',
                placeholder='Enter nickname',
                options=existing_nicknames,
                ensure_option=False,
                description='',
                layout=widgets.Layout(width='200px')
            )

            def _on_nickname_change(change, widget=nickname_input, known=known_nicknames):
                val = change['new'].strip()
                if val and val not in known:
                    widget.style.text_color = 'red' # new ingredient
                else:
                    widget.style.text_color = None  # default: empty, or matches existing
            nickname_input.observe(_on_nickname_change, names='value')

            self.nickname_widgets[idx] = nickname_input

            size_info = f", {row['size']}" if pd.notna(row['size']) else ""
            price_info = f", ${row['price']}" if pd.notna(row['price']) else ""
            order_info = f", Qty: {row['order']}" if pd.notna(row['order']) and row['order'] != 0 else ""

            row_widget = widgets.HBox([
                widgets.HTML(
                    value=f"<b>{description}</b> (#{product_num}{size_info}{price_info}{order_info})",
                    layout=widgets.Layout(width='500px', overflow='hidden')
                ),
                nickname_input
            ])
            self.nickname_area.children = list(self.nickname_area.children) + [row_widget]

        apply_button = widgets.Button(
            description='Apply Nicknames',
            button_style='info',
            layout=widgets.Layout(width='150px')
        )
        apply_button.on_click(self.apply_nicknames)
        self.nickname_area.children = list(self.nickname_area.children) + [apply_button]

        self.nickname_area.layout.display = 'flex'
    
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
                widget.layout.border = '2px solid #73cf89'
                widget.style.text_color = None
        
        # Update status
        with self.status_output:
            print(f"Applied {nickname_count} nicknames.")
            
            # Count remaining items without nicknames
            remaining = len(self.nickname_widgets) - nickname_count
            if remaining > 0:
                print(f"{remaining} items still need nicknames or will be skipped.")
            else:
                print("All items now have nicknames. Ready to update prices.")

        # A newly-assigned nickname may match an ingredient that already has
        # a price on file, or may itself have a size issue -- re-check now
        # that order_data['nickname'] is up to date, so "recent: ?" turns
        # into an actual comparison instead of waiting for a full reprocess.
        self.create_size_review_interface()
                
    # A ratio outside [1/RATIO_THRESHOLD, RATIO_THRESHOLD] gets flagged for review.
    # This is a heads-up, not a hard limit -- the same value can be re-applied
    # unchanged and it will still go through.
    SIZE_RATIO_THRESHOLD = 4.0

    def _rate_for_row(self, row):
        ''' $/quantity for a guide row, as a pint Quantity. Mirrors
            CostCalculator's pricing: rows whose unit is 'lb' are priced
            per pound regardless of size. Returns None if unresolvable.
        '''
        price = row.get('price')
        if pd.isna(price):
            return None
        try:
            price = float(str(price).replace('$', ''))
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        unit = row.get('unit')
        if isinstance(unit, str) and unit.strip().lower() == 'lb':
            quant = Q_('1 lb')
        else:
            size = row.get('size')
            quant = _try_parse_size(str(size)) if pd.notna(size) else None
            if quant is None or quant.m == 0:
                return None

        return price / quant

    def _format_rate(self, rate):
        if rate is None:
            return '?'
        unit_str = f"{rate.units:~}"
        unit_str = re.sub(r'^1\s*/\s*', '', unit_str)  # pint renders reciprocal units as "1 / count"
        return f"${rate.magnitude:.2f}/{unit_str}"

    def _comparable_rates(self, new_rate, old_rate, conversions):
        ''' Try to express new_rate in the same units as old_rate so they
            can be compared directly -- using the ingredient's own unit
            conversions (e.g. "1 lb per 2 ct") when the two rates aren't
            already the same dimensionality (e.g. $/lb vs $/ct).
            Returns (new_value, old_value) as plain floats in old_rate's
            units, or None if no comparison is possible.
        '''
        if new_rate is None or old_rate is None:
            return None
        try:
            if new_rate.dimensionality == old_rate.dimensionality:
                return new_rate.to(old_rate.units).magnitude, old_rate.magnitude
        except Exception:
            pass

        convlist = list(parse_unit_conversion(list(conversions))) if conversions else []
        if not convlist:
            return None
        try:
            # old_rate is a $/X rate, so its .units are the *reciprocal* of X
            # (e.g. "1 / pound"). We need "1 X" itself (e.g. "1 pound") as the
            # quantity to price using new_rate -- that's units**-1, not units.
            one_old_unit = Q_(1, old_rate.units ** -1)
            converted, _ = quantity_cost_and_conv(new_rate, one_old_unit, convlist)
        except Exception:
            return None
        if converted is None:
            return None
        return converted, old_rate.magnitude

    def _nickname_conversions(self, row, existing):
        ''' Known conversion strings for this ingredient: the row's own
            conversion first (if any), then any others on record.
        '''
        conversions = []
        row_conv = row.get('conversion')
        if isinstance(row_conv, str) and row_conv.strip():
            conversions.append(row_conv)
        for c in existing['conversion'].dropna().unique():
            if isinstance(c, str) and c.strip() and c not in conversions:
                conversions.append(c)
        return conversions

    def _flag_size_issues(self, df):
        ''' Return {idx: {'reason', 'new_rate', 'old_rate'}} (rates are pint
            Quantities or None) for rows whose size/price look suspicious:
              - size can't be parsed into a mass/volume/count quantity
              - the resulting $/quantity, compared like-for-like via any
                known unit conversion, is more than SIZE_RATIO_THRESHOLD x
                (or less than 1/SIZE_RATIO_THRESHOLD x) the most recent
                known price for the same nickname
        '''
        flagged = {}
        for idx, row in df.iterrows():
            size = row.get('size')
            nickname = row.get('nickname')

            # Look up the most recent known price for this nickname FIRST,
            # independent of whether the new row's own size parses -- so a
            # row that just got a nickname assigned (but still has a bad
            # size) can still show "recent: $X" instead of "recent: ?".
            existing = None
            old_rate = None
            if self.cc is not None and pd.notna(nickname) and nickname != '':
                existing = self.cc.uni_g.loc[self.cc.uni_g['nickname'] == nickname]
                if not existing.empty:
                    recent = existing.sort_values('date', ascending=False).iloc[0]
                    old_rate = self._rate_for_row(recent)

            q = _try_parse_size(str(size)) if pd.notna(size) else None
            if q is None or q.m == 0:
                flagged[idx] = {'reason': 'unknown/unparseable size', 'new_rate': None, 'old_rate': old_rate}
                continue

            new_rate = self._rate_for_row(row)
            if new_rate is None:
                continue

            if existing is None or existing.empty or old_rate is None:
                continue

            conversions = self._nickname_conversions(row, existing)
            comparable = self._comparable_rates(new_rate, old_rate, conversions)
            if comparable is None:
                continue
            new_val, old_val = comparable
            if old_val == 0:
                continue
            ratio = new_val / old_val

            if ratio > self.SIZE_RATIO_THRESHOLD or ratio < 1 / self.SIZE_RATIO_THRESHOLD:
                flagged[idx] = {
                    'reason': f'$/qty is {ratio:.1f}x the last known price for "{nickname}"',
                    'new_rate': new_rate,
                    'old_rate': old_rate,
                }

        return flagged

    def _row_is_resolved(self, size_val, price_val, unit, old_rate, conversions):
        ''' Check a single (possibly just-edited) row against the same
            criteria used to flag it, without touching the wider flag list.
        '''
        q = _try_parse_size(str(size_val)) if size_val else None
        if q is None or q.m == 0:
            return False

        pseudo_row = {'size': size_val, 'price': price_val, 'unit': unit}
        new_rate = self._rate_for_row(pseudo_row)
        if new_rate is None:
            return False

        if old_rate is None:
            # No baseline to compare against -- size now parses, that's all we can check.
            return True

        comparable = self._comparable_rates(new_rate, old_rate, conversions)
        if comparable is None:
            return False  # can't compare -- leave it as unresolved rather than claim success

        new_val, old_val = comparable
        if old_val == 0:
            return False
        ratio = new_val / old_val
        return (1 / self.SIZE_RATIO_THRESHOLD) <= ratio <= self.SIZE_RATIO_THRESHOLD

    def create_size_review_interface(self):
        """Create interface for correcting rows with suspicious/unparseable sizes"""
        self.size_review_area.children = [
            widgets.HTML(value=(
                "<h4>Review Sizes</h4>"
                "<p>These items have a size that couldn't be read, or a price that "
                "looks far off (more than 4x) from the last known price. Correct "
                "the size and/or price below if needed -- the $/quantity comparison "
                "updates as you edit -- then click Apply Corrections.</p>"
            ))
        ]
        self.size_review_widgets = {}

        if self.order_data is None:
            self.size_review_area.layout.display = 'none'
            return

        flagged = self._flag_size_issues(self.order_data)
        if not flagged:
            self.size_review_area.layout.display = 'none'
            return

        for idx, info in flagged.items():
            row = self.order_data.loc[idx]
            description = row['description'] if pd.notna(row['description']) else "No description"
            product_num = row['number'] if pd.notna(row['number']) else "No number"
            unit = row.get('unit')
            nickname = row.get('nickname')

            old_rate = info['old_rate']
            conversions = []
            if self.cc is not None and pd.notna(nickname) and nickname != '':
                existing = self.cc.uni_g.loc[self.cc.uni_g['nickname'] == nickname]
                if not existing.empty:
                    conversions = self._nickname_conversions(row, existing)

            size_input = widgets.Text(
                value=str(row['size']) if pd.notna(row['size']) else '',
                placeholder='e.g. 6/10 oz',
                continuous_update=False,
                layout=widgets.Layout(width='120px')
            )
            price_input = widgets.Text(
                value=str(row['price']) if pd.notna(row['price']) else '',
                placeholder='price',
                continuous_update=False,
                layout=widgets.Layout(width='80px')
            )
            rate_display = widgets.HTML(
                value=f"<span style='color:inherit'>recent: {self._format_rate(old_rate)} "
                      f"&rarr; new: {self._format_rate(info['new_rate'])}</span>"
            )

            row_widget = widgets.HBox([
                widgets.HTML(
                    value=f"<b>{description}</b> (#{product_num}) &mdash; {info['reason']}",
                    layout=widgets.Layout(width='420px', overflow='hidden')
                ),
                widgets.Label(value='size:'),
                size_input,
                widgets.Label(value='price:'),
                price_input,
                rate_display,
            ], layout=widgets.Layout(padding='2px'))

            def _recompute(change, size_w=size_input, price_w=price_input,
                           rate_w=rate_display, unit=unit, old_rate=old_rate,
                           conversions=conversions, row_w=row_widget):
                pseudo_row = {'size': size_w.value, 'price': price_w.value, 'unit': unit}
                new_rate = self._rate_for_row(pseudo_row)
                rate_w.value = (f"<span style='color:inherit'>recent: {self._format_rate(old_rate)} "
                                 f"&rarr; new: {self._format_rate(new_rate)}</span>")
                # Any further edit invalidates a previous "applied" checkmark
                # until Apply Corrections is clicked again.
                row_w.layout.border = ''

            size_input.observe(_recompute, names='value')
            price_input.observe(_recompute, names='value')

            self.size_review_widgets[idx] = {
                'size_input': size_input,
                'price_input': price_input,
                'row_widget': row_widget,
                'unit': unit,
                'old_rate': old_rate,
                'conversions': conversions,
            }

            self.size_review_area.children = list(self.size_review_area.children) + [row_widget]

        apply_button = widgets.Button(
            description='Apply Corrections',
            button_style='info',
            layout=widgets.Layout(width='160px')
        )
        apply_button.on_click(self.apply_size_corrections)
        self.size_review_area.children = list(self.size_review_area.children) + [apply_button]

        self.size_review_area.layout.display = 'flex'

    def apply_size_corrections(self, button):
        """Write corrected size/price values back into order_data, and mark
           each row resolved (green outline) or not -- without removing any
           rows from view.
        """
        applied = 0
        for idx, entry in self.size_review_widgets.items():
            size_input = entry['size_input']
            price_input = entry['price_input']
            row_widget = entry['row_widget']

            new_size = size_input.value.strip()
            new_price_str = price_input.value.strip()
            if new_size:
                self.order_data.at[idx, 'size'] = new_size
            if new_price_str:
                try:
                    self.order_data.at[idx, 'price'] = float(new_price_str.replace('$', ''))
                except ValueError:
                    pass
            applied += 1

            resolved = self._row_is_resolved(
                size_input.value, price_input.value,
                entry['unit'], entry['old_rate'], entry['conversions']
            )
            row_widget.layout.border = '2px solid #28a745' if resolved else ''

        with self.status_output:
            print(f"Applied {applied} size/price correction(s).")
    
    def _read_csv_ragged(self, file_path, header=None):
        """pandas.read_csv refuses a file where rows have different field
        counts, but a real order-guide CSV -- like its Excel counterpart --
        typically starts with short preamble/title rows (a company name, an
        "as of" date) before the real, wider header+data rows, and errors
        out on the mismatch. Read it with the stdlib csv module instead,
        which tolerates that, then pad every row out to the widest row's
        length (NaN-filling short and blank cells) so the result is a plain
        rectangular grid -- same shape pd.read_excel would give, so every
        existing header-row-detection / date-scanning / column-mapping call
        downstream works completely unmodified either way.
        utf-8-sig handles a CSV saved from Excel on Windows, which commonly
        prefixes the file with a UTF-8 byte-order mark; it's a no-op for a
        plain UTF-8 file that doesn't have one. newline='' hands the file
        to csv.reader raw so it -- not TextIOWrapper -- is what interprets
        the \\r\\n line endings those same Windows exports usually have.
        """
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        width = max((len(r) for r in rows), default=0)
        rows = [[(None if (c is None or c == '') else c)
                 for c in (r + [None] * (width - len(r)))] for r in rows]
        df = pd.DataFrame(rows)
        if header is not None:
            df.columns = df.iloc[header]
            df.columns.name = None
            df = df.iloc[header + 1:].reset_index(drop=True)
        return df

    def _read_raw(self, file_path, header=None):
        """Read a price-list/confirmation file into a DataFrame -- csv or
        excel, dispatched on the file extension. This is the only
        format-aware code in the class; everything downstream (header-row
        detection, column mapping, date scanning) works on the resulting
        DataFrame the same way regardless of which format it came from.
        """
        if str(file_path).lower().endswith('.csv'):
            return self._read_csv_ragged(file_path, header=header)
        return pd.read_excel(file_path, header=header)

    def _find_header_row(self, df_raw):
        """Row index of the first row that looks like a column-header row
        -- contains 'Item #', 'Item#', 'Product #', or 'Product#' (space
        optional, case-insensitive). Shared by all four process_* methods
        so every one of them tolerates either header-naming convention,
        not just whichever style that particular supplier happened to use
        when this method was first written.
        """
        mask = df_raw.apply(
            lambda row: row.astype(str).str.contains(r'Item\s*#|Product\s*#', case=False, regex=True).any(),
            axis=1)
        if not mask.any():
            raise ValueError("Could not find header row with 'Product #' or 'Item #'")
        return df_raw.loc[mask].index[0]

    def read_order_file(self, file_path):
        """
        Read and process an order file (guide, confirmation, or a plain
        item/price-list csv)
        
        Parameters:
        file_path (str): Path to the file (.xls, .xlsx, or .csv)
        
        Returns:
        pd.DataFrame: Processed order data
        """
        # Read the entire file without specifying headers -- needed before
        # the type is known for certain, since content-sniffing (used when
        # the filename doesn't match a known naming convention) reads it.
        df_raw = self._read_raw(file_path, header=None)

        if not self.file_type:
            self.file_type = self.determine_file_type(file_path, df_raw)
        
        # Process based on file type
        if self.file_type == 'confirmation':
            return self.process_order_confirmation(df_raw, file_path)
        elif self.file_type == 'freshpoint_confirmation':
            return self.process_freshpoint_confirmation(df_raw, file_path)
        elif self.file_type == 'item_pricelist':
            return self.process_item_price_list(df_raw, file_path)
        else:
            # Default to guide processing
            return self.process_order_guide(df_raw, file_path)
    
    def process_order_confirmation(self, df_raw, file_path):
        """Process an order confirmation file"""
        # Find the date in the file (ship date for confirmations)
        self.order_date, self.all_found_dates = self.find_all_dates_in_data(df_raw)
        
        # Look for header row based on Product # or Item #
        header_row_index = self._find_header_row(df_raw)
        
        # Re-read the file starting from the header row
        df = self._read_raw(file_path, header=header_row_index)
        
        # Remove columns without a header value
        df = df.dropna(axis=1, how='all')
        
        # Map column names
        columnmap = {
            'Product #': 'number', 
            'Item #': 'number',
            'Item#': 'number',
            'Product#': 'number',
            'Description': 'description', 
            'Product': 'description',
            'Pack': 'size', 
            'Pack Size': 'size',
            'Size': 'size',
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
        header_row_index = self._find_header_row(df_raw)
        
        # Re-read the file starting from the header row
        df = self._read_raw(file_path, header=header_row_index)
        
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
        
        # Identify the header row (Product # / Item #, space optional)
        header_row_index = self._find_header_row(df_raw)
        
        # Re-read the file starting from the header row
        df = self._read_raw(file_path, header=header_row_index)
        
        # Remove columns without a header value
        df = df.dropna(axis=1, how='all')
        
        # Map column names
        columnmap = {
            'Product #': 'number', 
            'Item #': 'number',
            'Item#': 'number',
            'Product#': 'number',
            'Description': 'description', 
            'Product': 'description',
            'Pack': 'size', 
            'Pack Size': 'size',
            'Size': 'size',
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

    def process_item_price_list(self, df_raw, file_path):
        """Process a plain item/price-list export: just Item#/Product/
        Size/Price columns, no order quantities, and often no date
        anywhere in the file (a straight price catalog, not an order or
        confirmation) -- content-sniffed in determine_file_type when the
        filename itself gives no hint (e.g. a generic export name).

        Shares FreshPoint confirmation's header convention ('Item#', no
        space) and size cleanup (trailing case/pack codes like 'BG'/'CS'/
        'FL', non-breaking spaces), since every file seen in this shape so
        far has used the same formatting -- and defaults to supplier 'FP'
        on that same basis. Correct the supplier in the Explorer afterward
        if a particular file turns out to be from someone else; it's a
        per-row column like any other guide entry.
        """
        # Find a date in the file, if there is one -- these price-list
        # exports often don't carry one at all, in which case order_date
        # falls back to today and the "found dates" dropdown just has
        # nothing to offer, but the date picker itself is still right
        # there to set one manually before Update Prices.
        self.order_date, self.all_found_dates = self.find_all_dates_in_data(df_raw)

        header_row_index = self._find_header_row(df_raw)
        df = self._read_raw(file_path, header=header_row_index)

        # Remove columns without a header value and fully-empty rows
        df = df.dropna(axis=1, how='all')
        df = df.dropna(axis=0, how='all')

        # Map column names
        columnmap = {
            'Item#': 'number',
            'Product': 'description',
            'Size': 'size',
            'Price': 'price',
        }
        mymap = {key: value for key, value in columnmap.items() if key in df.columns}
        df = df.rename(columns=mymap)

        # Remove rows where number is NaN (not actual items -- e.g. the
        # trailing blank column this format's trailing comma produces)
        if 'number' in df.columns:
            df = df[df['number'].notna()]

        # Clean up the size column the same way FreshPoint confirmations do:
        # strip non-breaking spaces and trailing case/pack codes (BG/CS/FL/BX/...)
        if 'size' in df.columns:
            df['size'] = df['size'].astype(str).str.replace('\xa0', ' ').str.strip()
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

        # Plain price list -- no order quantities in this format
        df['order'] = 0
        df['supplier'] = 'FP'
        df['unit'] = 'ea'
        df['brand'] = ''
        df['note'] = ''
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
                
                # Force a full recompute. Resetting costdf['cost'] to 0
                # directly isn't enough on its own -- FastCostMixin memoizes
                # full recipe costs (self._memo) and leaf prices
                # (self._leaf_cost), and a memo hit skips recomputing (and
                # re-writing) entirely, leaving a zeroed column exactly as
                # zero. invalidate_all_costs() flushes those caches too and
                # zeroes the column as a proper float64 Series.
                if hasattr(self.cc, 'invalidate_all_costs'):
                    self.cc.invalidate_all_costs()
                elif hasattr(self.cc, 'costdf'):
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

                # self.cc is the same object the Explorer holds, but nothing
                # else pushes these in-place changes to its on-screen grid --
                # without this the Explorer keeps showing whatever it had
                # displayed before the order guide was processed.
                if self.explorer is not None:
                    self.explorer.refresh_after_external_update()
                
            except Exception as e:
                print(f"Error updating database: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def _current_database_filename(self):
        """The filename Save Database should write to: whatever's currently
        loaded in the Explorer's toolbar, or the legacy default if this
        reader wasn't wired up to an explorer (e.g. the standalone
        update_from_order_guides.py tool)."""
        if self.explorer is not None:
            fname = getattr(self.explorer.toolbar, 'database_filename', '').strip()
            if fname:
                return fname
        return 'amc_menu_database.xlsx'

    def save_database(self, button):
        """Save the updated database"""
        if self.cc is None:
            with self.status_output:
                self.status_output.clear_output()
                print("No Cost Calculator available to save.")
            return
        
        fname = self._current_database_filename()
        with self.status_output:
            self.status_output.clear_output()
            print(f"Saving database to '{fname}'...")
            
            try:
                self.cc.write_cc(fname)
                print(f"Database saved successfully to '{fname}'.")
                if self.explorer is not None:
                    self.explorer.toolbar.file_exists = True
            except Exception as e:
                print(f"Error saving database: {str(e)}")
                import traceback
                traceback.print_exc()
    def display(self):
        """Display the OrderGuideReader interface"""
        display(self.container)
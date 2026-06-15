import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display, clear_output
from costcalulator import CostCalculator
from utils import *

class DataFrameWidget:
    ''' ipywidgets based interactive interface for pandas
    '''
    
    def __init__(self, df, width='80px', enabled_columns=None, hide_columns=None, 
                 cc=CostCalculator(), output=widgets.Output(), trigger=None):
        self.df = df.reset_index(drop=True).copy()
        self.defcolor = widgets.Text().style.text_color
        self.width = width
        self.column_width = {}
        self.df_type = None
        self.enabled_columns = enabled_columns if enabled_columns else []
        self.hide_columns = hide_columns if hide_columns else []
        self.cc = cc
        nicks = set(cc.uni_g['nickname'].dropna().unique())
        ingrs = set(cc.costdf['ingredient'].dropna().unique())
        self.all_ingredients = nicks.union(ingrs)
        self.buttons = {}
        self.output = output
        self.num_cols = 0
        self.trigger = trigger
        self.last_lookup = ''
        self.last_lookup = ''
        self.equ_quant_precision = None
        self.equ_quant_unit = None              # target unit for "equ quant" column
        self.scale_factor = None                # current display scale ratio (float|None)
        self._pending_lookup_quantity = None    # set by on_lookup_click before trigger fires
        self._navigating_back = False           # True while on_back_click is executing;
                                                # tells update_search not to clear scale
        self.search_history = []
        self.scale_stack = []    # parallel to search_history; entry[i] = scale active at level i
        self.search_history = []  # Add this line for tracking history
        self.backbutton = widgets.Button(description='Back', disabled=True)
        self.backbutton.on_click(self.on_back_click) 
        self.cost_multipliers = [3.0, 3.5]
        
        # Add progress bar for loading
        self.progress_bar = widgets.IntProgress(
            value=0,
            min=0,
            max=100,
            description='Loading:',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='200px', visibility='hidden')
        )
        # self.findtype()
        if self.df.empty:
            self.df_type = None
        elif 'ingredient' in self.df.columns and len(self.df['ingredient'].dropna().unique()) == 1:
            self.df_type = 'mentions'
        elif 'nickname' in self.df.columns:
            self.df_type = 'guide'
        elif 'ingredient' in self.df.columns:
            self.df_type = 'recipe'
        else:
            self.df_type = None
            
        self.df_types = set(('guide', 'recipe', 'mentions'))
        
        self.grid = self._create_grid()

    def setdf(self, mylookup):
        self.last_lookup = mylookup
        mydf = self.cc.findframe(
            mylookup,
            equ_quant_unit=self.equ_quant_unit,
            equ_quant_precision=self.equ_quant_precision
        ).reset_index(drop=True).copy()
        self.df = mydf
        self.findtype()
        if (self.df_type == 'recipe'):
            colorder = ['item', 'ingredient', 'quantity', 'cost', 'equ quant']
            mydf = reorder_columns(mydf, colorder)
            mycolumns = [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            for cm in self.cost_multipliers:
                if cm > 0:
                    add_costx(mydf, cm)
            if 'menu price' in mydf.columns and len(self.cost_multipliers) > 0:
                add_netprofit(mydf, self.cost_multipliers[0])
            # Apply view-mode scaling after all columns are finalised.
            # This is purely cosmetic – cc.costdf is never touched.
            if self.scale_factor is not None:
                mydf = self._apply_scaling(mydf, self.scale_factor)
            self.df = mydf
            self.update_column_width()

        else:
            mycolumns = mydf.columns
            if (self.df_type == 'guide'):
                mycolumns = [x for x in mydf.columns if x not in ['myconversion', 'mycost']]
            else:
                mycolumns =  [x for x in mydf.columns if x not in self.hide_columns]
            mydf = mydf[mycolumns]
            self.df = mydf
            self.update_column_width()
            
            
    def update_column_width(self):
        def carlen(myval):
            myval = f"{myval:0.2f}" if isinstance(myval, float) else myval
            return len(str(myval))

        # Calculate maxlen using map
        try:
            maxlen = self.df.apply(lambda x: x.map(lambda y: 5 + 10 * carlen(y))).max().to_dict()
            
            # Calculate cn_len for column names
            cn_len = {c: 5 + 8 * len(str(c)) for c in self.df.columns}

            # Update column_width using the maximum value between maxlen and cn_len
            self.column_width = {c: max(maxlen[c], cn_len[c]) for c in maxlen}
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
        except:
            # If there's an error, create a default width for each column
            self.column_width = {c: 5 + 8 * len(str(c)) for c in self.df.columns}
            if self.df_type == 'recipe':
                self.column_width['item'] = 5 + 8 * len('recipe for:')
                
    def _apply_scaling(self, mydf, scale):
        '''Scale quantities and costs in a display copy of a recipe DataFrame.
 
        This never writes back to self.cc.costdf – it only modifies the copy
        that will be displayed to the user in view mode.
 
        Columns scaled:
          - quantity    : pint-aware string  ("1 cup"     → "0.5000 cup")
          - equ quant   : pint-aware string  ("236.5 g"   → "118.2 g"), skips n/a
          - cost        : float
          - cost N.Nx   : float  (any "cost N.Nx" column added by add_costx)
        '''
        # No-op for full batches: avoids reformatting original quantity strings
        # ("1 cup" would otherwise become "1.0000 cup").
        if abs(scale - 1.0) < 1e-9:
            return mydf
        for idx in mydf.index:
            # ── quantity ──────────────────────────────────────────────────────
            q_str = str(mydf.at[idx, 'quantity'])
            try:
                q = parse_quant(q_str)
                if q is not None and hasattr(q, 'm') and q.m > 0:
                    mydf.at[idx, 'quantity'] = f"{(q * scale):~.2f}"
            except Exception:
                pass

            # ── equ quant (skip blanks and "n/a") ────────────────────────────
            if 'equ quant' in mydf.columns:
                eq_str = str(mydf.at[idx, 'equ quant'])
                if eq_str not in ('', 'nan', 'n/a', 'None'):
                    try:
                        # equ quant is stored as "value unit_string" (e.g. "120.0 g",
                        # "384 1/8 tsp").  Extract the numeric part, scale it, reformat
                        # using the stored precision (or 4 dp by default).
                        import re as _re
                        m = _re.match(r'^\s*([\d.]+)\s*(.*)', eq_str)
                        if m:
                            num  = float(m.group(1)) * scale
                            unit = m.group(2).strip()
                            prec = self.equ_quant_precision if self.equ_quant_precision is not None else 4
                            mydf.at[idx, 'equ quant'] = f"{num:.{prec}f} {unit}".strip()
                        else:
                            # fallback: pint parse
                            eq = parse_quant(eq_str)
                            if eq is not None and hasattr(eq, 'm') and eq.m > 0:
                                prec = self.equ_quant_precision if self.equ_quant_precision is not None else 4
                                mydf.at[idx, 'equ quant'] = (
                                    f"{(eq * scale).magnitude:.{prec}f} {eq.units:~}"
                                )
                    except Exception:
                        pass
                    
            # ── cost ─────────────────────────────────────────────────────────
            if 'cost' in mydf.columns:
                try:
                    mydf.at[idx, 'cost'] = float(mydf.at[idx, 'cost']) * scale
                except (TypeError, ValueError):
                    pass
 
            # ── cost N.Nx columns (added by add_costx) ───────────────────────
            for col in mydf.columns:
                if col != 'cost' and col.startswith('cost') and col.endswith('x'):
                    try:
                        mydf.at[idx, col] = float(mydf.at[idx, col]) * scale
                    except (TypeError, ValueError):
                        pass
 
        return mydf
        
    def update_display(self):
        self.progress_bar.layout.visibility = 'visible'
        self.progress_bar.value = 0
        
        self.grid.disabled = True
        self.progress_bar.value = 20
        self.grid = self._create_grid()
        self.progress_bar.value = 90
        
        with self.output:
            self.output.clear_output(wait=True)
            display(self.grid)
        
        self.progress_bar.value = 100
        self.progress_bar.layout.visibility = 'hidden'

        if (self.trigger != None):
            if (self.df_type == 'recipe'):
                self.trigger(self.df.iloc[0]['ingredient'])
            elif (self.df_type == 'guide'):
                self.trigger(self.df.loc[0]['nickname'])

            
    def getlayout(self, col=None):
        if col and col in self.column_width:
            return {'width': f"{self.column_width[col]}px", 'padding': '0px 1px'}
        else:
            return {'width': self.width, 'padding': '0px 1px'}
        
    def findtype(self):
        if self.df.empty:
            self.df_type = None
        elif 'ingredient' in self.df.columns:
            if self.df.iloc[0]['item'] == 'recipe':
                self.df_type = 'recipe'                
            else:
                self.df_type = 'mentions'
        elif 'nickname' in self.df.columns:
            self.df_type = 'guide'
        else:
            self.df_type = None
        return self.df_type
        
    
    # Modify _create_grid method to update the progress bar
    def _create_grid(self):
        # Show progress bar
        self.progress_bar.layout.visibility = 'visible'
        self.progress_bar.value = 0
        
        # Create a list to store the widgets
        items = []
        
        self.num_cols = len(self.df.columns) + 1 # extra one for button
        total_rows = len(self.df)
        
        # Setup column names
        # add blank label in place of a button
        for i in range(self.num_cols - len(self.df.columns)):
            items.append(widgets.Label(value='', layout=self.getlayout()))
        
        # add column labels for each column at top of interface
        for col in self.df.columns:
            items.append(widgets.Label(value=col, layout=self.getlayout(col)))
            
        # Update progress
        self.progress_bar.value = 5
            
        # if we have a recipe df, add row at end for ability to add to ingredient to recipe
        if self.df_type == 'recipe':
            new_row = pd.DataFrame({column: [''] for column in self.df.columns})
            # set blank row up as a member of the recipe
            new_row['item'] = self.df.iloc[0]['ingredient']
            self.df = pd.concat([self.df, new_row], ignore_index=True)
            
        # Update progress
        self.progress_bar.value = 10

        # Create interface for each row of the DataFrame
        for index, row in enumerate(self.df.iterrows()):
            self.create_row(items, row[0], row[1])
            # Update progress based on how many rows we've processed
            if total_rows > 0:
                progress = 10 + int((index + 1) / total_rows * 80)
                self.progress_bar.value = min(progress, 90)
        
        # Create the grid with all items
        grid = widgets.GridBox(items, layout=widgets.Layout(grid_template_columns=f"repeat({self.num_cols}, {self.width})"))
        # set the width of the first column to 100 pixels
        grid.layout.grid_template_columns = f"{self.width} {'px '.join([str(self.column_width[x]) for x in self.df.columns])}px"
        
        # Update progress and hide progress bar
        self.progress_bar.value = 100
        self.progress_bar.layout.visibility = 'hidden'
        
        return grid
    
    def create_row(self, items, index, row):
        ''' given a 'row' from a dataframe and the 'index' of the row in the dataframe
            create ui widgets for the row and add the widgets to 'items'
        '''
        # Create a button for each row and associate it with the row index
        # only create lookup button for row with ingredients
        butlist = []
        
        def create_lookup_button():
            # check there is a valid thing to lookup
            button = widgets.Button(description=f'lookup', layout=self.getlayout())
            if self.cc.findframe(row['ingredient']).empty:
                button.disabled = True
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_lookup_click)
            return button
        
        def create_search_button():
            button = widgets.Button(description=f'search', layout=self.getlayout())
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_search_click)
            return button

        def create_duplicate_button():
            button = widgets.Button(description=f'duplicate', layout=self.getlayout(), button_style='info')
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_duplicate_click)
            return button
        
        def create_delete_button():
            # Add delete button
            button = widgets.Button(description=f'delete', layout=self.getlayout(), button_style='danger')
            button.tag = index  # Store the row index in the button's 'tag' attribute
            button.on_click(self.on_delete_click)
            return button
        
        def set_df_val(df, row, column, newval):
            df.loc[
                (
                    df['item'] == row['item']
                ) & 
                (
                    df['ingredient'] == row['ingredient']
                ), column] = newval

        def set_df_for_iq(df, row, column, newval):
            '''
                set a value for df, match ingredient, quantity
            '''
            df.loc[
                (
                    df['ingredient'] == row['ingredient']
                ) & 
                (
                    df['quantity'] == row['quantity']
                ), column] = newval
            
        def get_df_val(df, row, column):
            return df.loc[
                (
                    df['item'] == row['item']
                ) & 
                (
                    df['ingredient'] == row['ingredient']
                ), column].values[0]

            
        # Add an observer to the Text widget that enables the button when the content changes
        def on_text_change(change, column, widget):
            
            def _update_df(df, row, match_columns, update_column, new_value):
                # Build a NaN-aware boolean mask so that rows where a match
                # column contains NaN are handled correctly (NaN == NaN is
                # always False in pandas, which silently breaks the lookup).
                condition = pd.Series([True] * len(df), index=df.index)
                for col in match_columns:
                    val = row[col]
                    try:
                        val_is_nan = pd.isna(val)
                    except (TypeError, ValueError):
                        val_is_nan = False
                    if val_is_nan:
                        condition = condition & df[col].isna()
                    else:
                        condition = condition & (df[col] == val)
                df.loc[condition, update_column] = new_value
                
            # clear cost of each recipe containing ingredient
            def _clear_costs(nickname):
                mdf = self.cc.find_ingredient(nickname)
                for i,m in mdf.iterrows():
                    self.cc.set_item_ingredient(m['item'], nickname, 'cost', 0)
                    self.cc.clear_cost(m['item'])
            
            defmatch = ['nickname', 'description', 'size', 'price', 'date', 'supplier']
            newval = change['new']
            oldval = self.df.iloc[index][column]
                
            if column == 'quantity':
                if self.df_type == 'recipe':
                    recipename = self.df.iloc[0]['ingredient']
                    # only update as recipe if in recipe mode
                    # check that we are editting a quantity for a valid ingredient
                    if self.df.iloc[index]['ingredient'] in self.all_ingredients:
                        #newsize = parse_quant(newval)
                        #oldsize = parse_quant(oldval)
                        # print(f"{oldval=}, {newval=}")
                        row = self.df.iloc[index]
                        # set_df_val(cc.costdf, row, column, newval)
                        self.df.loc[index:index, column] = newval
                        if (newval != oldval):
    
                            #button[0].disabled = False
                            updatecost = True
                            set_df_val(self.cc.costdf, row, column, newval)
                            set_df_val(self.cc.costdf, row, 'cost', 0)
    
                            self.cc.clear_cost(recipename)
                            self.cc.recipe_cost(recipename)
                            self.setdf(recipename)
                            self.update_display()
                        
            elif column == 'ingredient':
                if self.df_type == 'recipe':
                    recipename = self.df.iloc[0]['ingredient']
                    # check if valid ingredient
                    if newval in self.all_ingredients:
                        widget.style.text_color = self.defcolor
                        # check if ingredient is alread in recipe
                        self.df.loc[index:index, 'item'] = recipename
                        if newval in self.cc.item_list(recipename)['ingredient'].unique():
                            # ignore (repeated ingredients not allowed)
                            print('already in recipe')
                        else:
                            # check if there was a valid old value
                            if oldval in self.all_ingredients:
                                self.cc.removeIngredient(recipename, oldval)

                            # add new row to costdf
                            # set quantity to zero if none
                            self.df.loc[index:index, 'ingredient'] = newval
                            quant = parse_quant(self.df.loc[index]['quantity'])
                            if not quant:
                                self.df.loc[index:index, 'quantity'] = '0'
                            self.df.loc[index:index, 'cost'] = 0
                            newdf = pd.DataFrame([self.df.iloc[index]])
                            self.cc.costdf = pd.concat([self.cc.costdf, newdf], ignore_index=True)

                            self.cc.clear_cost(recipename)
                            self.cc.recipe_cost(recipename)
                            self.setdf(recipename)
                            # self.df = self.cc.findframe(reciperow['ingredient']).reset_index(drop=True)
                            self.update_display()

                    else: # newval not an ingredient
                        if str(newval) == '':
                            self.cc.removeIngredient(recipename, oldval)
                            self.cc.clear_cost(recipename)
                            self.cc.recipe_cost(recipename)
                            self.setdf(recipename)
                            # self.df = self.cc.findframe(reciperow['ingredient']).reset_index(drop=True)
                            self.update_display()
                        else:
                            widget.style.text_color = 'red'
                            #widget.add_class('invalid-input')  # CSS class for invalid input

                            

            elif column == 'saved cost':
                # check if valid cost
                try:
                    newval = float(newval)
                    # check valid value
            
                except:
                    # clear saved cost?
                    newval = -1

                if self.df_type == 'recipe':
                    recipename = self.df.iloc[0]['ingredient']
                    # update saved cost
                    row = self.df.iloc[index]
                    if (newval < 0):
                        set_df_val(self.cc.costdf, row, 'saved cost', np.nan)
                        if (self.cc.use_saved):
                            self.cc.set_item_ingredient(recipename, row['ingredient'], 'cost', 0)
                            self.cc.costdf.loc[self.cc.costdf['ingredient'] == row['ingredient'],'cost'] = 0
                    else:
                        set_df_val(self.cc.costdf, row, 'saved cost', newval)
                    #set_df_val(cc.costdf, row, 'cost', newval)
                    
                    # zero out all affected cost
                    # parent recipe, 
                    self.cc.clear_cost(recipename)

                    self.cc.recipe_cost(recipename)
                    self.setdf(recipename)
                    print('saved cost')
                    self.update_display()
                    
            elif column == 'menu price':
                # check if valid cost
                try:
                    newval = float(newval)
                    # check valid value
            
                except:
                    print('invalid menu price')
                    return

                if self.df_type == 'recipe':
                    recipename = self.df.iloc[0]['ingredient']
                    # update menu price
                    row = self.df.iloc[index]
                    #self.cc.costdf.loc[self.costdf['']
                    set_df_for_iq(self.cc.costdf, row, 'menu price', newval)
                    self.setdf(recipename)
                    self.update_display()

            elif column == 'date':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    # match nickname, description, size, date
                    mydate = pd.to_datetime(newval, errors='coerce')
                    if (mydate is pd.NaT):
                        # don't update if date if the input is invalid
                        self.update_display()
                    else:
                        mydate = mydate.strftime('%Y-%m-%d')
                        
                        _update_df(self.cc.uni_g, row, defmatch, 'date', mydate)
                        
                        _clear_costs(row['nickname'])

                        self.setdf(row['nickname'])
                        self.update_display()
                    
            elif column == 'size':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    newval = newval.strip()
                    newsize = parse_size(newval)
                    if (newval in ['', '-', '0']) or (newsize.m <= 0):
                        # ignore blank size, 0 size
                        self.update_display()
                    else:
                        # match nickname, description, size, date
                        _update_df(self.cc.uni_g, row, defmatch, 'size', newval)
                        _clear_costs(row['nickname'])
    
                        self.setdf(row['nickname'])
                        self.update_display()
                        # update mention display?
            
            elif column == 'price':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    try:
                        newval = float(newval)
                    except:
                        print('bad new price')
                        return

                    # match nickname, description, size, date, and update
                    _update_df(self.cc.uni_g, row, defmatch, 'price', newval)
                    
                    # clear cost of each recipe containing ingredient
                    _clear_costs(row['nickname'])

                    self.setdf(row['nickname'])
                    self.update_display()
                    # update mention display?
                    
            elif column == 'supplier':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    # match nickname, description, size, date, and update
                    _update_df(self.cc.uni_g, row, defmatch, 'supplier', newval)          
                    # clear cost of each recipe containing ingredient
                    _clear_costs(row['nickname'])

                    self.setdf(row['nickname'])
                    self.update_display()
                    # update mention display?
                    
            elif column == 'order':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    try:
                        newval = str(newval)
                    except:
                        print('bad order value')
                        return

                    # match nickname, description, size, date, and update
                    _update_df(self.cc.uni_g, row, defmatch, 'order', newval)          
                    
                    # clear cost of each recipe containing ingredient
                    _clear_costs(row['nickname'])
                    
                    self.setdf(row['nickname'])
                    self.update_display()
                    
            elif column == 'description':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    # match nickname, description, size, date, and update
                    _update_df(self.cc.uni_g, row, defmatch, 'description', newval)          
                    self.setdf(row['nickname'])
                    self.update_display()
                    # update mention display?
                    
            elif column == 'allergen':
                if self.df_type == 'guide':
                    row = self.df.iloc[index]
                    # match nickname, description, supplier
                    _update_df(self.cc.uni_g, row, ['nickname', 'description', 'supplier'], 'allergen', newval)          
                    self.setdf(row['nickname'])
                    self.update_display()
                    # update mention display?
                    
            # elif column == 'conversion':
            #     if (self.df_type == 'guide') or (self.df_type == 'recipe'):
            #         row = self.df.iloc[index]
            #         newval = newval.strip()
            #         # check valid conversion
            #         convrs = parse_conversion(newval)
            #         if len(convrs) > 0 or newval == '':
            #             # set convrs
            #             if self.df_type == 'recipe':
            #                 _update_df(self.cc.costdf, row, ['ingredient', 'item', 'quantity'], 'conversion', newval)
            #                 _clear_costs(row['ingredient'])
            #                 self.setdf(row['ingredient'])
            #             else:
            #                 _update_df(self.cc.uni_g, row, ['nickname', 'description', 'size', 'supplier'], 'conversion', newval)
            #                 _clear_costs(row['nickname'])
            #                 self.setdf(row['nickname'])
            #             self.update_display()
            elif column == 'conversion':
                if (self.df_type == 'guide') or (self.df_type == 'recipe'):
                    row = self.df.iloc[index]
                    newval = newval.strip()
                    # check valid conversion
                    convrs = parse_conversion(newval)
                    if len(convrs) > 0 or newval == '':
                        # Valid (or cleared) — remove any conversion error flag and border
                        ingredient_key = row.get('ingredient', row.get('nickname', ''))
                        conv_errors = getattr(self.cc, 'conversion_errors', set())
                        conv_errors.discard(ingredient_key)
                        widget.layout.border = ''
                        # set convrs
                        if self.df_type == 'recipe':
                            _update_df(self.cc.costdf, row, ['ingredient', 'item', 'quantity'], 'conversion', newval)
                            _clear_costs(row['ingredient'])
                            self.setdf(row['ingredient'])
                        else:
                            _update_df(self.cc.uni_g, row, ['nickname', 'description', 'size', 'supplier'], 'conversion', newval)
                            _clear_costs(row['nickname'])
                            self.setdf(row['nickname'])
                        self.update_display()
                    else:
                        # Invalid format typed — show red border immediately as feedback
                        widget.layout.border = '2px solid red'
        
        # add button based on what type of dataframe we have
        if self.df_type:
            if self.df_type == 'recipe':
                if row['item'] == 'recipe':
                    butlist.append(create_search_button())
                else:
                    butlist.append(create_lookup_button())
            elif self.df_type == 'guide':
                butlist.append(create_duplicate_button())
                butlist.append(create_delete_button())
            elif self.df_type == 'mentions':
                butlist.append(create_lookup_button())
                
            self.buttons[index] = butlist[0]
            items.append(widgets.HBox(butlist))

            
        # Create a Text widget for each cell in the row
        for col in self.df.columns:
            # is_disabled = (col not in self.enabled_columns) or (self.df_type == 'mentions' and col == 'ingredient')
            is_disabled = (col not in self.enabled_columns) or (self.df_type == 'mentions' and col == 'ingredient')

            # Recipe conversion override:
            #   • Header row (item == 'recipe') → editable only in Edit mode,
            #     i.e. when 'conversion' is present in enabled_columns.
            #   • Ingredient rows               → never editable here; use the Guide.
            if col == 'conversion' and self.df_type == 'recipe':
                if row['item'] == 'recipe':
                    is_disabled = 'conversion' not in self.enabled_columns
                else:
                    is_disabled = True
            # hide cell visibility
            hide = False
            # Simplifying value assignment and handling for 'myval'
            if str(row[col]) not in [str(np.nan), '']:
                 myval = row[col]
            else:
                myval = ''
                hide = True
            #myval = row[col] if str(row[col]) not in [str(np.nan), ''] else '-'
            myval = f"{myval:0.2f}" if isinstance(myval, float) else myval

            # Widget assignment based on 'item' and 'df_type'
            if col == 'item':
                if myval == 'recipe':
                    cell_widget = widgets.Label(value='recipe for:', layout=self.getlayout(col), style={'font_style': 'italic'})
                elif self.df_type == 'mentions':
                    cell_widget = widgets.Label(value=str(myval), layout=self.getlayout())
                else:
                    cell_widget = widgets.Label()
            else:
                if is_disabled or (col == 'ingredient' and self.df_type == 'recipe' and row['item'] == 'recipe'):
                    cell_widget = widgets.Label(value=str(myval), layout=self.getlayout(col))
                else:
                    if (col == 'ingredient') and (self.df_type == 'recipe'):
                        cell_widget = None
                        if (myval == ''): # use combobox for blank item
                            cell_widget = widgets.Combobox(
                                value = str(myval),
                                options=tuple(self.all_ingredients),
                                ensure_option=False,
                                disabled=is_disabled,
                                continuous_update=False,
                                layout = self.getlayout(col)
                            )
                        else:
                            cell_widget = widgets.Text(
                                value = str(myval),
                                #options=tuple(self.all_ingredients),
                                ensure_option=False,
                                disabled=is_disabled,
                                continuous_update=False,
                                layout = self.getlayout(col)
                            )
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget: on_text_change(change, col, cell_widget), 'value')
                    else:
                        cell_widget = widgets.Text(
                            value=str(myval), 
                            layout=self.getlayout(col), 
                            disabled=is_disabled, 
                            continuous_update=False
                        )
                        # Highlight conversion cell when a unit conversion is missing
                        if col == 'conversion' and not is_disabled:
                            ingredient_key = row.get('ingredient', row.get('nickname', ''))
                            conv_errors = getattr(self.cc, 'conversion_errors', set())
                            if ingredient_key and ingredient_key in conv_errors:
                                cell_widget.layout.border = '2px solid red'
                        cell_widget.observe(lambda change, col=col, cell_widget=cell_widget: on_text_change(change, col, cell_widget), 'value')


            if (hide and is_disabled):
                cell_widget.layout.visibility = 'hidden'
            items.append(cell_widget)
            
    # def on_back_click(self, button):
    #     """Handle back button click"""
    #     if len(self.search_history) > 1:
    #         self.search_history.pop()  # Remove current
    #         previous = self.search_history[-1]  # Get previous without popping it
            
    #         # Store current search_history
    #         saved_history = self.search_history.copy()
            
    #         # Look up the previous item without adding to history
    #         self.setdf(previous)
            
    #         # Restore history
    #         self.search_history = saved_history
            
    #         # Update the back button state
    #         self.backbutton.disabled = len(self.search_history) <= 1
            
    #         # Update display
    #         self.update_display()
    def on_back_click(self, button):
        '''Navigate to the previous item in the search history.
 
        Restores the scale_factor that was active at that history level so nested
        scaled recipes remain correct at every depth.
 
        Sets self._navigating_back = True so that if DataFrameExplorer subsequently
        fires update_search (e.g. to sync searchinput.value), that handler will
        not overwrite the scale_factor we just restored.
 
        scale_stack layout
        ──────────────────
          index 0  root recipe        → scale None  (always unscaled)
          index 1  first sub-recipe   → scale 0.5   (parent used ½ the yield)
          index 2  second sub-recipe  → scale 0.5   (that sub used ½ of its yield)
 
        Popping one level restores stack[-1], which is exactly the scale that was
        active when the now-current item was first navigated to.
        '''
        self._pending_lookup_quantity = None
 
        if len(self.search_history) > 1:
            self.search_history.pop()
            if self.scale_stack:
                self.scale_stack.pop()
 
            # Restore the scale that belongs to the level we are going back to
            self.scale_factor = self.scale_stack[-1] if self.scale_stack else None
 
            # Signal update_search (if it fires) to preserve this scale
            self._navigating_back = True
 
            previous = self.search_history[-1]
            saved_history = self.search_history.copy()
            saved_stack   = self.scale_stack.copy()
 
            self.setdf(previous)          # uses the just-restored scale_factor
 
            self.search_history = saved_history
            self.scale_stack    = saved_stack
 
            self.backbutton.disabled = len(self.search_history) <= 1
            self.update_display()
 
            # If DataFrameExplorer did NOT fire update_search (no extra handler),
            # _navigating_back would stay True indefinitely.  Clear it here as a
            # safety net; update_search clears it first if it runs.
            self._navigating_back = False
                    
    def on_duplicate_click(self, button):
        row = self.df.loc[button.tag]
        newdate = pd.to_datetime('today').strftime('%Y-%m-%d')
        if newdate != row['date']:
            newrow = row.copy()
            newrow['date'] = newdate
            # add only recognized guide columns
            newrow = newrow[self.cc.guide_columns]
            newdf = pd.DataFrame([newrow])
            self.cc.uni_g = pd.concat([self.cc.uni_g, newdf], ignore_index=True)

            # clear cost of each recipe containing ingredient
            mdf = self.cc.find_ingredient(row['nickname'])
            for i,m in mdf.iterrows():
                self.cc.set_item_ingredient(m['item'], row['nickname'], 'cost', 0)
                self.cc.clear_cost(m['item'])

            self.setdf(row['nickname'])
            self.update_display()
        else:
            print("Can't duplicate! Dates must be different")
    
    def on_delete_click(self, button):
        """Handle delete button click - remove the specific row from uni_g"""
        row_index = button.tag
        row = self.df.loc[row_index]
        # Get the index in the original uni_g DataFrame
        # We need to find the exact row in uni_g that corresponds to this row in our display
        # Match on multiple columns to ensure we get the exact row
        match_cols = ['nickname', 'description', 'size', 'price', 'date', 'supplier']
        match_dict = {col: row[col] for col in match_cols if col in row.index}
        
        # Find the index in the original DataFrame
        mask = True
        for col, val in match_dict.items():
            mask = mask & (self.cc.uni_g[col] == val)
        
        # If we found a match, delete just that row
        if any(mask):
            # Get the index in the original DataFrame
            original_index = self.cc.uni_g[mask].index[0]
            
            # Delete only this specific row
            self.cc.uni_g = self.cc.uni_g.drop(original_index).reset_index(drop=True)
            
            # Update the search options
            if hasattr(self, 'all_ingredients'):
                nicks = set(self.cc.uni_g['nickname'].dropna().unique())
                ingrs = set(self.cc.costdf['ingredient'].dropna().unique())
                self.all_ingredients = nicks.union(ingrs)
                        
            self.setdf(row['nickname'])
            self.update_display()

            
    def on_search_click(self, button):
        # Retrieve the row from the DataFrame using the button's 'tag' attribute
        row = self.df.loc[button.tag]
        
        # load mentions of the ingredient
        if self.df_type == 'recipe':
            self.search_name(row['ingredient'])
        elif self.df_type == 'mentions':
            self.search_name(row['item'])
        elif self.df_type == 'guide':
            self.search_name(row['nickname'])
        self.update_display()

    # def on_lookup_click(self, button):
    #     # Retrieve the row from the DataFrame using the button's 'tag' attribute
    #     row = self.df.loc[button.tag]
            
    #     # Update the DataFrame and the grid
    #     if self.df_type == 'recipe':
    #         if row['item'] != 'recipe':
    #             self.trigger(row['ingredient'])

    #     elif self.df_type == 'mentions':
    #         self.trigger(row['item'])

    #     button.disabled = True
    def on_lookup_click(self, button):
        '''Navigate to the ingredient's own recipe / guide entry.
 
        Before calling the trigger we store the parent-recipe quantity of this
        ingredient so DataFrameExplorer.trigger_update can compute a scale
        factor and display the sub-recipe scaled to exactly the amount required
        by the parent recipe (view mode only).
        '''
        row = self.df.loc[button.tag]
 
        if self.df_type == 'recipe':
            if row['item'] != 'recipe':
                # Save the quantity used in the parent recipe for scale calculation
                self._pending_lookup_quantity = row.get('quantity', None)
                self.trigger(row['ingredient'])
 
        elif self.df_type == 'mentions':
            self._pending_lookup_quantity = None   # no scaling for mention lookups
            self.trigger(row['item'])
 
        button.disabled = True

    def search_name(self, search):
        self.df = self.cc.find_ingredient(search).reset_index(drop=True)
        # calculate cost for each mention
        for i, row in self.df.iterrows():
            cost = self.cc.item_cost(row['item'], row['ingredient'])
            
        self.df = self.cc.find_ingredient(search).reset_index(drop=True)
        self.df = self.df.loc[self.df['item'] != 'recipe']
        mycolumns = [x for x in self.df.columns if x not in self.hide_columns]
        self.df = self.df[mycolumns]
        self.findtype()
        if self.df_type == 'mentions':
            if self.df.empty:
                return
        else:
            pass
            #print("my type: ", self.df_type)
        self.update_column_width()
        
                
    def lookup_name(self, lookup):
        # Update the DataFrame and the grid
        self.setdf(lookup)
        self.findtype()
        if self.df_type == 'recipe':
            self.cc.recipe_cost(self.df.iloc[0]['ingredient'])
            self.setdf(lookup)
        
        # Mirror scale_factor into scale_stack whenever a new entry is pushed.
        # scale_factor has already been set by DataFrameExplorer.update_search
        # (or left unchanged by on_back_click) before lookup_name is called.
        if not self.search_history or lookup != self.search_history[-1]:
            self.search_history.append(lookup)
            self.scale_stack.append(self.scale_factor)
        
        # Update back button state
        self.backbutton.disabled = len(self.search_history) <= 1

    def get_widget(self):
        return(self.grid)
    
    def display(self):
        # Display the GridBox
        with self.output:
            self.output.clear_output(wait=True)
            display(self.grid)
        display(self.output)


class DisplayDataFrameWidget(DataFrameWidget):
    def on_lookup_click(self, button):
        # Retrieve the row from the DataFrame using the button's 'tag' attribute
        row = self.df.loc[button.tag]
        # if a trigger was set
        if (self.trigger != None):
            if (self.df_type == 'recipe'):
                 if row['item'] != 'recipe':
                    self.trigger(row['ingredient'])

            elif self.df_type == 'mentions':
                self.trigger(row['item'])
            elif (self.df_type == 'guide'):
                self.trigger(row['nickname'])

        button.disabled = True
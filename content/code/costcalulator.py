# costcalculator.py
import pandas as pd
import numpy as np
from datetime import datetime
from utils import *

class CostCalculator:
    def __init__(self, filename=None, costpicker=None):
        self.costdf = pd.DataFrame()
        self.uni_g = pd.DataFrame()
        self.guide_sheet_name = 'unified - guide'
        self.cost_sheet_name = 'menu - cost'
        self.guide_columns = ['supplier', 'description', 'number', 'price', 'unit', 'size', 'brand', 'order', 'nickname', 'note', 'allergen', 'conversion', 'date']
        self.cost_columns = ['item', 'ingredient', 'quantity', 'cost', 'conversion', 'note', 'menu price']
        self.costdf_order = ('item', 'ingredient', 'quantity', 'equ quant', 
                'cost', 'cost 3.0x', 'menu price')
        self.uni_g_order = ('nickname',  'price', 'unit', 'size', '$/quant',
               'conversion', 'description', 'supplier', 'date')
        self.uni_g_easyorder = ('nickname', '$/quant', 'price', 'size', 'supplier', 'date', 'description', 'conversion')
        self.use_saved = False

        def defcostpicker(cdf):
            return pick_recent_cost(cdf)
            
        if costpicker:
            self.cost_picker = costpicker
        else:
            self.cost_picker = defcostpicker
        
        if filename:
            self.read_from_xlsx(filename)

    def guide_lookup(self, nick):
        ''' search order guide for nickname == nick
            if no results: try searching description
        '''
        glist = self.uni_g.loc[self.uni_g['nickname'] == nick]
        if glist.empty:
            search = nick
            results = self.uni_g[self.uni_g['description'].str.contains(search, case=False)].copy()
            if len(results) < 1:
                maybeprint(f"{search = } not found!\n")
                return pd.DataFrame()
            else:
                return results.loc[:, ['description', 'supplier', 'price', 'unit', 'size', 'nickname', 'conversion', 'date']]
        else:
            return glist.loc[:, ['description', 'supplier', 'price', 'unit', 'size', 'nickname', 'conversion', 'date']]
    
    def get_cost_df(self, myingr, myquant=None):
        ''' get a dataframe with list of the possible non-zero costs
            given an ingredient and quantity
        '''
        if myquant != None:
            myquant = parse_quant(myquant)
                
        results = self.find_nick(myingr)
        mydf = pd.DataFrame()
        # get a list of all conversions
        convr = set(results['conversion'].dropna().unique())
    
        for i, r in results.iterrows():
            quant = parse_size(r['size'])
            price = r['price']
            
            thisconv = list(convr)
            if isinstance(r['conversion'], str):
                thisconv = [r['conversion']]
                for c in convr:
                    if not (c in convr):
                        thisconv.append(c)

            if isinstance(price, str):
                price = float(price.strip('$'))
            if (price <= 0):
                maybeprint(f"!!! no price for: {myingr}")
            if (r['unit'] in ['lb', 'LB', 'Lb']):
                quant = Q_('1 lb')
                
            nextprice = 0
            myconv = 1
            if (myquant == None):
                myquant = Q_(f"1 {str(quant.units)}")
            if (myquant.m == 0):
                myquant = Q_(f"0 {str(quant.units)}")
            else:
                nextprice, myconv = quantity_cost_and_conv(price/quant, myquant, parse_unit_conversion(thisconv))
                
            if (nextprice >= 0):
                r['mycost'] = nextprice
                r['myconversion'] = str(myconv)
                #r['quantity'] = myquant
                r['$/quantity'] = str(price/quant)
                r['$/quant'] = f"{price/quant:~.2f}"
                mydf = pd.concat([mydf, pd.DataFrame([r])], ignore_index=True)
            else:
                maybeprint(f"! zero cost, {myingr}, {myquant}")
        if len(mydf) == 0:
            print(f"!!! no cost found for: {myingr}, {myquant}")
        return mydf
        



    def get_item_ingredient(self, item, ingredient):
        return self.costdf.loc[(self.costdf['item'] == item) & (self.costdf['ingredient'] == ingredient)]
        #if recipe_entry.empty:
    
    def get_recipe_entry(self, inick):
        ''' get the recipe entry for inick
        '''
        recipe_entry = self.costdf.loc[(self.costdf['item'] == 'recipe') & (self.costdf['ingredient'] == inick)]
        #if recipe_entry.empty:
        #    print(f'no recipe for {inick} found')
            # recipe_entry = self.costdf.loc[(self.costdf['ingredient'] == inick)]
        return recipe_entry

    def set_recipe_entry(self, inick, column_name, value):
        ''' set a value (cost, saved cost, quantity....) for a recipe entry
            column_name (column to set) value (value to set)
            recipe entrys are (should be) unique
        '''
        self.costdf.loc[(self.costdf['item'] == 'recipe') & (self.costdf['ingredient'] == inick),
            column_name] = value
        
    def set_item_ingredient(self, item, ingredient, column_name, value):
        ''' set a value for specified column (column_name) for (unique) entry
            which matches 'item' == item, 'ingredient' == ingredient
        '''
        # If the column is 'cost' or contains 'cost' in its name, ensure it's float type
        if column_name == 'cost' or 'cost' in column_name.lower():
            # First convert the column to float if it's not already
            if self.costdf[column_name].dtype != 'float64':
                self.costdf[column_name] = self.costdf[column_name].astype('float64')
            
            # Ensure the value is float
            if not isinstance(value, float) and value is not None:
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    print(f"Warning: Could not convert value '{value}' to float for column '{column_name}'")
        
        # Now set the value
        self.costdf.loc[(self.costdf['item'] == item) & (self.costdf['ingredient'] == ingredient),
            column_name] = value

    def get_simple_ingredient_cost(self, inick, iquant):
        ''' get cost from the price guide, using weighted average if possible '''
        cdf = self.get_cost_df(inick, iquant)
        if cdf.empty:
            return 0
        
        # Get selected costs using the cost picker
        selected_costs = self.cost_picker(cdf)
        
        # Calculate weighted cost
        cost = calculate_weighted_cost(selected_costs)
        
        return cost
    
    def find_nick(self, inick):
        return self.uni_g.loc[self.uni_g['nickname'] == inick]
    
    def find_ingredient(self, inick, iquant=None):
        if (iquant == None):
            return self.costdf.loc[(self.costdf['ingredient'] == inick)]
        else:
            return self.costdf.loc[(self.costdf['ingredient'] == inick) & (self.costdf['quantity'] == iquant)]
    
    def item_cost(self, myitem, inick):
        ''' calulate the cost given an item, nickname and quantity
        '''
        def lookup(mycolumn):
            return self.costdf.loc[(self.costdf['item'] == myitem) & (self.costdf['ingredient'] == mynick), mycolumn].squeeze()
            
        def getsaved(myitem, mynick):
            return self.costdf.loc[
                (self.costdf['item'] == myitem) &
                (self.costdf['ingredient'] == mynick), 'saved cost'
            ].squeeze()

        inick = inick.strip()
        myitem = myitem.strip()
        myrow = self.get_item_ingredient(myitem, inick).squeeze()
        iquant = myrow['quantity']
        # check current line
        # check if we should use saved cost
        savedcost = getsaved(myitem, inick)
        if savedcost and float(savedcost) >= 0:
            savedcost = float(savedcost)
        else:
            savedcost = -1

            
        if (self.use_saved and (savedcost >= 0)):
            self.set_item_ingredient(myitem, inick, 'cost', savedcost)
            return savedcost
            
        results = self.find_nick(inick)
        cost = 0
        if results.empty:
            # check recipe location for saved cost
            # look up item, ingredient
            recipe_entry = self.get_recipe_entry(inick)

            if recipe_entry.empty: # no recipe found
                # use saved cost if it exists
                if (savedcost >= 0):
                    self.set_item_ingredient(myitem, inick, 'cost', savedcost)
                    return savedcost
                else:
                    print(f"!!!unknown recipe! {myitem}, {inick}, {iquant}")
                    return 0
            else: # a recipe was found
                if len(recipe_entry) > 1:
                    print(f'mulitple recipes found for {inick}')
                recipe_entry = recipe_entry.squeeze()
                recipe_cost = 0
                
                # use user defined cost if it exists
                if self.use_saved and float(recipe_entry['saved cost']) > 0:
                    recipe_cost = float(recipe_entry['saved cost'])
                else:
                    # use previous calculation
                    recipe_cost = float(recipe_entry['cost'])
                    
                if (recipe_cost > 0):
                    myquant = parse_quant(iquant)
                    #myquant = Q_(iquant.replace('ct', 'count'))
                    #recipe_quant = Q_((recipe_entry['quantity']).replace('ct', 'count'))
                    recipe_quant = parse_quant(recipe_entry['quantity'])
                    
                        
                    # if my quantity and recipe quantity are of same dimensionality
                    if (myquant.dimensionality == recipe_quant.dimensionality):
                        cost = recipe_cost * (myquant/recipe_quant).to_reduced_units().m
                        self.set_item_ingredient(myitem, inick, 'cost', cost)
                        return cost
                    else:
                        if isinstance(recipe_entry['conversion'], str):
                            conv = parse_unit_conversion(recipe_entry['conversion'])
                            cost, myconv = quantity_cost_and_conv(
                                recipe_cost/recipe_quant, myquant, conv)
                            if (cost < 0):
                                print(f'no conversion found, for {inick, iquant}')
                                return 0
                            else:
                                # We are done! save cost, and return
                                self.set_item_ingredient(myitem, inick, 'cost', cost)
                                return cost
                                
                        else:
                            print(f'no conversion found, for {inick, iquant}')
                            return 0
                else: # we need to calculate underlying recipe!
                    recipe = self.item_list(inick)
                    if (recipe.empty):
                        return recipe_cost
                    else:
                        # loop through ingredient list
                        for i, subitem in recipe.iterrows():
                            subnick = subitem['ingredient']
                            subquant = subitem['quantity']
                            subcost = 0
                            
                            # first try to use saved cost
                            subsaved = subitem['saved cost']
                            if subsaved and (float(subsaved) >= 0):
                                subsaved = float(subsaved)
                            else:
                                subsaved = -1
                            #try:
                            #    subsaved = float(subitem['saved cost'])
                            #except:
                            #    subsaved = -1

                            # first see if we are using a saved cost
                            if (self.use_saved) and (subsaved >= 0):
                                subcost = subsaved
                                # set cost of sub item
                                self.set_item_ingredient(inick, subnick, 'cost', subcost)
                            # look for an already computed cost
                            elif float(subitem['cost']) > 0:
                                subcost = float(subitem['cost'])
                            # otherwise next compute the cost
                            else:
                                subcost = self.item_cost(inick, subnick)
                                if (subcost > 0):
                                    #subcost = float(subcost)
                                    pass
                                else:
                                    if (subsaved >= 0):
                                        subcost = subsaved
                                    else:
                                        subcost = 0
                                        if parse_quant(subquant).m != 0:
                                            print(f'no cost!, {subnick}, {subquant}')
                                self.set_item_ingredient(inick, subnick, 'cost', subcost)

                            cost = cost + subcost
                        
                        # need take fraction of the cost
                        # if we are looking for ct (count) quantity

                        myquant = parse_quant(iquant)
                        recipe_quant = parse_quant(recipe_entry['quantity'])
                        conv = parse_unit_conversion(recipe_entry['conversion'])
                        mycost, myconv = quantity_cost_and_conv(cost/recipe_quant, myquant, conv)

                        self.set_item_ingredient(myitem, inick, 'cost', mycost)

                        # if this is a recipe update full recipe cost
                        if not (self.costdf.loc[(self.costdf['item'] == 'recipe') 
                                       & (self.costdf['ingredient'] == inick)]).empty:
                            self.costdf.loc[(self.costdf['item'] == 'recipe') 
                                       & (self.costdf['ingredient'] == inick), 'cost'] = cost
                        return mycost
                    
                    # check if quants are equal (above)
                
        else:
            mycost = self.get_simple_ingredient_cost(inick, iquant)
            self.set_item_ingredient(myitem, inick, 'cost', mycost)
            return mycost

    def removeIngredient(self, item, ingredient):
        ''' remove an ingredient from a recipe (item)
        '''
        self.costdf = self.costdf.drop(self.costdf[(self.costdf['item'] == item) & 
                         (self.costdf['ingredient'] == ingredient)].index)
    
    # need to include instance of inick along with parents
    def clear_cost(self, inick):
        ''' clear the calculated cost of a item
            and any items with an affected cost
        '''
        mask = self.costdf['ingredient'].isin([inick] + list(self.get_all_parents(inick, set())))
        self.costdf.loc[mask, 'cost'] = 0
        
    def calculate_cost(self, item_name):
        ''' calculate the cost subitems of a item
        '''
        # menus to calculate cost
        menu_df = self.item_list(item_name)
        # calculate the cost of each menu item
        for i,row in menu_df.iterrows():
            name, quant = row['ingredient'], row['quantity']
            #print (f"Calculating cost of {name}, {quant}...")
            self.item_cost(item_name, name)
        return self.costdf
    
    def recipe_cost(self, rname):
        ''' calculate the cost of a recipe
        '''
        rentry = self.get_recipe_entry(rname)
        if not rentry.empty:
            rentry = rentry.squeeze()
            if (self.use_saved and rentry['saved cost'] >= 0):
                self.set_recipe_entry(rname, 'cost', rentry['saved cost'])
            else:
                self.item_cost('recipe', rentry['ingredient'])
        
    def item_list(self, iname):
        ''' dataframe of children
            return costdf.loc[costdf['item'] == iname.strip()
        '''
        return self.costdf.loc[self.costdf['item'] == iname.strip()]

    def read_from_csv(self, filename):
        '''read menu/recipe list
        '''
        self.costdf = pd.read_csv(filename, sep=',')
        self.costdf['item'] = self.costdf['item'].transform(lambda x: x.strip() if type(x) == str else x)
        self.costdf['ingredient'] = self.costdf['ingredient'].transform(lambda x: x.strip() if type(x) == str else x)
        self.costdf['quantity'] = self.costdf['quantity'].transform(lambda x: x.strip() if type(x) == str else x)

        self.costdf['item'] = pd.Categorical(self.costdf['item'])
        self.costdf['ingredient'] = pd.Categorical(self.costdf['ingredient'])
        
    def read_from_xlsx(self, filepath):
        # read the Excel file into a pandas dataframe
        excel_data = pd.read_excel(
            filepath, sheet_name=None, 
            converters={'date': lambda x: datetime.strptime(x, '%Y-%m-%d') if isinstance(x, str) else x}
            #dtype_backend="pyarrow"
            )

        #excel_data = pd.read_excel(filepath, sheet_name=None)

        # load unified price guide
        if (self.guide_sheet_name in excel_data.keys()):
            self.uni_g = excel_data[self.guide_sheet_name]
        else:
            print('cant find guide sheet')
            return
        
        self.uni_g.columns = self.guide_columns
        # if the first row is just the names of the columns, remove, reset index at 0
        if self.uni_g.iloc[0][self.uni_g.columns[0]] == self.uni_g.columns[0]:
            self.uni_g.columns = list(self.uni_g.iloc[0])
            self.uni_g = self.uni_g.drop(self.uni_g.index[0]).reset_index(drop=True)

        # Parse the dates in the 'date' column
        if ('date' in self.uni_g.columns):
            self.uni_g['date'] = pd.to_datetime(self.uni_g['date'], errors='coerce')
            self.uni_g.loc[self.uni_g['date'].isna(), 'date'] = ('2023-1-1')
            self.uni_g['date'] = self.uni_g['date'].dt.strftime('%Y-%m-%d')
        
        # load menu/recipe list
        self.costdf = excel_data[self.cost_sheet_name]
        
        self.costdf.columns = self.cost_columns
        
        # if the first row is just the names of the columns, remove, reset index at 0
        if self.costdf.iloc[0][self.costdf.columns[0]] == self.costdf.columns[0]:
            self.costdf.columns = list(self.costdf.iloc[0])
            self.costdf = self.costdf.drop(self.costdf.index[0]).reset_index(drop=True)

        #self.costdf.columns = ['item', 'ingredient', 'quantity', 'cost', 'conversion', 'note']
        maybeprint(self.costdf.columns)
        self.costdf['item'] = self.costdf['item'].transform(
            lambda x: x.strip() if type(x) == str else x)
        self.costdf['ingredient'] = self.costdf['ingredient'].transform(
            lambda x: x.strip() if type(x) == str else x)
        self.costdf['quantity'] = self.costdf['quantity'].transform(
            lambda x: x.strip() if type(x) == str else x)
        self.costdf['item'] = pd.Categorical(self.costdf['item'])
        self.costdf['ingredient'] = pd.Categorical(self.costdf['ingredient'])
        
        # rename cost column so it is separate from, (not overwritten by) calculations
        self.costdf = self.costdf.rename(columns={'cost': 'saved cost'})
        self.costdf.loc[:, 'cost'] = 0.0
        

    def write_cc(self, filename):
        ''' Write costdf, uni_g to given excel filename
        '''
        # order costdf by recipe
        recipeset = list(self.costdf.loc[self.costdf['item'] == 'recipe']['ingredient'].unique())
        recipeset.sort()
        orderedcost = pd.DataFrame()
        for rname in recipeset:
            df2 = self.item_list(rname)
            df1 = self.get_recipe_entry(rname)
            orderedcost = pd.concat([orderedcost, df1, df2], ignore_index=True)
        # only save saved cost, remove computed cost
        orderedcost.loc[:,'cost'] = orderedcost.loc[:,'saved cost']
        orderedcost = orderedcost[self.cost_columns]

        ordered_guide = pd.DataFrame()
        
        with pd.ExcelWriter(filename) as writer: 
            self.uni_g.to_excel(writer, sheet_name=self.guide_sheet_name, index=False)
            orderedcost.to_excel(writer, sheet_name=self.cost_sheet_name, index=False)
    
    def ordered_xlsx(self, filename, oldcostsheets=None, cost_multipliers=[3.0, 3.5]):
        ''' create ordered xls from cost dataframe (cdf)
            order: breakfast, lunch, dinner, recipes
        '''
        orderdf = pd.DataFrame()
        myorder = self.get_children('fullmenu')
        # myorder = ['breakfast', 'side menu', 'lunch', 'dinner']
        mycolumns = ['item', 'ingredient', 'quantity', 'cost']
        alpha  = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        row_offset = 3

        # calculate all costs
        self.item_cost('recipe', 'fullmenu')
        
        with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
            menulist = []
            # excel formating
            workbook = writer.book
            curformat = workbook.add_format({"num_format": "$ 0.00"})
            performat = workbook.add_format({"num_format": "0%"})
            
            # create a sheet for each menu in myorder
            for menu in myorder:
                #menulist.append(self.item_list(menu))
                menulist = self.item_list(menu)[mycolumns]
                menu_detail = pd.DataFrame()
                for i,r in menulist.iterrows():
                    myitem = pd.DataFrame([r])
                    recipetop = self.get_recipe_entry(r['ingredient'])
                    mydetail = self.item_list(r['ingredient'])[mycolumns]
                    menu_detail = pd.concat([menu_detail, recipetop, mydetail], ignore_index=True)

                # each sheet is first a top level menu, then a detail of each menu item
                onesheet = pd.concat([menulist, menu_detail], ignore_index=True)

                # if a list of old costs is given, add comparision
                if (type(oldcostsheets) != type(None)):
                    compdf = pd.DataFrame()
                    oldsheet = oldcostsheets[menu]
                    for i,r in onesheet.iterrows():
                        myrow = r.copy()
                        nc_idx = list(myrow.index).index('cost')
                        cell_mult_x = f'${alpha[nc_idx+1]}${row_offset-1}'
                        cell_mult_xx = f'${alpha[nc_idx+2]}${row_offset-1}'
                        myrow['cost x'] = f'=${alpha[nc_idx]}{i+row_offset}*{cell_mult_x}'
                        myrow['cost xx'] = f'=${alpha[nc_idx]}{i+row_offset}*{cell_mult_xx}'
                        oldcost = oldsheet.loc[(oldsheet['ingredient'] == r['ingredient']) & (oldsheet['quantity'] == r['quantity'])]['cost']
                        if (not oldcost.empty):
                            myrow['old cost'] = oldcost.values[0]
                            # myrow['old cost 3.0x'] = oldcost.values[0]*3
                            oc_idx = list(myrow.index).index('old cost')
                            
                            # set xcel equation for cell '= $J4 * $K$2'
                            cell_mult = f'${alpha[oc_idx+1]}${row_offset-1}'
                            myrow['old cost xx'] = f'=${alpha[oc_idx]}{i+row_offset}*{cell_mult_xx}'
                            myrow['change xx'] = f'=${alpha[nc_idx]}{i+row_offset}*{cell_mult_xx}-${alpha[oc_idx+1]}{i+row_offset}'
                        compdf = pd.concat([compdf, pd.DataFrame([myrow])], ignore_index=True)
                    compdf = pd.concat([pd.DataFrame({'cost x':['300%'], 'cost xx':['350%'], 'old cost x':['350%']}), compdf])[compdf.columns]             
                    compdf.to_excel(writer, sheet_name=menu, index=False)
                    worksheet = writer.sheets[menu]
                    itemwidth = 0.8*max(compdf['item'].apply(lambda x: len(str(x))))
                    ingwidth = 0.8*max(compdf['ingredient'].apply(lambda x: len(str(x))))
                    worksheet.set_column(0,0, itemwidth, None)
                    worksheet.set_column(1,1, ingwidth, None)
                    worksheet.set_column(nc_idx, oc_idx+2, None, curformat)
                    worksheet.set_row(1, None, performat)
                else:
                    for mult in cost_multipliers:
                        onesheet = add_costx(onesheet, mult)
                    onesheet.to_excel(writer, sheet_name=menu, index=False)
                    worksheet = writer.sheets[menu]
                    #compdf['ingredient']
                    width1 = max(onesheet['item'].apply(lambda x: len(x)))
                    width2 = max(onesheet['ingredient'].apply(lambda x: len(x)))
                    worksheet.set_column(0,0, width1, None)
                    worksheet.set_column(1,1, width2, None)
                    cost_idx = list(onesheet.columns).index('cost')
                    worksheet.set_column(cost_idx, cost_idx+2, None, curformat)
                
        
            # create a sheet for each recipe
            recipes = self.item_list('recipe').reset_index(drop=True)
            recipe_names = (recipes['ingredient']).sort_values()
            recipe_detail = pd.DataFrame()
            for name in recipe_names:
                cur_recipe = self.item_list(name)
                cur_header = recipes.loc[recipes['ingredient'] == name]
                recipe_detail = pd.concat([recipe_detail, 
                                            cur_header, cur_recipe], ignore_index=True)

            recipe_detail = recipe_detail[mycolumns]
            recipe_detail = add_costx(recipe_detail, 3.0)
            recipe_detail = add_costx(recipe_detail, 3.5)
            recipe_detail.to_excel(writer, sheet_name='recipe', index=False)
            worksheet = writer.sheets['recipe']

            width1 = max(recipe_detail['item'].apply(lambda x: len(x)))
            width2 = max(recipe_detail['ingredient'].apply(lambda x: len(x)))
            worksheet.set_column(0,0, width1, None)
            worksheet.set_column(1,1, width2, None)
            cost_idx = list(recipe_detail.columns).index('cost')
            worksheet.set_column(cost_idx, cost_idx+2, None, curformat)
        
    def ordered_csv(self, filename):
        ''' create ordered csv from cost dataframe (cdf)
            order: breakfast, lunch, dinner, recipes
        '''
        orderdf = pd.DataFrame()
        myorder = ['breakfast', 'side menu', 'lunch', 'dinner']
        menulist = []
        for menu in myorder:
            menulist.append(self.item_list(menu))
        
        orderdf = pd.concat(menulist, ignore_index=True)
        detaildf = pd.DataFrame()
        for i in range(len(orderdf)):
            ihead = orderdf[i:i+1]
            ilist = self.item_list(ihead['ingredient'].array[0])
            detaildf = pd.concat([detaildf, ihead, ilist], ignore_index=True)
            
        orderdf = pd.concat([orderdf, detaildf], ignore_index=True)
            
        recipes = self.item_list('recipe').reset_index(drop=True)
        recipe_names = (recipes['ingredient']).sort_values()
        recipe_detail = pd.DataFrame()
        for name in recipe_names:
            cur_recipe = self.item_list(name)
            cur_header = recipes.loc[recipes['ingredient'] == name]
            recipe_detail = pd.concat([recipe_detail, 
                                        cur_header, cur_recipe], ignore_index=True)
        #for i in range(len(recipes)):
        #    ihead = recipes[i:i+1]
        #    ilist = item_list(ihead['ingredient'].array[0])
        #    recipe_detail = pd.concat([recipe_detail, ihead, ilist], ignore_index=True)
            
        orderdf = pd.concat([orderdf, recipe_detail], ignore_index=True)
            
        orderdf.to_csv(filename)
        
    def add_equ_quant(self, row):
        ''' add equivalent quantity to menu cost item
        '''
        #row = row.copy()
        if self.find_nick(row['ingredient']).empty:
            return row
        cl = self.get_cost_df(row['ingredient'], row['quantity'])
        q = parse_quant(row['quantity'])
        if q.m <= 0:
            return row
        cpq = Q_(cl.iloc[0]['$/quantity'].replace('ct','count'))
        conv = Q_(cl.iloc[0]['myconversion'].replace('ct', 'count'))
        row['equ quant'] = ''
        if type(q) in (int, float):
            return row
        elif q.dimensionality != (1/cpq).dimensionality:
            row['equ quant'] = f"{(q*conv).to_reduced_units().to(1/cpq.units):~.4f}"
        elif q.dimensionality == (1/cpq).dimensionality:
            if q.units != (1/cpq).units:
                row['equ quant'] = f"{q.to((1/cpq).units):~.4f}"
        return row
    
    def findframe(self, ingredient):
        ''' universal method to return the definition(s) of ingredient
        '''
        myselection = pd.DataFrame()
        if ingredient is not None:
            rentry = self.get_recipe_entry(ingredient)
            ilist = self.item_list(ingredient)
            if rentry is not None and not rentry.empty:
                myselection = pd.concat([rentry, ilist], ignore_index=True)
                myselection = myselection.apply(self.add_equ_quant, axis=1)
                myselection = reorder_columns(myselection, self.costdf_order)
                
            else:# look in guide if no results in menu
                # if no matches in guide return empty dataframe
                if self.find_nick(ingredient).empty:
                    return pd.DataFrame()
                myselection = self.cost_picker(self.get_cost_df(ingredient))
                if not myselection.empty:
                    myselection['equ size'] = myselection['size'].apply(lambda x: f"{parse_size(x):~}")
                    myselection = reorder_columns(myselection, self.uni_g_easyorder)
                    
        return myselection
    
    def find_mentions(self, iname):
        ''' find recipes that have iname as an ingredient
        '''
         # find mentions of the search
        mentiondf = pd.DataFrame()
        for p in self.get_parents(iname):
            if p != 'recipe':
                mentiondf = pd.concat([mentiondf, self.findframe(p).loc[self.findframe(p)['ingredient'] == iname]], ignore_index=True)
        
        return mentiondf
    
    def get_children(self, iname):
        ''' get immediate children of iname
        '''
        return list(self.costdf.loc[self.costdf['item'] == iname]['ingredient'])

    def get_all_children(self, iname, all_children):
        ''' get all the children of a node, given inital children all_children
        '''
        children = self.get_children(iname)
        for child in children:
            all_children.add(child)
            self.get_all_children(child, all_children)
        return all_children
    
    def get_parents(self, iname):
        ''' get immediate parents of iname
        '''
        return list(self.costdf.loc[self.costdf['ingredient'] == iname]['item'])
    
    def get_all_parents(self, node, all_parents):
        ''' get all the parents of a node, given inital parents all_parents
        '''
        parents = self.get_parents(node)
        for parent in parents:
            all_parents.add(parent)
            self.get_all_parents(parent, all_parents)
        return all_parents
    
    def is_ingredient(self, ingr):
        ''' is ingr an ingredient, (ingr is a nickname in the price guide)
        '''
        return not self.uni_g.loc[self.uni_g['nickname'] == ingr].empty
    
    def do_conversion(self, item, q1, q2):
        '''
        Try to convert quantity q1 to units of q2 of an item.
        
        Parameters:
        - item: The item for which the conversion is to be done.
        - q1: The quantity to convert from.
        - q2: The target quantity to convert to.
        
        Returns:
        - Converted quantity if a suitable conversion is found.
        - None if no suitable conversion is found.
        '''
        if isinstance(q1, str):
            q1 = parse_quant(q1)
        if isinstance(q2, str):
            q2 = parse_quant(q2)
            
        if q1.dimensionality == q2.dimensionality:
            return q1.to(q2)
        
        results = list(self.find_nick(item)['conversion'].dropna().unique())
        convs = list(parse_unit_conversion(results))
        partialconv = []
        # look for suitable conversion
        for nextconv in convs:
            if isinstance(nextconv, int):
                continue
            for c in nextconv.units._units:
                if q1.dimensionality == ureg(c).dimensionality:
                    # divide/mult by conversion as appropriate
                    result = q1*(nextconv**(-1*nextconv.units._units[c]))
                    if result.dimensionality == q2.dimensionality:
                        return result.to(q2.units)
                    else:
                        partialconv.append(result)
        # check any partial conversion for suitable convs (2nd pass)
        for pc in partialconv:
            for nextconv in convs:
                for c in nextconv.units._units:
                    if pc.dimensionality == ureg(c).dimensionality:
                        newresult = pc*(nextconv**(-1*nextconv.units._units[c]))
                        if newresult.dimensionality == q2.dimensionality:
                            return newresult.to(q2.units)
        return None

    def flatten_recipe(self, item, quant):
        '''
            flatten the recipe for quant of item (all ingredients of the recipe
            are simple ingredients in order guide

            return dataframe with all ingredients and quantities
        '''
        ratio = parse_quant(quant) / parse_quant(self.get_recipe_entry(item)['quantity'].squeeze())
        flatten_df = pd.DataFrame()
        # flatten to simple ingredients
        for i, row in self.item_list(item).iterrows():
            if self.is_ingredient(row['ingredient']) or self.item_list(row['ingredient']).empty:
                row['quantity'] = str(parse_quant(row['quantity']) * ratio.to_reduced_units().m)
                flatten_df = pd.concat([flatten_df, pd.DataFrame([row])], ignore_index=True)
            else:
                ndf = self.flatten_recipe(row['ingredient'], str(parse_quant(row['quantity']) * ratio.to_reduced_units().m))
                flatten_df = pd.concat([flatten_df, ndf], ignore_index=True)
                
        # consolidate repeated ingredient
        reduced_df = pd.DataFrame()
        for ing in flatten_df['ingredient'].unique():
            comb = flatten_df.loc[flatten_df['ingredient'] == ing]
            allquants = comb['quantity'].squeeze()
            #|print(ing)
            if isinstance(allquants, str):
                reduced_df = pd.concat([reduced_df, comb], ignore_index=True)
            else:
                single_df = comb.iloc[0].copy()
                totalquant = 0
                for q in allquants:
                    if totalquant == 0:
                        totalquant = parse_quant(q)
                    else:
                        nextq = parse_quant(q)
                        if totalquant.dimensionality == nextq.dimensionality:
                            totalquant = totalquant + parse_quant(q)
                        else:
                            #print(f'{totalquant} + {nextq}')
                            totalquant = totalquant + self.do_conversion(ing, nextq, totalquant)
                allquants = str(totalquant.to_reduced_units())
                single_df['quantity'] = allquants
                reduced_df = pd.concat([reduced_df, pd.DataFrame([single_df])])
            #print(f"{ing}, {allquants}")
            
        return reduced_df
    
    # find allergens
    def find_allergens(self, item, quant='1 ct'):
        ''' given an item and (quantity) returns a list of all allergens
        '''
        allaller = set()
        if len(ingdf:= self.find_nick(item)) > 0:
            if len(allergen:= ingdf['allergen'].dropna().unique()) > 0:
                for a in allergen:
                    for asub in a.replace(' ', '').split(','):
                        allaller.add(asub)   
        else:
            for ing in self.get_all_children(item, set()):
                if len(self.find_nick(ing)):
                    if len(allergen:= self.find_nick(ing)['allergen'].dropna().unique()) > 0:
                        for a in allergen:
                            for asub in a.replace(' ', '').split(','):
                                allaller.add(asub)

        return allaller
    
        # find allergens
    def findNset_allergens(self, item, quant='1 ct'):
        ''' given an item and (quantity) returns a list of all allergens
        '''
        allaller = set()
        if ('allergen' in self.costdf.columns) and (isinstance(self.costdf.loc[self.costdf['ingredient'] == item][:1]['allergen'].squeeze(), str)):
            allaller = set(self.costdf.loc[self.costdf['ingredient'] == item][:1]['allergen'].squeeze().split(', '))
        else:
            if len(ingdf:= self.find_nick(item)) > 0:
                if len(allergen:= ingdf['allergen'].dropna().unique()) > 0:
                    for a in allergen:
                        for asub in a.replace(' ', '').split(','):
                            allaller.add(asub)   
            else:
                for ing in self.get_all_children(item, set()):
                    if len(self.find_nick(ing)):
                        if len(allergen:= self.find_nick(ing)['allergen'].dropna().unique()) > 0:
                            for a in allergen:
                                for asub in a.replace(' ', '').split(','):
                                    allaller.add(asub)
            self.costdf.loc[self.costdf['ingredient'] == item, 'allergen'] = ", ".join(allaller)
        return allaller
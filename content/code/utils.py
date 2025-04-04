import os
from pint import UnitRegistry

ureg = UnitRegistry()
Q_ = ureg.Quantity

printon = False

def maybeprint(*mymess):
    if (printon == True):
        print(mymess)
        
def parse_quantity(quant):
    quant = quant.replace('ct', 'count')
    try:
        return Q_(quant)
    except:
        return None

def get_xlsx_files():
    return [f for f in os.listdir('.') if f.endswith('.xlsx')]

# Add other utility functions as needed
def find_ratio(iquant, recipe_entry):
    ''' find the ratio of a quantity iquant to a given recipe
        1 tbsp, r_e['quantity'] == 1 cup ----> 0.0625
    '''
    myratio = 1
    myquant = parse_quant(iquant)
    #myquant = Q_(iquant.replace('ct', 'count'))
    recipe_quant = Q_((recipe_entry['quantity']).replace('ct', 'count'))

    # if my quantity and recipe quantity are of same dimensionality
    if (myquant.dimensionality == recipe_quant.dimensionality):
        myratio = (myquant/recipe_quant).to_reduced_units().m
        return myratio
    else:
        if isinstance(recipe_entry['conversion'], str):
            conv = parse_unit_conversion(recipe_entry['conversion'])
            myratio, myconv = quantity_cost_and_conv(
                1/recipe_quant, myquant, conv)
            if (myratio <= 0):
                print(f'no conversion found')
                return 1
            else:
                # We are done! save cost, and return
                return myratio
        else:
            print(f'no conversion found')
            return 1

def get_cost_wconv(myrow, comunit, convers):
    ''' get the cost of a row, in terms of a common unit, comunit
        using the list of conversions convers
    '''
    cost = Q_(0)
    if (str(myrow['unit']).lower()).strip() == 'lb':
        cost = float(myrow['price']) / Q_('1 lb')
    else:
        cost = float(myrow['price']) / parse_size(myrow['size'])
        
    if cost.units != 1/comunit:
        c,q = quantity_cost_and_conv(cost, comunit, parse_unit_conversion(';'.join(convers)))
        
        return c/comunit
    else:
        return cost
def pick_most_recent_cost(df):
    ''' return the entries of 2 most recent dates from the price guide
    '''
    if len(df) > 1:
        # sorted_df = df.sort_values(by='date', ascending=False, ignore_index=True)
        # return sorted_df.loc[0:1,:]
    
        sdf = df.sort_values(by='date', ascending=False, ignore_index=True)
        alldates = list(sdf['date'].unique())
        dates = alldates[0:min(2,len(alldates))]
        return sdf.loc[sdf['date'].isin(dates)]
    else:
        return df
    
def pick_recent_cost(df):
    ''' return the entries of 2 most recent dates from the price guide
    '''
    if len(df) > 1:
        # sorted_df = df.sort_values(by='date', ascending=False, ignore_index=True)
        # return sorted_df.loc[0:1,:]
    
        sdf = df.sort_values(by='date', ascending=False, ignore_index=True)
        alldates = list(sdf['date'].unique())
        dates = alldates[0:min(2,len(alldates))]
        return sdf.loc[sdf['date'].isin(dates)]
    else:
        return df

def pick_max_cost(cdf, count=1):
    ''' sort a cost list df by cost, return row maximum cost,
        optionally return mulitple (count) rows with the largest costs
    '''
    count = int(count)
    sorted_df = cdf.sort_values(by='mycost', ascending=False, ignore_index=True)
    if count >= len(cdf):
        return sorted_df
    else:
        return sorted_df.loc[0:count-1, :]
    

def pick_min_cost(cdf, count=1):
    ''' sort a cost list df by cost, return row minimum cost,
        optionally return mulitple (count) rows with the smallest costs
    '''
    count = int(count)
    sorted_df = cdf.sort_values(by='mycost', ascending=True, ignore_index=True)
    if count >= len(cdf):
        return sorted_df
    else:
        return sorted_df.loc[0:count-1, :]
    

def comp_mag(my_str): 
    ''' compute the the magnitude
        return Q_(my_str).magnitude
    ''' 
    return Q_(my_str).magnitude

def parse_quant(myquant):
    """Parses a quantity string and returns a numeric value.

    Args:
        s (str): The quantity string to parse.

    Returns:
        float: The numeric value of the quantity.
    """
    if isinstance(myquant, str) and len(myquant) > 0:
        q = Q_(myquant.replace('ct', 'count'))
        if q.dimensionless:
            q = q.m*ureg.count
        return q
    elif isinstance(myquant, (int, float)):
        return Q_(f'{myquant} count')
    else:
        return Q_(0)
        
def parse_size(sizestr):
    ''' parse size string in the order guide
    convert to magnitude and units with pint library
    ex: 6/10 oz --> 6*10 oz --> {60} {oz}
    '''
    rmap = (('10/cn', '96 floz'), ('/', '*'), ('#', 'lb'), 
            ('dz', '*12 count'), ('ct', 'count'), ('pk', 'count'), ('doz', '*12 count'), 
            ('gl', 'gal'),('flat', '8 lb'), ('av', '*1'), ('lt','l'))
    if not isinstance(sizestr, str):
        sizestr = '1'
    sizestr = sizestr.lower()
    # if there is an '-' assume we are dealing with a range of values
    # use that average value
    if ('-' in sizestr):
        x,y = sizestr.split('-')
        x = parse_size(x)
        y = parse_size(y)
        return (x.to(y.units) + y)/2
    
    # handle the case of a range of values
    if (sizestr.count('/') == 1) and ('ct' in sizestr):
        x,y = sizestr.split('/')
        x = parse_size(x)
        y = parse_size(y)
        if (x.m < y.m):
            return (x.to(y.units) + y)/2
        
    for r in rmap:
        sizestr = sizestr.replace(*r)
    sizestr = sizestr.replace('**', '*')
    try:
        size = Q_(sizestr.replace('ct', 'count'))
        if size.units == ureg.cs:
            print(f'bad size: {sizestr} {size}')
        return size
    except:
        return Q_('1')

def quantity_cost(cpq, myq, conversion):
    ''' calculate the cost of a given quantity (myq)
        cpq: (cost per quantity from order guide)
        if necessary use conversion to get compatible units
        example conversion: <1 cup>/<120 g>
    '''
    cost = (cpq*myq).to_reduced_units()
    # cost should be dimensionless if compatible units were used
    if not cost.dimensionless:
        # see if conversion or it's reciprical is a valid conversion
        for testconv in conversion:
            if (cost/testconv).dimensionless:
                cost = (cost/testconv).to_reduced_units()
                return cost.m
            elif (cost*testconv).dimensionless:
                cost = (cost*testconv).to_reduced_units()
                return cost.m
        maybeprint(f"can't convert {cpq}, {myq}, {testconv}")
        return 0
    # cost is dimensionless thus we have the cost
    else:
        return cost.m

def quantity_cost_and_conv(cpq, myq, conversion):
    ''' calculate the cost of a given quantity (myq)
        cpq: (cost per quantity from order guide)
        if necessary use conversion to get compatible units
        example conversion: <1 cup>/<120 g>
    '''
        
    cost = (cpq*myq).to_reduced_units()
    # cost should be dimensionless if compatible units were used
    if not cost.dimensionless:
        # see if conversion or it's reciprical is a valid conversion
        for testconv in conversion:
            if (cost/testconv).dimensionless:
                cost = (cost/testconv).to_reduced_units()
                return cost.m, 1/testconv
            elif (cost*testconv).dimensionless:
                cost = (cost*testconv).to_reduced_units()
                return cost.m, testconv
        print(f"can't convert {cpq}, {myq}, {testconv}")
        return 0, 1
    # cost is dimensionless thus we have the cost
    else:
        return cost.m, 1
    
def parse_conversion(conv_str):
    ''' create a conversion factor from a given string conv_str 
        assumed to be in format like: 1 cup per 100 grams
        '1 cup per 100 grams' => <1 cup>/<100 g>
    '''
    conversions = []
    if type(conv_str) == list:
        conv_str = '; '.join(conv_str)
            
    if type(conv_str) == str:
        conv_str = conv_str.replace('ct', 'count')
        for oneconv in conv_str.split(';'):
            if 'per' in oneconv:
                v,m = oneconv.split('per')
                v = Q_(v)
                m = Q_(m)
                conversions.append(v/m)
    return conversions
    
def parse_unit_conversion(conv_str):
    ''' create a conversion factor from a given string conv_str 
        assumed to be in format like: 1 cup per 100 grams
        '1 cup per 100 grams' => <1 cup>/<100 g>
    '''
    if type(conv_str) == list:
        conv_str = '; '.join(conv_str)
            
    if type(conv_str) == str:
        conv_str = conv_str.replace('ct', 'count')
        for oneconv in conv_str.split(';'):
            if 'per' in oneconv:
                v,m = oneconv.split('per')
                v = Q_(v)
                m = Q_(m)
                yield v/m
            else:
                maybeprint(f'!!! no conversion found, {conv_str=}')
                yield 1
    else:
        yield 1
    
        
def reorder_columns(df, columnorder):
    ''' reorder the columns of df by the specified order,
        non specified columns are appended to end
    '''
    #columnorder = ['item', 'ingredient', 'quantity', 'equ quant', 'cost', 'conversion', 'note']
    # Find the columns in the DataFrame that are not in the specified column order
    extra_columns = [col for col in df.columns if col not in columnorder]
    
    # Find the columns in the specified column order that are also in the DataFrame
    existing_columns = [col for col in columnorder if col in df.columns]
    
    # Combine the existing columns in the specified column order with the extra columns
    new_column_order = existing_columns + extra_columns
    
    # Reorder the columns in the DataFrame
    reordered_df = df[new_column_order]
    
    return reordered_df


def format_guide(s2):
    ''' format a row of the price guide, so size is parsed
        a cost column is added as $price/quantity
        use with apply:
        df = df.apply(format_guide, axis=1)
    '''
    s2['cost'] = 20
    if isinstance(s2['size'], str):
        s2['equal size'] = parse_size(s2['size']).format_babel(my_format_babel)
    if (str(s2['unit']).lower()).strip() == 'lb':
        s2['cost'] = f"${s2['price']:.2f} / lb"
    else:
        s2['cost'] = f"${float(s2['price'])/parse_size(s2['size']).m:.2f} / {parse_size(s2['size']).units:~}"
    return s2

def format_recipe(r):
    '''format a row of a recipe list
    '''
    
    #r['cost'] = f"${r['cost']:.2f}"
    return r

def my_format_babel(q, _):
    """Custom formatting function for quantities using the 'babel' format.

    Args:
        q (Quantity): The quantity to format.
        _ : Unused parameter for compatibility.

    Returns:
        str: The formatted quantity string.
    """
    if round(float(q.magnitude), ndigits=4).is_integer():
        return f'{q:.0f~}'
    else:
        return f'{q:.4f~}'
    
def add_costx(xdf, mult):
    """Adds a new cost column to the DataFrame, multiplied by a specified factor.

    Args:
        xdf (pd.DataFrame): The DataFrame to modify.
        mult (float): The multiplication factor for the cost.

    Returns:
        pd.DataFrame: The DataFrame with the new cost column.
    """
    name = f"cost {mult:.1f}x"
    xdf.loc[:, name] = xdf['cost']*mult
    return xdf

def add_netprofit(xdf, mult):
    """ Adds a new cost column to the DataFrame, which is the difference of
        the menu price - target price, (cost * by a specified factor)

    Args:
        xdf (pd.DataFrame): The DataFrame to modify.
        mult (float): The multiplication factor for the cost.

    Returns:
        pd.DataFrame: The DataFrame with the new cost column.
    """
    name = f"difference"
    if xdf['menu price'].notna:
        xdf.loc[:, name] = xdf['menu price'] - xdf['cost']*mult
    return xdf
    
def calculate_weighted_cost(cost_df):
    '''
    Calculate weighted average cost based on the 'order' column.
    Attempts to convert order values to float regardless of their original type.
    If 'order' is not present or conversion fails, uses a weight of 1.
    Allows zero weights (0) in the calculation.
    
    Args:
        cost_df: DataFrame with price and order information
    
    Returns:
        float: The weighted average cost
    '''
    if 'order' not in cost_df.columns:
        # Fall back to simple average if order column doesn't exist
        return cost_df['mycost'].mean()
    
    # Create a new weights column, converting to float where possible
    weights = []
    for val in cost_df['order']:
        try:
            # Try to convert to float regardless of type
            weight = float(val) if val is not None else 1.0
            weights.append(weight)
        except:
            # If conversion fails, use weight of 1
            weights.append(1.0)
    
    # Apply the weights to the mycost values
    weighted_values = [cost * weight for cost, weight in zip(cost_df['mycost'], weights)]
    total_weight = sum(weights)
    
    if total_weight > 0:
        # If we have positive weights, calculate weighted average
        return sum(weighted_values) / total_weight
    else:
        # If all weights are zero, fall back to simple average
        return cost_df['mycost'].mean()
    
ureg.Quantity.format_babel = my_format_babel
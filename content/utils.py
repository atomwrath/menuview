import os
from pint import UnitRegistry

ureg = UnitRegistry()
Q_ = ureg.Quantity

def parse_quantity(quant):
    quant = quant.replace('ct', 'count')
    try:
        return Q_(quant)
    except:
        return None

def get_xlsx_files():
    return [f for f in os.listdir('.') if f.endswith('.xlsx')]

# Add other utility functions as needed

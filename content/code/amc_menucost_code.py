import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display
from costcalulator import CostCalculator
from data_frame_explorer import DataFrameExplorer
    
def main():
    cc = CostCalculator()
    try:
        cc.read_from_xlsx('amc_menu_database.xlsx')
    except FileNotFoundError:
        pass  # Explorer will show the filename in red; user can reload or write
    
    # Create and display the explorer
    explorer = DataFrameExplorer(cc=cc)
    explorer.display()

if __name__ == "__main__":
    main()
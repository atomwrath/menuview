import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display
from costcalulator import CostCalculator
from utils import *
from data_frame_explorer import DataFrameExplorer
from product_fetcher import integrate_fetcher_with_explorer

def main():
    # Initialize the cost calculator with the database
    cc = CostCalculator()
    cc.read_from_xlsx('amc_menu_database.xlsx')
    
    # # Create and display the explorer
    # explorer = DataFrameExplorer(cc=cc)
    # explorer.display()
    
    # Apply the integration
    EnhancedExplorer = integrate_fetcher_with_explorer(DataFrameExplorer)

    # Use the enhanced explorer
    explorer = EnhancedExplorer(cc=cc)
    explorer.display()

if __name__ == "__main__":
    main()
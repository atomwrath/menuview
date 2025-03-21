import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display
from df_functions import *
from data_frame_explorer import DataFrameExplorer

def main():
    # Initialize the cost calculator with the database
    cc = CostCalculator()
    cc.read_from_xlsx('amc_menu_database.xlsx')
    
    # Create and display the explorer
    explorer = DataFrameExplorer(cc=cc)
    explorer.display()

if __name__ == "__main__":
    main()
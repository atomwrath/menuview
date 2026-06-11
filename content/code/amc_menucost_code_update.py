import pandas as pd
import ipywidgets as widgets
import numpy as np
from IPython.display import display
from costcalulator import CostCalculator
from data_frame_explorer import DataFrameExplorer
from order_guide_reader import OrderGuideReader  # Import the new class

def main():
    # Initialize the cost calculator with the database
    cc = CostCalculator()
    try:
        cc.read_from_xlsx('amc_menu_database.xlsx')
    except FileNotFoundError:
        pass  # Explorer will show the filename in red; user can reload or write
    
    # Create the order guide reader with the cost calculator instance
    order_reader = OrderGuideReader(cc=cc)
    
    # Create and display the explorer
    explorer = DataFrameExplorer(cc=cc)
    
    # Create a tab layout to switch between explorer and order guide reader
    tab = widgets.Tab()
    tab.children = [explorer.vbox, order_reader.container]
    tab.set_title(0, 'Menu Explorer')
    tab.set_title(1, 'Order Guide Reader')
    
    # Display the tabbed interface
    display(tab)

if __name__ == "__main__":
    main()
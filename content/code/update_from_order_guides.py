import os
import pandas as pd
import ipywidgets as widgets
from IPython.display import display
from costcalulator import CostCalculator
from order_guide_reader import OrderGuideReader

def main():
    """Run the order guide reader as a standalone tool"""
    # Create orders directory if it doesn't exist
    if not os.path.exists('orders'):
        os.makedirs('orders')
        print("Created 'orders' directory for XLS files")
    
    # Initialize the cost calculator with the database
    cc = CostCalculator()
    
    try:
        # Try to read from the standard database file
        cc.read_from_xlsx('amc_menu_database.xlsx')
        print("Successfully loaded database from amc_menu_database.xlsx")
    except Exception as e:
        print(f"Warning: Could not load database file. {str(e)}")
        print("You can still process order guides, but nickname matching will be limited.")
    
    # Create and display the order guide reader
    reader = OrderGuideReader(cc=cc)
    reader.display()

if __name__ == "__main__":
    main()
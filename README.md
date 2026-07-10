# menuview

**[Open menuview →](https://atomwrath.github.io/menuview/notebooks/index.html?path=menu_view.ipynb)**

A Jupyter-based restaurant cost management application for recipe costing, ingredient price tracking, and order guide processing. Runs entirely in the browser via JupyterLite/Pyodide — no install required. This is just a pre-release demo.

## What it does

- **Recipe costing** — build recipes from ingredients and track their cost as prices change
- **Ingredient price tracking** — maintain a price history per ingredient across suppliers
- **Order guide processing** — import supplier order confirmations to keep prices current
- **Fast, interactive grids** — custom anywidget-based grid views for recipes and order guides, built for large datasets (thousands of rows) without the performance overhead of per-cell widgets

## Running it

The app is deployed via GitHub Pages and runs in-browser using JupyterLite, so the link above is all you need — just click and go.

To run it locally in JupyterLab Desktop instead, clone the repo and open `menu_view.ipynb`.

## Project structure

| File | Purpose |
|---|---|
| `costcalulator.py` | Core cost calculation backend (`CostCalculator`, `FastCostMixin`) |
| `data_frame_widget.py` / `data_frame_explorer.py` | Grid display and UI orchestration |
| `recipe_grid_widget.py` / `guide_grid_widget.py` | Fast anywidget-based grid renderers |
| `order_guide_reader.py` | Supplier order confirmation processing |
| `menuview_theme.py` | Shared UI theme (light/dark) |
| `fast_cost.py`, `utils.py`, `menu_display_widget.py` | Supporting logic and display components |

## Tech stack

Python, pandas, and [anywidget](https://anywidget.dev/) for the frontend widgets, running on both JupyterLab Desktop and JupyterLite (Pyodide/WebAssembly) so the same notebook works locally and as a static, in-browser web app.

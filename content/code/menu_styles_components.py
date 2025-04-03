import ipywidgets as widgets
import pandas as pd
from IPython.display import display

# UI Style Constants
BUTTON_HEIGHT = '33px'
MIN_BUTTON_WIDTH = 120
HIGHLIGHT_COLOR = '#beb153'
BORDER_STYLES = {
    'normal': '2px dotted gray',
    'highlighted': f'2px dotted {HIGHLIGHT_COLOR}'
}

# Standard layouts
LAYOUTS = {
    'button': widgets.Layout(width='auto', height=BUTTON_HEIGHT),
    'header_button': widgets.Layout(width='auto', height=BUTTON_HEIGHT, flex='0 0 auto'),
    'row': widgets.Layout(align_items='flex-start', display='flex', width='100%', 
                          border=BORDER_STYLES['normal']),
    'highlighted_row': widgets.Layout(align_items='flex-start', display='flex', width='100%', 
                                     border=BORDER_STYLES['normal']),
    'ingredient_container': widgets.Layout(flex='1 1 auto', width='70%', overflow='hidden', padding='2px'),
    'header_label': widgets.Layout(height=BUTTON_HEIGHT, flex='0 0 auto'),
    'ingredient_list': widgets.Layout(width='100%', overflow='hidden'),
    'file_selector': widgets.Layout(border='1px solid lightgray', padding='10px', margin='5px'),
    'highlighting_container': widgets.Layout(border=f'1px solid {HIGHLIGHT_COLOR}', 
                                           padding='2px', margin='2px', spacing='1'),
    'output_display': widgets.Layout(overflow='scroll', border='1px solid black', min_height='400px'),
    'top_display': widgets.Layout(border='2px solid green'),
    'allergen_chips': widgets.Layout(display='flex', flex_flow='row wrap', width='100%', padding='10px'),
    'allergen_container': widgets.Layout(margin='0'),
    'ingredient_container_box': widgets.Layout(margin='0'),
    'ingredient_chip': widgets.Layout(border=f'2px solid {HIGHLIGHT_COLOR}', border_radius='15px',
                                   padding='2px 10px', margin='3px', background_color='#e8f4f8'),
    'matching_ingredients': widgets.Layout(display='flex', flex_flow='row wrap', width='100%', margin='5px 0')
}

# Widget styles
WIDGET_STYLES = {
    'standard_font': {'font_size': '13pt'},
    'highlighted_text': {'font_weight': 'bold', 'font_style': 'italic'},
    'warning_text': {'text_color': 'red'},
    'normal_text': {'text_color': 'black'}
}

# HTML Style Templates
HTML_STYLES = {
    'allergen': "text-decoration: underline; font-style: italic;",
    'highlighted_ingredient': f"font-weight: bold; border: 2px solid {HIGHLIGHT_COLOR}; border-radius: 3px; padding: 0 2px;",
    'nowrap': "white-space: nowrap;",
    'heading': "margin-bottom: 5px;",
    'subheading': "margin-bottom: 5px; margin-top: 5px;"
}

# HTML Templates
HTML_TEMPLATES = {
    'title': "<h2>{text}</h2>",
    'heading': "<h3 style='{style}'>{text}</h3>",
    'subheading': "<h4 style='{style}'>{text}</h4>",
    'recipe_title': "<h1 style='font-variant: small-caps;'><b>{text}</b></h1>",
    'highlighted_allergen': "<span style='{style}'>{icon} {text}</span>",
    'normal_allergen': "<span style='{style}'>{icon} {text}</span>",
    'highlighted_ingredient': "<span style='{style}'>{text}</span>",
    'ingredient_list': "INGREDIENTS: {ingredients}"
}

# Allergen icons
allergen_icons = {
    'gluten': '<svg height="16" width="16"><path d="M3,14 V6 C3,6 1.5,5 1.7,3.5 C2,0.5 15,0.5 15,3.5 C15,5.4 13.3,6 13.3,6 V14 Z" fill="#f7efe0" stroke="#784421" stroke-width="1" stroke-linejoin="round"/></svg>',
    'dairy': '<svg height="16" width="16"><path d="M6,2 L10,2 L12,6 L12,14 L4,14 L4,6 Z M4,6 L12,6" fill="#ffffff" stroke="#333" stroke-width="1"/></svg>',
    'egg': '<svg height="16" width="16"><ellipse cx="8" cy="8" rx="6" ry="8" fill="#fffaf0" stroke="#333" stroke-width="1"/><circle cx="8" cy="7" r="4" fill="#f5d742" stroke="none"/></svg>',
    'soy': '<svg height="16" width="16"><path d="M8,2 C10,2 12,4 12,7 C12,10 10,12 8,14 C6,12 4,10 4,7 C4,4 6,2 8,2 Z" fill="#9de24f" stroke="#333" stroke-width="1"/></svg>',
    'fish': '<svg height="16" width="16"><path d="M2,8 C5,4 10,4 13,8 C10,12 5,12 2,8 Z" fill="#a4dbf5" stroke="#333" stroke-width="0.5"/><polygon points="13,8 16,6 16,10" fill="#a4dbf5" stroke="#333" stroke-width="0.5"/></svg>',
    'shellfish': '<svg height="16" width="16"><path d="M2,10 C2,6 6,6 8,8 C10,6 14,6 14,10" fill="none" stroke="#ffb6c1" stroke-width="3" stroke-linecap="round"/></svg>',
    'tree-nut': '<svg height="16" width="16"><polygon points="8,2 14,14 2,14" fill="#8B4513" stroke="#333" stroke-width="1"/></svg>',
    'peanut': '<svg height="16" width="16"><ellipse cx="5" cy="8" rx="4" ry="6" fill="#e6c98a" stroke="#333" stroke-width="1"/><ellipse cx="11" cy="8" rx="4" ry="6" fill="#e6c98a" stroke="#333" stroke-width="1"/></svg>',
    'poultry': '<svg height="16" width="16"><path d="M2,2 L14,2 C8,8 4,10 2,10 Z" fill="#ffcc00" stroke="#1a1a1a" stroke-width="0.5" stroke-linejoin="round"/><path d="M4,10 C3,10 6,12 5,14 C4,16 2,14 2,12 C2,11 2,10 2,10 Z" fill="#ff0000" stroke="#1a1a1a" stroke-width="0.5" stroke-linejoin="round"/></svg>',
    'sesame': '<svg height="16" width="16"><circle cx="8" cy="8" r="7" fill="#f9e076" stroke="#333" stroke-width="1"/><circle cx="8" cy="8" r="3" fill="#e6ca46" stroke="#333" stroke-width="1"/></svg>'
}

# List of common allergens for filtering
my_allergens = ['gluten', 'soy', 'sesame', 'tree-nut', 'peanut', 'dairy', 'egg', 'fish', 'shellfish', 'poultry']

# Component Helper Functions

def create_styled_button(description, on_click=None, tooltip=None, width='auto', style='', styledict='', disabled=False):
    """Create a styled button with consistent layout"""
    button = widgets.Button(
        description=description,
        layout=widgets.Layout(width=width, height=BUTTON_HEIGHT),
        button_style=style,
        tooltip=tooltip or description,
        disabled=disabled
    )
    if styledict:
        button.style = styledict
    if on_click:
        button.on_click(on_click)
    return button

def create_styled_label(value, width='auto', height=BUTTON_HEIGHT, flex='0 0 auto'):
    """Create a styled label with consistent layout"""
    layout = widgets.Layout(width=width, height=height, flex=flex)
    return widgets.Label(value=value, layout=layout)

def create_styled_html(value, width='auto', height=BUTTON_HEIGHT, flex='0 0 auto'):
    """Create a styled HTML widget with consistent layout"""
    layout = widgets.Layout(width=width, height=height, flex=flex)
    return widgets.HTML(value=value, layout=layout)

def create_header_row(columns, max_lengths):
    """Create a header row with standardized styling"""
    header_widgets = []
    
    # Add item column header
    header_widgets.append(create_styled_label(
        " Item ",
        width=f'{max_lengths.get("ingredient", MIN_BUTTON_WIDTH)}px'
    ))
    
    # Add ingredients column header
    header_widgets.append(create_styled_label(
        " Allergen / Ingredients ",
        flex='1 1 auto'
    ))
    
    return widgets.HBox(header_widgets)

def create_allergen_checkbox(allergen):
    """Create an allergen checkbox with icon"""
    icon_html = widgets.HTML(
        value=f"{allergen_icons[allergen]} {allergen.capitalize()}",
        layout=widgets.Layout(width='100px', margin='0 5px')
    )
    
    checkbox = widgets.Checkbox(
        value=False, 
        indent=False,
        layout=widgets.Layout(width='24px', margin='0 5px')
    )
    
    checkbox.description = allergen  # Store allergen name in description attribute
    
    container = widgets.HBox([
        checkbox, 
        icon_html
    ], layout=widgets.Layout(
        margin='0 10px 0 0',
        align_items='center',
    ))
    
    return checkbox, icon_html, container

def create_ingredient_chip(ingredient, on_remove):
    """Create a removable chip for a highlighted ingredient"""
    # Create container
    chip = widgets.HBox(layout=LAYOUTS['ingredient_chip'])
    
    # Create label
    label = widgets.Label(value=ingredient)
    
    # Create remove button
    remove_button = widgets.Button(
        description='×',
        button_style='warning',
        layout=widgets.Layout(width='24px', height='24px', padding='0px')
    )
    
    # Set up remove action
    remove_button.on_click(on_remove)
    
    # Assemble chip
    chip.children = [label, remove_button]
    return chip

def format_allergen_text(allergen_text, selected_allergens):
    """Format allergen text with icons and highlighting"""
    if not allergen_text or not isinstance(allergen_text, str):
        return ""
    
    # Split the allergen text into individual allergens
    allergens = [a.strip().lower() for a in allergen_text.split(',')]
    formatted_parts = []
    
    # Add icon for each allergen if it exists in our icon dictionary
    for allergen in allergens:
        allergen_clean = allergen.lower().strip()
        
        # Check if this allergen should be highlighted
        is_highlighted = allergen_clean in selected_allergens
        
        # Apply appropriate formatting
        if allergen_clean in allergen_icons:
            # Apply bold and italic styling for highlighted allergens
            if is_highlighted:
                formatted_parts.append(HTML_TEMPLATES['highlighted_allergen'].format(
                    style=HTML_STYLES['allergen'] + HTML_STYLES['nowrap'],
                    icon=allergen_icons[allergen_clean],
                    text=allergen.capitalize()
                ))
            else:
                formatted_parts.append(HTML_TEMPLATES['normal_allergen'].format(
                    style=HTML_STYLES['nowrap'],
                    icon=allergen_icons[allergen_clean],
                    text=allergen.capitalize()
                ))
        else:
            if is_highlighted:
                formatted_parts.append(f"<span style='{HTML_STYLES['allergen']}'>{allergen.capitalize()}</span>")
            else:
                formatted_parts.append(allergen.capitalize())
    
    # Join with commas
    return ", ".join(formatted_parts)

def get_highlighted_ingredient_html(ingredient, should_highlight):
    """Return HTML for an ingredient, highlighted if should_highlight is True"""
    if should_highlight:
        return HTML_TEMPLATES['highlighted_ingredient'].format(
            style=HTML_STYLES['highlighted_ingredient'],
            text=ingredient
        )
    return ingredient

def create_matching_ingredient_button(ingredient, is_highlighted, on_click):
    """Create a button for a matching ingredient in the suggestions list"""
    btn = widgets.Button(
        description=ingredient,
        layout=widgets.Layout(
            margin='3px',
            max_width='200px',
            overflow='hidden',
            text_overflow='ellipsis'
        ),
        tooltip=ingredient
    )
    
    # Disable button if ingredient is already highlighted
    if is_highlighted:
        btn.disabled = True
        btn.style.button_color = '#f0f0f0'  # Light gray background
        btn.tooltip = f"{ingredient} (already highlighted)"
    else:
        # Set up click handler
        btn.on_click(on_click)
    
    return btn
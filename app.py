import os
import base64
from copy import deepcopy
import json
import time
import sys
import uuid

import pandas as pd
import numpy as np
import dash
from PIL import Image, ImageFilter
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_html_components as html
import dash_reusable_components as drc
import plotly.graph_objs as go
from flask_caching import Cache


from utils import STORAGE_PLACEHOLDER, GRAPH_PLACEHOLDER
from utils import apply_filters, show_histogram, generate_lasso_mask, apply_enhancements

DEBUG = True

image_string_dict = {}

app = dash.Dash(__name__)
server = app.server

# Caching
CACHE_CONFIG = {
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache-directory',
}

# Custom Script for Heroku
if 'DYNO' in os.environ:
    app.scripts.append_script({
        'external_url': 'https://cdn.rawgit.com/chriddyp/ca0d8f02a1659981a0ea7f013a378bbd/raw/e79f3f789517deec58f41251f7dbb6bee72c44ab/plotly_ga.js'
    })

    # Change caching to redis if hosted on heroku
    CACHE_CONFIG = {
        'CACHE_TYPE': 'redis',
        'CACHE_REDIS_URL': os.environ.get('REDIS_URL', 'localhost:6379'),
    }

cache = Cache()
cache.init_app(app.server, config=CACHE_CONFIG)


def serve_layout():
    session_id = str(uuid.uuid4())

    # Serve placeholder image
    image_string_dict[session_id] = drc.pil_to_b64(Image.open('images/default.jpg'), enc_format='jpeg')

    # App Layout
    return html.Div([
        # Session ID
        html.Div(session_id, id='session-id', style={'display': 'none'}),

        # Banner display
        html.Div([
            html.H2(
                'Dash Image Processing App',
                id='title'
            ),
            html.Img(
                src="https://s3-us-west-1.amazonaws.com/plotly-tutorials/logo/new-branding/dash-logo-by-plotly-stripe-inverted.png"
            )
        ],
            className="banner"
        ),

        # Body
        html.Div(className="container", children=[
            html.Div(className='row', children=[
                html.Div(className='five columns', children=[
                    drc.Card([
                        dcc.Upload(
                            id='upload-image',
                            children=[
                                'Drag and Drop or ',
                                html.A('Select an Image')
                            ],
                            style={
                                'width': '100%',
                                'height': '50px',
                                'lineHeight': '50px',
                                'borderWidth': '1px',
                                'borderStyle': 'dashed',
                                'borderRadius': '5px',
                                'textAlign': 'center'
                            },
                            accept='image/*'
                        ),

                        drc.NamedInlineRadioItems(
                            name='Selection Mode',
                            short='selection-mode',
                            options=[
                                {'label': ' Rectangular', 'value': 'select'},
                                {'label': ' Lasso', 'value': 'lasso'}
                            ],
                            val='select'
                        ),

                        drc.NamedInlineRadioItems(
                            name='Image Display Format',
                            short='encoding-format',
                            options=[
                                {'label': ' JPEG', 'value': 'jpeg'},
                                {'label': ' PNG', 'value': 'png'}
                            ],
                            val='jpeg'
                        ),
                    ]),

                    drc.Card([
                        dcc.Dropdown(
                            id='dropdown-filters',
                            options=[
                                {'label': 'Blur', 'value': 'blur'},
                                {'label': 'Contour', 'value': 'contour'},
                                {'label': 'Detail', 'value': 'detail'},
                                {'label': 'Enhance Edge', 'value': 'edge_enhance'},
                                {'label': 'Enhance Edge (More)', 'value': 'edge_enhance_more'},
                                {'label': 'Emboss', 'value': 'emboss'},
                                {'label': 'Find Edges', 'value': 'find_edges'},
                                {'label': 'Sharpen', 'value': 'sharpen'},
                                {'label': 'Smooth', 'value': 'smooth'},
                                {'label': 'Smooth (More)', 'value': 'smooth_more'}
                            ],
                            searchable=False,
                            placeholder='Basic Filter...'
                        ),

                        dcc.Dropdown(
                            id='dropdown-enhance',
                            options=[
                                {'label': 'Brightness', 'value': 'brightness'},
                                {'label': 'Color Balance', 'value': 'color'},
                                {'label': 'Contrast', 'value': 'contrast'},
                                {'label': 'Sharpness', 'value': 'sharpness'}
                            ],
                            searchable=False,
                            placeholder='Enhance...'
                        ),

                        html.Div(
                            id='div-enhancement-factor',
                            style={
                                'display': 'none',
                                'margin': '25px 5px 30px 0px'
                            },
                            children=[
                                f"Enhancement Factor:",
                                html.Div(
                                    style={'margin-left': '5px'},
                                    children=dcc.Slider(
                                        id='slider-enhancement-factor',
                                        min=0,
                                        max=2,
                                        step=0.1,
                                        value=1,
                                        updatemode='drag'
                                    )
                                )
                            ]
                        ),

                        html.Button('Run Operation', id='button-run-operation')
                    ]),

                    dcc.Graph(id='graph-histogram-colors', config={'displayModeBar': False})
                ]),

                html.Div(className='seven columns', style={'float': 'right'}, children=[
                    # The Interactive Image Div contains the dcc Graph showing the image, as well as the hidden div
                    # storing the true image
                    html.Div(id='div-interactive-image', children=[
                        GRAPH_PLACEHOLDER,
                        html.Div(
                            id='div-storage',
                            children=STORAGE_PLACEHOLDER,
                            style={'display': 'none'}
                        )
                    ])
                ])
            ])
        ])
    ])


app.layout = serve_layout


def add_action_to_stack(action_stack, operation, type, selectedData):
    """Add in-place new action to the action stack"""
    new_action = {
        'operation': operation,
        'type': type,
        'selectedData': selectedData
    }

    action_stack.append(new_action)


# Recursively retrieve the previous versions of the image by popping the action stack
@cache.memoize()
def apply_actions_on_image(session_id, action_stack, filename, image_signature):
    action_stack = deepcopy(action_stack)

    if len(action_stack) == 0:
        string = image_string_dict[session_id]
        im_pil = drc.b64_to_pil(string)
        return im_pil

    # Pop out the last action
    last_action = action_stack.pop()
    # Apply all the previous action_stack, and gets the image PIL
    im_pil = apply_actions_on_image(session_id, action_stack, filename, image_signature)
    im_size = im_pil.size

    # Apply the rest of the action_stack
    operation = last_action['operation']
    selectedData = last_action['selectedData']
    type = last_action['type']

    # Select using Lasso
    if selectedData and 'lassoPoints' in selectedData:
        selection_mode = 'lasso'
        selection_zone = generate_lasso_mask(im_pil, selectedData)
    # Select using rectangular box
    elif selectedData and 'range' in selectedData:
        selection_mode = 'select'
        lower, upper = map(int, selectedData['range']['y'])
        left, right = map(int, selectedData['range']['x'])
        # Adjust height difference
        height = im_size[1]
        upper = height - upper
        lower = height - lower
        selection_zone = (left, upper, right, lower)
    # Select the whole image
    else:
        selection_mode = 'select'
        selection_zone = (0, 0) + im_size

    # Apply the filters
    if type == 'filter':
        apply_filters(
            image=im_pil,
            zone=selection_zone,
            filter=operation,
            mode=selection_mode
        )
    elif type == 'enhance':
        enhancement = operation['enhancement']
        factor = operation['enhancement_factor']

        apply_enhancements(
            image=im_pil,
            zone=selection_zone,
            enhancement=enhancement,
            enhancement_factor=factor,
            mode=selection_mode
        )

    return im_pil


# Update Callbacks
@app.callback(Output('interactive-image', 'figure'),
              [Input('radio-selection-mode', 'value')],
              [State('interactive-image', 'figure')])
def update_selection_mode(selection_mode, figure):
    if figure:
        figure['layout']['dragmode'] = selection_mode
    return figure


@app.callback(Output('graph-histogram-colors', 'figure'),
              [Input('interactive-image', 'figure')])
def update_histogram(figure):
    # Retrieve the image stored inside the figure
    enc_str = figure['layout']['images'][0]['source'].split(';base64,')[-1]
    # Creates the PIL Image object from the b64 png encoding
    im_pil = drc.b64_to_pil(string=enc_str)

    return show_histogram(im_pil)


@app.callback(Output('div-interactive-image', 'children'),
              [Input('upload-image', 'contents'),
               Input('button-run-operation', 'n_clicks')],
              [State('interactive-image', 'selectedData'),
               State('dropdown-filters', 'value'),
               State('dropdown-enhance', 'value'),
               State('slider-enhancement-factor', 'value'),
               State('upload-image', 'filename'),
               State('radio-selection-mode', 'value'),
               State('radio-encoding-format', 'value'),
               State('div-storage', 'children'),
               State('session-id', 'children')])
def update_graph_interactive_image(content,
                                   n_clicks,
                                   selectedData,
                                   filters,
                                   enhance,
                                   enhancement_factor,
                                   new_filename,
                                   dragmode,
                                   enc_format,
                                   storage,
                                   session_id):
    t_start = time.time()

    # Retrieve the name of the file stored and the action stack
    # Filename is the name of the image file
    # Path is the path in which the image file is stored
    # Action stack is the list of actions that are applied on the image to get the final result. Each action is the
    # dictionary of a given operation, the input parameter needed for that operation, and the zone selected by the
    # user.

    filename, image_signature, action_stack = storage
    action_stack = json.loads(action_stack)

    # If the file has changed (when a file is uploaded)
    if new_filename and new_filename != filename:
        # Replace filename
        if DEBUG:
            print(filename, "replaced by", new_filename)
        filename = new_filename

        # Parse the string and convert to pil
        string = content.split(';base64,')[-1]
        im_pil = drc.b64_to_pil(string)

        # Update the image signature, which is the first 200 b64 values of the string encoding
        image_signature = string[:200]

        # Add the new string to the dictionary containing all server's image strings
        image_string_dict[session_id] = string

        # Resets the action stack
        action_stack = []

    # If the file HAS NOT changed (which means an operation was applied)
    else:
        # Add actions to the action stack (we have more than one if filters and enhance are BOTH selected)
        if filters:
            type = 'filter'
            operation = filters
            add_action_to_stack(action_stack, operation, type, selectedData)

        if enhance:
            type = 'enhance'
            operation = {'enhancement': enhance, 'enhancement_factor': enhancement_factor}
            add_action_to_stack(action_stack, operation, type, selectedData)

        # Use the memoized function to apply the required actions to the picture
        im_pil = apply_actions_on_image(session_id, action_stack, filename, image_signature)

    t_end = time.time()
    if DEBUG:
        print(f"Updated Image Storage in {t_end - t_start:.3f} sec")

    return [
        drc.InteractiveImagePIL(
            image_id='interactive-image',
            image=im_pil,
            enc_format=enc_format,
            display_mode='fixed',
            dragmode=dragmode,
            verbose=DEBUG
        ),

        html.Div(
            id='div-storage',
            children=[filename, image_signature, json.dumps(action_stack)],
            style={'display': 'none'}
        )
    ]


# Show/Hide Callbacks
@app.callback(Output('div-enhancement-factor', 'style'),
              [Input('dropdown-enhance', 'value')],
              [State('div-enhancement-factor', 'style')])
def show_slider_enhancement_factor(value, style):
    # If any enhancement is selected
    if value:
        style['display'] = 'block'
    else:
        style['display'] = 'none'

    return style


# Reset Callbacks
@app.callback(Output('dropdown-filters', 'value'),
              [Input('button-run-operation', 'n_clicks')])
def reset_dropdown_filters(_):
    return None


@app.callback(Output('dropdown-enhance', 'value'),
              [Input('button-run-operation', 'n_clicks')])
def reset_dropdown_enhance(_):
    return None


external_css = [
    "https://cdnjs.cloudflare.com/ajax/libs/normalize/7.0.0/normalize.min.css",  # Normalize the CSS
    "https://fonts.googleapis.com/css?family=Open+Sans|Roboto"  # Fonts
    "https://maxcdn.bootstrapcdn.com/font-awesome/4.7.0/css/font-awesome.min.css",
    "https://cdn.rawgit.com/xhlulu/0acba79000a3fd1e6f552ed82edb8a64/raw/dash_template.css",  # For production,
    "https://cdn.rawgit.com/xhlulu/dash-image-processing/1d2ec55e/custom_styles.css"  # Custom CSS
]

for css in external_css:
    app.css.append_css({"external_url": css})

# Running the server
if __name__ == '__main__':
    app.run_server(debug=True)


"""
Main file

To compile the resources, run:
$ pyside-rcc resource -o resource.py
from inside pkview/resources
"""

from pkview import pkviewer

# required to use resources in theme
from pkview.resources import resource

pkviewer.main()


"""
Quantiphyse - Package for data registration and motion correction

Copyright (c) 2013-2018 University of Oxford
"""
from .widget import RegWidget, ApplyTransform
from .process import RegProcess, ApplyTransformProcess
from .reg_method import RegMethod

QP_MANIFEST = {
    "widgets" : [RegWidget, ApplyTransform],
    "processes" : [RegProcess, ApplyTransformProcess],
    "base-classes" : [RegMethod,],
}

"""
Quantiphyse - Self-test framework

Copyright (c) 2013-2018 University of Oxford
"""

import unittest
import math

import numpy as np
import scipy

from quantiphyse.data import DataGrid
from quantiphyse.utils import get_plugins

from .widget_test import WidgetTest
from .process_test import ProcessTest
from .slice_plane_test import OrthoSliceTest
from .ivm_test import IVMTest
from .qpd_test import NumpyDataTest

__all__ = ["WidgetTest", "ProcessTest", "run_tests", "create_test_data"]

class_tests = [IVMTest, NumpyDataTest, OrthoSliceTest,]

def run_tests(test_filter=None):
    """
    Run all unit tests defined by packages and plugins

    :param test_filter: Specifies name of test set to be run, None=run all
    """
    suite = unittest.TestSuite()

    for test in class_tests:
        if test_filter is None or test.__name__.lower().startswith(test_filter.lower()):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test))

    tests = get_plugins("widget-tests")
    for test in tests:
        if test_filter is None or test.__name__.lower().startswith(test_filter.lower()):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test))
   
    tests = get_plugins("process-tests")
    for test in tests:
        if test_filter is None or test.__name__.lower().startswith(test_filter.lower()):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test))
   
    unittest.TextTestRunner(verbosity=2).run(suite)

def _test_fn(x, y, z, t=None):
    f = math.exp(-(x**2 + 2*y**2 + 3*z**2))
    if t is not None:
        f *= 1-math.cos(t*2*math.pi)
    return f

def create_test_data(obj, shape=[10, 10, 10], nt=20, motion_scale=0.5):
    """
    Create test data

    Creates the following attributes on obj, each a Numpy array

     - grid
     - data_3d
     - data_4d
     - data_4d_moving
     - mask
    """
    centre = [float(v)/2 for v in shape]

    obj.grid = DataGrid(shape, np.identity(4))
    obj.data_3d = np.zeros(shape, dtype=np.float32)
    obj.data_4d = np.zeros(shape + [nt,], dtype=np.float32)
    obj.data_4d_moving = np.zeros(shape + [nt,], dtype=np.float32)
    obj.mask = np.zeros(shape, dtype=np.int)

    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                nx = 2*float(x-centre[0])/shape[0]
                ny = 2*float(y-centre[1])/shape[1]
                nz = 2*float(z-centre[2])/shape[2]
                d = math.sqrt(nx**2 + ny**2 + nz**2)
                obj.data_3d[x, y, z] = _test_fn(nx, ny, nz)
                obj.mask[x, y, z] = int(d < 0.5)
                for t in range(nt):
                    ft = float(t)/nt
                    obj.data_4d[x, y, z, t] = _test_fn(nx, ny, nz, ft)
    
    for t in range(nt):
        tdata = obj.data_4d[:, :, :, t]
        shift = np.random.normal(scale=motion_scale, size=3)
        odata = scipy.ndimage.interpolation.shift(tdata, shift)
        obj.data_4d_moving[:, :, :, t] = odata

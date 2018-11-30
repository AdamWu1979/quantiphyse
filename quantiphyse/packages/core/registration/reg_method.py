"""
Quantiphyse - Base class for a registration method

Copyright (c) 2013-2018 University of Oxford
"""
from PySide import QtGui

import numpy as np

from quantiphyse.data import NumpyData
from quantiphyse.utils import LogSource, QpException

class RegMethod(LogSource):
    """
    A registration method

    Methods should implement, at a minimum, the ``reg`` method
    Methods which take options should implement ``interface`` and ``options``
    Methods may implement ``moco`` if motion correction is handled differently
    """
    def __init__(self, name, display_name=None):
        LogSource.__init__(self)
        self.name = name
        if display_name is not None:
            self.display_name = display_name
        else:
            self.display_name = name

    @classmethod
    def apply_transform(cls, reg_data, transform, options, queue):
        """
        Apply a previously calculated transformation to a data set

        :param reg_data: QpData containing data to apply the transform to.
        :param transform: A transformation object as returned by one of the registration methods.
                          This must be compatible with the registration class (i.e.
                          typically generated by the same registration class)
        :param options: Method options as dictionary
        :param queue: Queue object which method may put progress information on to. Progress 
                      should be given as a number between 0 and 1.
        :return Tuple of QpData containing transformed data and log output as a string
        """
        raise NotImplementedError("Registration method has not implemented 'apply_transform'")

    @classmethod
    def reg_3d(cls, reg_data, ref_data, options, queue):
        """
        3D Registration

        :param reg_data: 3D QpData containing data to register.
        :param ref_data: 3D QpData containing reference data.
        :param options: Method options as dictionary
        :param queue: Queue object which method may put progress information on to. Progress 
                      should be given as a number between 0 and 1.

        :return Tuple of three items. 
        
                First, A QpData containing registered data

                Second, if options contains ``output-transform : True``, transformation found. 
                This is either a QpData containing warp images (typically 3) or an Extra
                containing a matrix transformation. If ``output-transform`` is not given, or
                is not supported, returns None instead.

                Third, log information from the registration as a string.
        """
        raise NotImplementedError("Registration method has not implemented 'reg'")

    @classmethod
    def reg_4d(cls, reg_data, ref_data, options, queue):
        """
        4D Registration

        The default implementation simply registers each volume of the data independently. However,
        implementations can supply their own more optimal implementation if appropriate

        :param reg_data: 4D QpData containing data to register.
        :param ref_data: 3D QpData containing reference data.
        :param options: Method options as dictionary
        :param queue: Queue object which method may put progress information on to. Progress 
                      should be given as a number between 0 and 1.

        :return Tuple of three items. 
        
                First, A QpData containing registered data

                Second, if options contains ``output-transform : True``, sequence of transformations
                found, one for each volume in ``reg_data``. Each is either a QpData object containing 
                a sequence of 3 warp images or an Extra object containing a transformation matrix
                If ``output-transform`` is not given or not supported, returns None instead.

                Third, log information from the registration as a string.
        """
        if reg_data.ndim != 4:
            raise QpException("reg_4d expected 4D data")
        
        if options.get("output-space", "ref") == "ref":
            output_space = ref_data
        else:
            output_space = reg_data
        out_data = np.zeros(list(output_space.grid.shape) + [reg_data.nvols])

        transforms = []
        log = "Default 4D registration using multiple 3d registrations\n"
        for vol in range(reg_data.shape[-1]):
            log += "Registering volume %i of %i\n" % (vol+1, reg_data.shape[-1])
            reg_vol = NumpyData(reg_data.volume(vol), grid=reg_data.grid, name="regvol")
            #self.debug("Vol %i of %i" % (vol+1, reg_data.shape[-1]))
            if vol == options.get("ignore-idx", -1):
                # Ignore this index (e.g. because it is the same as the ref volume)
                if options.get("output-space", "ref") != "reg":
                    raise QpException("Can't ignore an index unless the output space is the registration data")
                out_data[..., vol] = reg_vol.raw()
                transforms.append(None)
            else:
                #self.debug("Calling reg_3d", cls, cls.reg_3d)
                # We did not remove output-space from the options so regdata should
                # come back in the appropriate space
                regdata, transform, vol_log = cls.reg_3d(reg_vol, ref_data, options, queue)
                out_data[..., vol] = regdata.raw()
                transforms.append(transform)
                log += vol_log
            queue.put(float(vol)/reg_data.shape[-1])

        # If we are not saving transforms, the list will just be a list of None objects
        if not options.get("save-transforms", False):
            transforms = None

        return out_data, transforms, log

    @classmethod
    def moco(cls, moco_data, ref, options, queue):
        """
        Motion correction
        
        The default implementation uses the ``reg_4d`` function to perform motion correction
        as registration to a common reference, however this function can have a custom
        implementation specific to motion correction if required.
        
        :param moco_data: A single 4D QpData containing data to motion correct.
        :param ref: Either 3D QpData containing reference data, or integer giving 
                    the volume index of ``moco_data`` to use
        :param options: Method options as dictionary
        :param queue: Queue object which method may put progress information on to. Progress 
                      should be given as a number between 0 and 1.
        
        :return Tuple of three items. 
        
                First, motion corrected QpData in the same space as ``moco_data``
        
                Second, if options contains ``output-transform : True``, sequence of transformations
                found, one for each volume in ``reg_data``. Each is either a QpData object containing 
                a sequence of 3 warp images or an Extra object containing a transformation matrix
                If ``output-transform`` is not given or not supported, returns None instead.

                Third, log information from the registration as a string.
        """
        if moco_data.ndim != 4:
            raise QpException("Cannot motion correct 3D data")
        
        log = "Default MOCO implementation using multiple 3d registrations\n"
        if isinstance(ref, int):
            if ref >= moco_data.nvols:
                raise QpException("Reference volume index of %i, but data has only %i volumes" % (ref, moco_data.nvols))
            ref = moco_data.volume(ref)

        options["output-space"] = "reg"
        out_data, transforms, moco_log = cls.reg_4d(moco_data, ref, options, queue)
        log += moco_log
        return out_data, transforms, log

    def interface(self):
        """
        Return a QtGui.QWidget() to allow options to be controlled
        """
        return QtGui.QWidget()
        
    def options(self):
        """
        :return: Dictionary of options currently selected
        """ 
        return {}

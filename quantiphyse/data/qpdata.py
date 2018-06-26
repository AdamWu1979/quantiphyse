"""
Quantiphyse - Basic volume data classes

Concepts:

 - All data is 3D or 4D. 2D (or 1D?) data must be expanded to 3D on load. There is provision
   for 3D data to be 'interpreted' as 2D multi-volume data (there are broken Nifti files
   around like this)
 - All data is defined on a ``DataGrid`` which consists of the data shape and an affine transform
   from grid co-ordinate space to world space.
 - The 4th dimension (multiple volumes) is not part of the grid and has no impact on orientation.
 - Data objects support arbitrary slicing in a plane defined by an normal axis and a position
   relative to another grid. The output of this slice is an array, a mask (zero where outside range
   of data, plus a 2D affine transformation to map the data onto the slice grid)
 - Data objects also support resampling onto a grid, as required for some analysis methods

Copyright (c) 2013-2018 University of Oxford
"""

import logging
import math

import numpy as np
import scipy

from quantiphyse.utils import sf, QpException

# Private copy of pyqtgraph functions for bug fixes
from . import functions as pg

#: Tolerance for treating values as equal
#: Used to determine if matrices are diagonal or identity
EQ_TOL = 1e-3

LOG = logging.getLogger(__name__)

def is_diagonal(mat):
    """
    :return: True if mat is diagonal, to within a tolerance of ``EQ_TOL``
    """
    return np.all(np.abs(mat - np.diag(np.diag(mat))) < EQ_TOL)

def is_identity(mat):
    """
    :return: True if mat is the identity matrix, to within a tolerance of ``EQ_TOL``
    """
    return np.all(np.abs(mat - np.identity(mat.shape[0])) < EQ_TOL)

def is_ortho_vector(vec, shape=1):
    """
    Determine if a vector has a component in only one direction

    :return: Tuple of axis, sign if vector is ortho, None, None otherwise
    """
    tol = EQ_TOL / shape
    mod = np.linalg.norm(vec)
    for axis, val in enumerate(vec):
        if abs(abs(val/mod)-1) < tol:
            return axis, math.copysign(1, val)
    return None, None

class DataGrid(object):
    """
    Defines a regular 3D grid in some 'world' space

    :ivar affine: 4D affine matrix which describes the transformation from
                  grid co-ordinates to standard space co-ordinates
    :ivar origin: 3D origin of grid in world co-ordinates (last column of ``affine``)
    :ivar transform: 3x3 submatrix of ``affine`` used to transform directions to world space
    :ivar spacing: Sequence of length 3 giving spacing between voxels in world units
    :ivar nvoxels: Number of voxels in the grid

    A DataGrid is not formally immutable but are not designed to be modified
    """

    def __init__(self, shape, affine):
        """
        Create a DataGrid object

        :param shape: Sequence of 3 integers giving number of voxels along each axis
        :param affine: 4x4 affine transformation to world co-ordinates
        """
        # Dimensionality of the grid - 3D only
        if len(shape) != 3:
            raise RuntimeError("Grid shape must be 3D")
        self.shape = list(shape)[:]

        # 3D Affine transformation from grid-space to standard space
        # This is a 4x4 matrix - includes constant offset (origin)
        if len(affine.shape) != 2 or affine.shape[0] != 4 or affine.shape[1] != 4:
            raise RuntimeError("Grid affine must be 4x4 matrix")

        self.affine = np.copy(affine)
        self.origin = tuple(affine[:3, 3])
        self.transform = affine[:3, :3]
        self.inv_transform = np.linalg.inv(self.transform)

        self.spacing = [np.linalg.norm(self.affine[:, i]) for i in range(3)]
        self.nvoxels = 1
        for dim in range(3):
            self.nvoxels *= shape[dim]

    def grid_to_grid(self, coord, from_grid=None, to_grid=None, direction=False):
        """
        Transform grid co-ordinates to another grid's co-ordinates

        :param coords: 3D or 4D grid co-ordinates. If 4D, last entry is returned unchanged
        :param from_grid: DataGrid the input co-ordinates are relative to. They will be returned
                     relative to this grid
        :param to_grid: DataGrid the input co-ordinates are to be transformed into. The input
                   co-ordinates are assumed to be relative to this grid
        :return: List containing 3D or 4D co-ordinates
        """
        if from_grid is not None and to_grid is None:
            to_grid = self
        elif from_grid is None and to_grid is not None:
            from_grid = self
        else:
            raise RuntimeError("Exactly one of from_grid and to_grid must be specified")

        world = from_grid.grid_to_world(coord, direction=direction)
        return to_grid.world_to_grid(world, direction=direction)

    def grid_to_world(self, coords, direction=False):
        """
        Transform grid co-ordinates to world co-ordinates

        :param coords: 3D or 4D grid co-ordinates. If 4D, last entry is returned unchanged
        :return: List containing 3D or 4D world co-ordinates
        """
        vec = np.array(coords[:3])
        world_coords = np.dot(self.transform, vec)
        if not direction:
            world_coords += np.array(self.origin, dtype=world_coords.dtype)

        if len(coords) == 4:
            return list(world_coords) + [coords[3]]
        else:
            return list(world_coords)

    def world_to_grid(self, coords, direction=False):
        """
        Transform world co-ordinates to grid co-ordinates

        :param coords: 3D world co-ordinates. If 4D, last entry is returned unchanged
        :return: List containing 3D or 4D grid co-ordinates
        """
        vec = np.array(coords[:3])
        if not direction:
            vec -= np.array(self.origin, dtype=vec.dtype)
        grid_coords = np.dot(self.inv_transform, vec)

        if len(coords) == 4:
            return list(grid_coords) + [coords[3]]
        else:
            return list(grid_coords)

    def get_standard(self):
        """
        Return a new grid in approximate RAS order, by axis transposition
        and flipping only

        The result is a grid which defines the same space as the original
        with the same voxel spacing but where the x axis is increasing
        left->right, the y axis increases posterior->anterior and the
        z axis increases inferior->superior.
        """
        reorder, _, tmatrix = self.simplify_transforms(self.affine)
        new_shape = [self.shape[d] for d in reorder]
        return DataGrid(new_shape, tmatrix)

    def get_ras_axes(self):
        """
        Get the grid axes which best correspond to the RAS axes

        :return: List of four integers giving the axes indices of the R, A and S axes.
                 The fourth integer is always 3 indicating the volume axis
        """
        world_axes = [np.argmax(np.abs(self.transform[:, axis])) for axis in range(3)]
        grid_axes = [world_axes.index(axis) for axis in range(3)]
        return grid_axes + [3, ]

    def matches(self, grid):
        """
        Determine if another grid matches this one

        :param grid: DataGrid instance
        :return: True if ``grid`` is identical to this grid
        """
        return np.array_equal(self.affine, grid.affine) and  np.array_equal(self.shape, grid.shape)

    def simplify_transforms(self, mat):
        """
        Convert the transformation into optional re-ordering and flipping
        of axes and a final optional affine transformation
        This enables us to use faster methods in the case where the
        grids are essentially the same or scaled
        """
        # Flip/transpose the axes to put the biggest numbers on
        # the diagonal and make negative diagonal elements positive
        dim_order, dim_flip = [], []

        absmat = np.absolute(mat)
        for dim in range(3):
            newd = np.argmax(absmat[:, dim])
            dim_order.append(newd)
            if mat[newd, dim] < 0:
                dim_flip.append(newd)

        new_mat = np.copy(mat)
        if sorted(dim_order) == range(3):
            # The transposition was consistent, so use it
            LOG.debug("Before simplification")
            LOG.debug(new_mat)
            new_shape = [self.shape[d] for d in dim_order]
            for idx, dim in enumerate(dim_order):
                new_mat[:, dim] = mat[:, idx]
            LOG.debug("After transpose %s", dim_order)
            LOG.debug(new_mat)
            for dim in dim_flip:
                # Change signs to positive to flip a dimension
                new_mat[:, dim] = -new_mat[:, dim]
            LOG.debug("After flip %s", dim_flip)
            LOG.debug(new_mat)
            for dim in dim_flip:
                # Adjust origin
                new_mat[:3, 3] = new_mat[:3, 3] - new_mat[:3, dim] * (new_shape[dim]-1)

            LOG.debug("After adjust origin %s", new_shape)
            LOG.debug(new_mat)

            return dim_order, dim_flip, new_mat
        else:
            # Transposition was inconsistent, just go with general
            # affine transform - this will work but might be slow
            return range(3), [], new_mat

class OrthoSlice(DataGrid):
    """
    DataGrid defined as a 2D orthogonal slice through another grid

    Has same attributes as :class:`DataGrid`, in addition:

    :ivar basis: Sequence of two 3D basis vectors for the plane in world co-ordinates
    :ivar normal: 3D normal vector to the plane in world co-ordinates
    """

    def __init__(self, grid, zaxis, pos):
        """
        Create an OrthoSlice by taking a slice through an existing grid

        :param grid: DataGrid instance
        :param zaxis: Which axis is the normal axis for the slice (0, 1 or 2)
        :param pos: Position along ``axis`` to take the slice, in grid co-ordinates
        """
        affine = np.zeros((4, 4))
        shape = [1, 1, 1]
        col = 0
        for axis in range(3):
            if axis != zaxis:
                affine[:, col] = grid.affine[:, axis]
                shape[col] = grid.shape[axis]
                col += 1
            else:
                affine[:, 2] = grid.affine[:, axis]
        affine[:, 3] = grid.affine[:, 3] + pos * affine[:, 2]
        DataGrid.__init__(self, shape, affine)
        self.basis = [tuple(self.transform[:, 0]), tuple(self.transform[:, 1])]
        self.normal = tuple(self.transform[:, 2])

class QpData(object):
    """
    3D or 4D data

    Data is defined on a DataGrid instance which defines a uniform grid in standard space.

    :ivar name: Identifying name for the data the :class:`ImageVolumeManagement` class will
                require this to be a valid and Python variable name and unique within the IVM.
    :ivar grid: :class:`DataGrid` instance the data is defined on
    :ivar nvols: Number of volumes (1=3D data)
    :ivar ndim: 3 or 4 for 3D or 4D data
    :ivar fname: File name data came from if relevant
    :ivar dps: Number of decimal places to display data to
    :ivar raw_2dt: Whether raw data is 3D but being interpreted as 2D multi-volume
    :ivar range: Data range tuple (min, max)
    :ivar roi: True if this data represents a region of interest
    """

    def __init__(self, name, grid, nvols, fname=None, metadata=None, roi=False):
        # Everyone needs a friendly name
        self.name = name

        # Grid the data was defined on.
        self.grid = grid

        # Number of volumes (1=3D data)
        self.nvols = nvols
        if self.nvols == 1:
            self.ndim = 3
        else:
            self.ndim = 4

        # File it was loaded from, if relevant
        self.fname = fname

        # Number of decimal places to display data to
        self.dps = 1

        # Whether raw data is 2d + time incorrectly returned as 3D
        self.raw_2dt = False

        # Treat as an ROI data set if requested
        self._regions = None
        self._range = None
        self.set_roi(roi)

        # Metadata - saved as NIFTI extension. Keys must be strings and
        # values must be YAML-convertible
        if metadata is not None:
            self.metadata = metadata
        else:
            self.metadata = {}

    def raw(self):
        """
        Return the raw data as a Numpy array

        Instances should implement this method to get the data from file
        or internal storage
        """
        raise NotImplementedError("Internal Error: raw() has not been implemented.")

    def range(self, vol=None):
        """
        Return data max and min

        Note that obtaining the range of a large 4D data set may be expensive!

        :param vol: Index of volume to use, if not specified use whole data set
        :return: Tuple of min value, max value
        """
        if vol is None:
            if self._range is None:
                self._range = self.raw().min(), self.raw().max()
            return self._range
        else:
            voldata = self.volume(vol)
            return voldata.min(), voldata.max()

    def volume(self, vol):
        """
        Get the specified volume from a multi-volume data set

        The default implementation calls raw() to return all data. Implementations may override
        e.g. to only load the required volume.

        If the specified volume is out of range for this data, returns the last volume

        :param vol: Volume number (0=first)
        """
        rawdata = self.raw()
        if self.ndim == 4:
            rawdata = rawdata[:, :, :, min(vol, self.nvols-1)]
        return rawdata

    def value(self, pos, grid=None, as_str=False):
        """
        Return the data value at a point

        :param pos: Position as a 3D or 4D vector. If 4D last value is the volume index
                    (0 for 3D). If ``grid`` not specified, position is in world space
        :param grid: If specified, interpret position in this ``DataGrid`` co-ordinate space.
        :param str: If True, return value as string to appropriate number of decimal places.
        """
        if grid is None:
            grid = DataGrid([1, 1, 1], np.identity(4))

        data_pos = [int(math.floor(v+0.5)) for v in self.grid.grid_to_grid(pos[:3], from_grid=grid)]
        if min(data_pos) < 0:
            # Out of range but will be misinterpreted by indexing!
            value = 0
        else:
            rawdata = self.volume(pos[3])
            try:
                value = rawdata[tuple(data_pos)]
            except IndexError:
                value = 0

        if as_str:
            return sf(value)
        else:
            return value

    def timeseries(self, pos, grid=None):
        """
        Return the time/volume series at a point

        :param pos: Position as a 3D or 4D vector. If 4D last value is the volume index
                    (0 for 3D). If ``grid`` not specified, position is in world space
        :param grid: If specified, interpret position in this ``DataGrid`` co-ordinate space.
        :return: List of values, one for each volume. For 3D data, sequence has length 1.
        """
        if self.nvols == 1:
            return [self.value(pos, grid), ]

        if grid is None:
            grid = DataGrid([1, 1, 1], np.identity(4))

        data_pos = [int(math.floor(v+0.5)) for v in self.grid.grid_to_grid(pos[:3], from_grid=grid)]
        if min(data_pos) < 0:
            # Out of range but will be misinterpreted by indexing!
            return []
        else:
            rawdata = self.raw()
            try:
                return list(rawdata[data_pos[0], data_pos[1], data_pos[2], :])
            except IndexError:
                return []

    def mask(self, roi, region=None, vol=None, invert=False, output_flat=False, output_mask=False):
        """
        Mask the data

        :param roi: ROI data item If None, return all data
        :param region: If specified, return data within this region. Otherwise return
                       data within any ROI region.
        :param vol: If specified, restrict output to this volume index
        :param invert: If True, invert the mask
        :param flat: If True, return unmasked data only as flattened arrray
        :param mask: If True, return boolean mask in same grid space as data
        :return If ``flat``, 1-D Numpy array containing unmasked data. Otherwise, Numpy array
                containing data with masked points zeroed. If ``mask`` also return
                a boolean mask in the same grid space as the data.
        """
        ret = []
        if vol is not None:
            data = self.volume(vol)
        else:
            data = self.raw()

        if roi is None:
            if output_flat:
                ret.append(data.flatten())
            else:
                ret.append(data)
            if output_mask:
                ret.append(np.ones(data.shape[:3], dtype=np.int))
        else:
            roi = roi.resample(self.grid)
            if region is None:
                mask = roi.raw() > 0
            else:
                mask = roi.raw() == region
            if invert:
                mask = np.logical_not(mask)

            if output_flat:
                ret.append(data[mask])
            else:
                masked = np.zeros(data.shape)
                masked[mask] = data[mask]
                ret.append(masked)
            if output_mask:
                ret.append(mask)

        if len(ret) > 1:
            return tuple(ret)
        else:
            return ret[0]

    def resample(self, grid, order=0):
        """
        Resample the data onto a new grid

        :param grid: :class:`DataGrid` to resample the data on to
        :return: New :class:`QpData` object
        """
        data = self.raw()

        LOG.debug("Resampling from:")
        LOG.debug(self.grid.affine)
        LOG.debug("To:")
        LOG.debug(grid.affine)

        # Affine transformation matrix from current grid to new grid
        tmatrix = np.dot(np.linalg.inv(grid.affine), self.grid.affine)
        reorder, flip, tmatrix = self.grid.simplify_transforms(tmatrix)

        # Perform the flips and transpositions which simplify the transformation and
        # may avoid the need for an affine transformation, or make it a simple scaling
        if reorder != range(3):
            if data.ndim == 4:
                reorder = reorder + [3]
            data = np.transpose(data, reorder)
            
        if flip:
            for dim in flip:
                data = np.flip(data, dim)

        if not is_identity(tmatrix):
            # We were not able to reduce the transformation down to flips/transpositions
            # so we will need an affine transformation
            # scipy requires the out->in transform so invert our in->out transform
            tmatrix = np.linalg.inv(tmatrix)
            affine = tmatrix[:3, :3]
            offset = list(tmatrix[:3, 3])
            output_shape = grid.shape[:]
            if data.ndim == 4:
                # Make 4D affine with identity transform in 4th dimension
                affine = np.append(affine, [[0, 0, 0]], 0)
                affine = np.append(affine, [[0], [0], [0], [1]], 1)
                offset.append(0)
                output_shape.append(data.shape[3])

            if is_diagonal(affine):
                # The transformation is diagonal, so use faster sequence mode
                affine = np.diagonal(affine)
            #LOG.debug("WARNING: affine_transform: ")
            #LOG.debug(affine)
            #LOG.debug("Offset = ", offset)
            #LOG.debug("Input shape=", data.shape, data.min(), data.max())
            #LOG.debug("Output shape=", output_shape)
            data = scipy.ndimage.affine_transform(data, affine, offset=offset,
                                                  output_shape=output_shape, order=order)

            if self.roi:
                if data.min() < 0 or data.max() > 2**32:
                    raise QpException("ROIs must contain values between 0 and 2**32")
                if not np.equal(np.mod(data, 1), 0).any():
                    raise QpException("ROIs must contain integers only")
                data = data.astype(np.int32)

        from quantiphyse.data import NumpyData
        return NumpyData(data=data, grid=grid, name=self.name + "_resampled", roi=self.roi)

    def slice_data(self, plane, vol=0, interp_order=0):
        """
        Extract a data slice in raw data resolution

        :param plane: OrthoSlice representing the slice to be extracted. Note that this
                      slice will not in general be defined on the same grid as the data
        :param vol: volume index for use if this is a 4D data set
        :param interp_order: Order of interpolation for non-orthogonal slices
        """
        rawdata = self.volume(vol)

        data_origin = np.array(self.grid.grid_to_grid([0, 0, 0], from_grid=plane))
        data_normal = np.array(self.grid.grid_to_grid([0, 0, 1], from_grid=plane, direction=True))

        data_scaled_normal = np.array([data_normal[idx] * self.grid.spacing[idx] * self.grid.spacing[idx] for idx in range(3)])
        data_naxis = np.argmax(np.absolute(data_scaled_normal))

        data_axes = range(3)
        del data_axes[data_naxis]
        slice_basis, slice_shape = [], []
        for axis in data_axes:
            vec = [0, 0, 0]
            vec[axis] = 1
            vec[data_naxis] = -(data_scaled_normal[axis] / data_scaled_normal[data_naxis])
            slice_basis.append(vec)
            slice_shape.append(rawdata.shape[axis])

        trans_v = np.array([
            np.array(self.grid.grid_to_grid(slice_basis[0], to_grid=plane, direction=True)),
            np.array(self.grid.grid_to_grid(slice_basis[1], to_grid=plane, direction=True)),
        ])

        trans_v = np.delete(trans_v, 2, 1)
        slice_origin = [0, 0, 0]
        slice_origin[data_naxis] = np.dot(data_origin, data_scaled_normal) / data_scaled_normal[data_naxis]
        data_offset = data_origin - slice_origin + 0.5
        offset = -np.array(self.grid.grid_to_grid(data_offset, to_grid=plane, direction=True))[:2]

        ax1, sign1 = is_ortho_vector(slice_basis[0], slice_shape[0])
        ax2, sign2 = is_ortho_vector(slice_basis[1], slice_shape[0])
        if ax1 is not None and ax2 is not None:
            #LOG.debug("\nOrthoSlice: data basis: %s (shape=%s)" % (str(slice_basis), str(slice_shape)))
            slices = [None, None, None]
            slices[ax1] = self._get_slice(rawdata.shape[ax1], sign1)
            slices[ax2] = self._get_slice(rawdata.shape[ax2], sign2)

            pos = int(math.floor(data_origin[data_naxis]+0.5))
            if pos >= 0 and pos < rawdata.shape[data_naxis]:
                slices[data_naxis] = pos
                LOG.debug("Using Numpy slice: %s %s", slices, rawdata.shape)
                sdata = rawdata[slices]
                smask = np.ones(slice_shape)
            else:
                # Requested slice is outside the data range
                LOG.debug("Outside data range: %i, %i", pos, rawdata.shape[data_naxis])
                sdata = np.zeros(slice_shape)
                smask = np.zeros(slice_shape)
        else:
            LOG.debug("Full affine slice")

            #LOG.debug("OrthoSlice: plane origin: %s" % str(plane.origin))
            #LOG.debug("OrthoSlice: plane v1: %s" % str(plane.basis[0]))
            #LOG.debug("OrthoSlice: plane v2: %s" % str(plane.basis[1]))
            #LOG.debug("OrthoSlice: plane n: %s" % str(plane.normal))
            #LOG.debug("OrthoSlice: Plane affine")
            #LOG.debug(plane.affine)

            #LOG.debug("OrthoSlice: data origin: %s" % str(data_origin))
            #LOG.debug("OrthoSlice: data n: %s" % str(data_normal))
            #LOG.debug("OrthoSlice: data naxis: %i" % data_naxis)
            #LOG.debug("OrthoSlice: data affine")
            #LOG.debug(self.grid.affine)
            
            #LOG.debug("OrthoSlice: new normal=", data_scaled_normal)
            #LOG.debug("OrthoSlice: data basis: %s (shape=%s)" % (str(slice_basis), str(slice_shape)))
            #LOG.debug("OrthoSlice: trans matrix:\n%s" % (str(trans_v)))
            #LOG.debug("OrthoSlice: slice origin=", slice_origin)
            #LOG.debug("OrthoSlice: new origin: %s (offset=%s)" % (str(slice_origin), str(data_offset)))
            #LOG.debug("OrthoSlice: new plane offset: %s" % (str(offset)))
            
            #LOG.debug("Origin: ", slice_origin)
            #LOG.debug("Basis", slice_basis)
            #LOG.debug("Shape", slice_shape)
            if self.roi:
                # Use nearest neighbour interpolation for ROIs
                sdata = pg.affineSlice(rawdata, slice_shape, slice_origin, slice_basis, range(3), order=0)
                smask = np.ones(sdata.shape)
            else:
                # Generate mask by flagging out of range data with value less than data minimum
                dmin = np.min(rawdata)
                sdata = pg.affineSlice(rawdata, slice_shape, slice_origin, slice_basis, range(3), 
                                       order=interp_order, mode='constant', cval=dmin-100)
                smask = np.ones(sdata.shape)
                smask[sdata < dmin] = 0
                sdata[sdata < dmin] = 0
            LOG.debug("Done affine slice")

        return sdata, smask, trans_v, offset

    def _get_slice(self, length, sign):
        if sign == 1:
            return slice(0, length, 1)
        else:
            return slice(length-1, None, -1)

    def set_2dt(self):
        """
        Force 3D static data into the form of 2D multi-volume

        This is useful for some broken NIFTI files. Note that the 3D extent of the grid
        is completely ignored. In order to work, the underlying class must implement the
        change in raw().
        """
        if self.nvols != 1 or self.grid.shape[2] == 1:
            raise RuntimeError("Can only force to 2D timeseries if data was originally 3D static")

        self.raw_2dt = True
        self.nvols = self.grid.shape[2]
        self.ndim = 4

        # The grid transform can't be properly interpreted because basically the file is broken,
        # so just make it 2D and hope the remaining transform is sensible
        self.grid.shape[2] = 1

    def regions(self):
        """
        :return: Sequence of distinct ROI region integers, not including zero
        """
        if not self.roi:
            raise TypeError("Only ROIs have distinct regions")
        
        if self._regions is None:
            self._regions = np.unique(self.raw().astype(np.int))
            self._regions = [int(r) for r in self._regions if r > 0]

        return self._regions

    def set_roi(self, roi):
        """
        Set whether data should be interpreted as a region of interest

        :param roi: If True, interpret as roi
        """
        if roi and self.nvols != 1:
            raise TypeError("ROIs must be static (single volume) 3D data")
        self.roi = roi

    def get_bounding_box(self, ndim=3):
        """
        Returns a sequence of slice objects which
        describe the bounding box of this ROI.
        If ndim is specified, will return a bounding
        box of this number of dimensions, truncating
        and appending slices as required.

        This enables data to be
        easily restricted to the ROI region and
        reduce data copying.

        e.g.
        slices = roi.get_bounding_box(img.ndim)
        img_restric = data[slices]
        ... process img_restict, returning out_restrict
        out_full = np.zeros(img.shape)
        out_full[slices] = out_restrict
        """
        if not self.roi:
            raise RuntimeError("get_bounding_box() called on non-ROI data")

        slices = [slice(None)] * ndim
        for dim in range(min(ndim, 3)):
            axes = [i for i in range(3) if i != dim]
            nonzero = np.any(self.raw(), axis=tuple(axes))
            bb_start, bb_end = np.where(nonzero)[0][[0, -1]]
            slices[dim] = slice(bb_start, bb_end+1)

        return slices

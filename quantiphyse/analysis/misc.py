import numpy as np

from PySide import QtGui

from ..utils import table_to_str
from . import Process, BackgroundProcess
from .overlay_analysis import OverlayAnalysis

class MeanValuesProcess(Process):
    """
    Create new overlay by replacing voxel values with mean within each ROI region
    """
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)

    def run(self, options):
        roi_name = options.pop('roi', None)
        data_name = options.pop('data', None)
        output_name = options.pop('output-name', None)

        if roi_name is None:
            roi = self.ivm.current_roi
        else:
            roi = self.ivm.rois[roi_name]

        if data_name is None:
            data = self.ivm.main.std
        else:
            data = self.ivm.data[data_name].std

        if output_name is None:
            output_name = data.name + "_means"

        ov_data = np.zeros(data.shape)
        for region in roi.regions:
            if data.shape[3] > 1:
                ov_data[roi == region] = np.mean(data[roi.std == region])
            else:
                ov_data[roi == region] = np.mean(data[roi.std == region], axis=0)

        self.ivm.add_data(ov_data, name=output_name, make_current=True)
        self.status = Process.SUCCEEDED

class CalcVolumesProcess(Process):
    """
    Calculate volume of ROI region or regions
    """
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)
        self.model = QtGui.QStandardItemModel()

    def run(self, options):
        roi_name = options.pop('roi', None)
        sel_region = options.pop('region', None)

        if roi_name is None:
            roi = self.ivm.current_roi
        else:
            roi = self.ivm.rois[roi_name]

        self.model.clear()
        self.model.setVerticalHeaderItem(0, QtGui.QStandardItem("Num voxels"))
        self.model.setVerticalHeaderItem(1, QtGui.QStandardItem("Volume (mm^3)"))

        sizes = self.ivm.grid.spacing
        if roi is not None:
            counts = np.bincount(roi.std.flatten())
            for idx, region in enumerate(roi.regions):
                if sel_region is None or region == sel_region:
                    nvoxels = counts[region]
                    vol = counts[region]*sizes[0]*sizes[1]*sizes[2]
                    self.model.setHorizontalHeaderItem(idx, QtGui.QStandardItem("Region %i" % region))
                    self.model.setItem(0, idx, QtGui.QStandardItem(str(nvoxels)))
                    self.model.setItem(1, idx, QtGui.QStandardItem(str(vol)))

        no_artifact = options.pop('no-artifact', False)
        if not no_artifact: 
            output_name = options.pop('output-name', "roi-vols")
            self.ivm.add_artifact(output_name, table_to_str(self.model))
        self.status = Process.SUCCEEDED

class HistogramProcess(Process):
    """
    Calculate histogram for an overlay
    """
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)
        self.model = QtGui.QStandardItemModel()

    def run(self, options):
        ov_name = options.pop('overlay', None)
        roi_name = options.pop('roi', None)
        sel_region = options.pop('region', None)
        dmin = options.pop('min', None)
        dmax = options.pop('max', None)
        bins = options.pop('bins', 20)
        output_name = options.pop('output-name', "histogram")
        no_artifact = options.pop('no-artifact', False)

        if roi_name is None and self.ivm.current_roi is None:
            roi = np.ones(self.ivm.shape[:3])
            roi_labels = [1,]
        elif roi_name is None:
            roi = self.ivm.current_roi.std
            roi_labels = roi.regions
        else:
            roi = self.ivm.rois[roi_name].std
            roi_labels = roi.regions

        if ov_name is None:
            ovs = self.ivm.data.values()
        else:
            ovs = [self.ivm.data[ov_name]]

        self.model.setHorizontalHeaderItem(0, QtGui.QStandardItem("x0"))
        self.model.setHorizontalHeaderItem(1, QtGui.QStandardItem("x1"))  
        self.xvals, self.edges, self.hist = None, None, {}
        col = 2
        
        for ov in [qpd.std for qpd in ovs]:
            hrange = [dmin, dmax]
            if dmin is None: hrange[0] = ov.min()
            if dmax is None: hrange[1] = ov.max()
            for region in roi_labels:
                if self.debug: print("Doing %s region %i" % (ov.name, region))
                if sel_region is not None and region != sel_region:
                    if self.debug: print("Ignoring this region")
                    continue
                region_data = ov[roi == region]
                yvals, edges = np.histogram(region_data, bins=bins, range=hrange)
                if self.xvals is None:
                    self.edges = edges
                    self.xvals = [(edges[i] + edges[i+1])/2 for i in range(len(edges)-1)]
                    for idx in range(len(edges)-1):
                        self.model.setVerticalHeaderItem(idx, QtGui.QStandardItem(""))
                        self.model.setItem(idx, 0, QtGui.QStandardItem(str(self.edges[idx])))
                        self.model.setItem(idx, 1, QtGui.QStandardItem(str(self.edges[idx+1])))
                self.model.setHorizontalHeaderItem(col, QtGui.QStandardItem("%s\nRegion %i" % (ov.name, region)))
                for idx, v in enumerate(yvals):
                    self.model.setItem(idx, col, QtGui.QStandardItem(str(v)))
                if ov.name not in self.hist: self.hist[ov.name] = {}
                self.hist[ov.name][region] = yvals
                col += 1

        if not no_artifact: 
            if self.debug: print("Adding %s" % output_name)
            self.ivm.add_artifact(output_name, table_to_str(self.model))
        self.status = Process.SUCCEEDED

class RadialProfileProcess(Process):
    """
    Calculate radial profile for an overlay
    """
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)
        self.model = QtGui.QStandardItemModel()

    def run(self, options):
        ov_name = options.pop('overlay', None)
        roi_name = options.pop('roi', None)
        #roi_region = options.pop('region', None)
        centre = options.pop('centre', None)
        output_name = options.pop('output-name', "radial-profile")
        no_artifact = options.pop('no-artifact', False)
        bins = options.pop('bins', 20)

        if roi_name is None:
            roi = self.ivm.current_roi.std
        else:
            roi = self.ivm.rois[roi_name].std

        if ov_name is None:
            ovs = self.ivm.data.values()
        else:
            ovs = [self.ivm.data[ov_name]]

        voxel_sizes = self.ivm.grid.spacing

        if centre is not None:
            centre = [int(v) for v in centre.split(",")]
        else:
            centre = self.ivm.cim_pos

        self.model.clear()
        self.rp = {}
        
        # Generate an array whose entries are integer values of the distance
        # from the centre. Set masked values to distance of -1
        x, y, z = np.indices((self.ivm.grid.shape))
        r = np.sqrt((voxel_sizes[0]*(x - centre[0]))**2 + (voxel_sizes[1]*(y - centre[1]))**2 + (voxel_sizes[2]*(z - centre[2]))**2)
        if roi is not None: 
            r[roi==0] = -1
            rmin = r[roi>0].min()   
        else: rmin = r.min()

        # Generate histogram of number of voxels in each bin
        # Use the range parameter to ignore masked values with negative distances
        voxels_per_bin, self.edges = np.histogram(r, bins=bins, range=(rmin, r.max()))

        # Prevent divide by zero, if there are no voxels in a bin, this is OK because
        # there will be no data either
        voxels_per_bin[voxels_per_bin==0] = 1
        self.xvals = [(self.edges[i] + self.edges[i+1])/2 for i in range(len(self.edges)-1)]

        for idx, xval in enumerate(self.xvals):
            self.model.setVerticalHeaderItem(idx, QtGui.QStandardItem(str(xval)))

        for col, data in enumerate([qpd.std for qpd in ovs]):
            self.model.setHorizontalHeaderItem(col, QtGui.QStandardItem("%s" % data.name))
                
            # If overlay is 4d, get current 3d volume
            if len(data.shape) == 4:
                data = data[:, :, :, centre[3]]

            # Generate histogram by distance, weighted by data
            rpd, junk = np.histogram(r, weights=data, bins=bins, range=(rmin, r.max()))

            # Divide by number of voxels in each bin to get average value by distance.
            rp = rpd / voxels_per_bin
            for idx, v in enumerate(rp):
                self.model.setItem(idx, col, QtGui.QStandardItem(str(v)))
            self.rp[data.name] = rp

        if not no_artifact: 
            self.ivm.add_artifact(output_name, table_to_str(self.model))
        self.status = Process.SUCCEEDED

class OverlayStatisticsProcess(Process):
    """
    Calculate summary statistics on data
    """
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)
        self.model = QtGui.QStandardItemModel()
        self.ia = OverlayAnalysis(ivm=self.ivm)

    def run(self, options):
        roi_name = options.pop('roi', None)
        ov_name = options.pop('overlay', None)
        output_name = options.pop('output-name', "overlay-stats")
        no_artifact = options.pop('no-artifact', False)
        if ov_name is None:
            ovs = self.ivm.data.values()
        else:
            ovs = [self.ivm.data[ov_name]]
            
        if roi_name is None:
            roi = self.ivm.current_roi
            print("Current=", roi)
        else:
            roi = self.ivm.rois[roi_name]
            print("Specified=", roi)

        self.model.clear()
        self.model.setVerticalHeaderItem(0, QtGui.QStandardItem("Mean"))
        self.model.setVerticalHeaderItem(1, QtGui.QStandardItem("Median"))
        self.model.setVerticalHeaderItem(2, QtGui.QStandardItem("Variance"))
        self.model.setVerticalHeaderItem(3, QtGui.QStandardItem("Min"))
        self.model.setVerticalHeaderItem(4, QtGui.QStandardItem("Max"))

        col = 0
        for ov in ovs:
            stats1, roi_labels, hist1, hist1x = self.ia.get_summary_stats(ov, roi, **options)
            for ii in range(len(stats1['mean'])):
                self.model.setHorizontalHeaderItem(col, QtGui.QStandardItem("%s\nRegion %i" % (ov.name, roi_labels[ii])))
                self.model.setItem(0, col, QtGui.QStandardItem(str(np.around(stats1['mean'][ii], ov.dps))))
                self.model.setItem(1, col, QtGui.QStandardItem(str(np.around(stats1['median'][ii], ov.dps))))
                self.model.setItem(2, col, QtGui.QStandardItem(str(np.around(stats1['std'][ii], ov.dps))))
                self.model.setItem(3, col, QtGui.QStandardItem(str(np.around(stats1['min'][ii], ov.dps))))
                self.model.setItem(4, col, QtGui.QStandardItem(str(np.around(stats1['max'][ii], ov.dps))))
                col += 1

        if not no_artifact: 
            self.ivm.add_artifact(output_name, table_to_str(self.model))
        self.status = Process.SUCCEEDED

class SimpleMathsProcess(Process):
    
    def __init__(self, ivm, **kwargs):
        Process.__init__(self, ivm, **kwargs)
        self.model = QtGui.QStandardItemModel()

    def run(self, options):
        globals = {'np': np, 'ivm': self.ivm}
        for name, ovl in self.ivm.data.items():
            globals[name] = ovl.std
        for name, proc in options.items():
            result = eval(proc, globals)
            self.ivm.add_data(result, name=name)
       
        self.status = Process.SUCCEEDED

class RenameDataProcess(Process):
    """ Rename data  """
    def run(self, options):
        for name, newname in options.items():
            self.ivm.rename_overlay(name, newname)
            
        self.status = Process.SUCCEEDED

class RenameRoiProcess(Process):
    """ Rename ROI  """
    def run(self, options):
        for name, newname in options.items():
            self.ivm.rename_roi(name, newname)
            
        self.status = Process.SUCCEEDED

"""
Quantiphyse - 2d ortho slice image viewer

Copyright (c) 2013-2018 University of Oxford
"""

from __future__ import division, unicode_literals, absolute_import, print_function

import collections

from PySide import QtCore, QtGui
import warnings
import numpy as np

import pyqtgraph as pg
from pyqtgraph.exporters.ImageExporter import ImageExporter

from quantiphyse.utils import get_icon, debug
from quantiphyse.volumes import OrthoSlice, Transform, DataGrid
from quantiphyse.gui.widgets import OptionsButton

from .HistogramWidget import MultiImageHistogramWidget
from .pickers import DragMode, PICKERS, PointPicker
from .data_views import MainDataView, OverlayView, RoiView, OverlayViewWidget, RoiViewWidget

class OrthoView(pg.GraphicsView):
    """
    A single slice view of data and ROI
    """

    # Signals when point is selected
    sig_pick = QtCore.Signal(int, list)

    # Signals when mouse is draggged if picker uses drag selection
    sig_drag = QtCore.Signal(int, list)

    # Signals when view is double clicked
    sig_doubleclick = QtCore.Signal(int)

    def __init__(self, ivl, ivm, ax_map, ax_labels):
        pg.GraphicsView.__init__(self)
        self.ivl = ivl
        self.ivm = ivm
        self.xaxis, self.yaxis, self.zaxis = ax_map
        self.dragging = False
        self.focus_pos = [0, 0, 0, 0]
        self.slice_plane = None
        self.slice_vol = 0
        self._arrow_items = []

        self.vline = pg.InfiniteLine(angle=90, movable=False)
        self.vline.setZValue(2)
        self.vline.setPen(pg.mkPen((0, 255, 0), width=1.0, style=QtCore.Qt.DashLine))
        self.vline.setVisible(False)

        self.hline = pg.InfiniteLine(angle=0, movable=False)
        self.hline.setZValue(2)
        self.hline.setPen(pg.mkPen((0, 255, 0), width=1.0, style=QtCore.Qt.DashLine))
        self.hline.setVisible(False)

        self.vb = pg.ViewBox(name="view%i" % self.zaxis, border=pg.mkPen((0, 0, 255), width=3.0))
        self.vb.setAspectLocked(True)
        self.vb.setBackgroundColor([0, 0, 0])
        self.vb.enableAutoRange()
        self.setCentralItem(self.vb)

        # Create static labels for the view directions
        self.labels = []
        for ax in [self.xaxis, self.yaxis]:
            self.labels.append(QtGui.QLabel(ax_labels[ax][0], parent=self))
            self.labels.append(QtGui.QLabel(ax_labels[ax][1], parent=self))
        for l in self.labels:
            l.setVisible(False)
            l.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.resizeEventOrig = self.resizeEvent
        self.resizeEvent = self.resize_win

        self.ivl.sig_focus_changed.connect(self.update)
        self.ivl.sig_arrows_changed.connect(self._arrows_changed)
        self.ivl.main_data_view.sig_redraw.connect(self.update)
        self.ivl.current_data_view.sig_redraw.connect(self.update)
        self.ivl.current_roi_view.sig_redraw.connect(self.update)

    def update(self):
        """
        Update the ortho view
        """
        # Get the current position and slice
        self.focus_pos = self.ivl.focus()
        self.slice_plane = OrthoSlice(self.ivl.grid, self.zaxis, self.focus_pos[self.zaxis])
        self.slice_vol = self.focus_pos[3]

        # Adjust axis scaling depending on whether voxel size scaling is enabled
        if self.ivl.opts.size_scaling == self.ivl.opts.SCALE_VOXELS:
            self.vb.setAspectLocked(True, ratio=(self.ivl.grid.spacing[self.xaxis] / self.ivl.grid.spacing[self.yaxis]))
        else:
            self.vb.setAspectLocked(True, ratio=1)

        self._update_labels()
        self._update_crosshairs()
        self._update_arrows()
        self.ivl.main_data_view.redraw(self.vb, self.slice_plane, self.slice_vol)
        self.ivl.current_data_view.redraw(self.vb, self.slice_plane, self.slice_vol)
        self.ivl.current_roi_view.redraw(self.vb, self.slice_plane, self.slice_vol)

    def _update_labels(self):
        for l in self.labels:
            l.setVisible(True)

        # Flip left/right depending on the viewing convention selected
        if self.xaxis == 0:
            # X-axis is left/right
            self.vb.invertX(self.ivl.opts.orientation == 0)
            if self.ivl.opts.orientation == self.ivl.opts.RADIOLOGICAL:
                l, r = 1, 0
            else:
                l, r = 0, 1
            self.labels[r].setText("R")
            self.labels[l].setText("L")

    def _update_crosshairs(self):
        self.vline.setPos(float(self.focus_pos[self.xaxis]))
        self.hline.setPos(float(self.focus_pos[self.yaxis]))
        self.vline.setVisible(self.ivl.opts.crosshairs == self.ivl.opts.SHOW)
        self.hline.setVisible(self.ivl.opts.crosshairs == self.ivl.opts.SHOW)
        self.vb.addItem(self.vline, ignoreBounds=True)
        self.vb.addItem(self.hline, ignoreBounds=True)

    def _update_arrows(self):
        """
        Update arrows so only those visible are shown
        """
        current_zpos = int(self.focus_pos[self.zaxis] + 0.5)
        for pos, col, item in self._arrow_items:
            arrow_zpos = int(pos[self.zaxis] + 0.5)
            item.setVisible(current_zpos == arrow_zpos)
    
    def _arrows_changed(self, arrows):
        item_num = 0
        for pos, col in arrows:
            if item_num == len(self._arrow_items):
                item = pg.ArrowItem()
                self.vb.addItem(item)
                self._arrow_items.append((pos, col, item))
            _, _, item = self._arrow_items[item_num]
            item.setPos(float(pos[self.xaxis]), float(pos[self.yaxis]))
            item.setPen(pg.mkPen(col))
            item.setBrush(pg.mkBrush(col))
            item.setZValue(2)
            self._arrow_items[item_num] = (pos, col, item)
            item_num += 1
        
        for _, _, item in self._arrow_items[item_num:]:
            self.vb.removeItem(item)
        
        self._arrow_items = self._arrow_items[:item_num]
        self._update_arrows()

    def resize_win(self, event):
        """
        Called when window is resized - updates the position
        of the text labels and then calls the original resize method
        """
        w = self.geometry().width()
        h = self.geometry().height()
        self.labels[0].setGeometry(0, h/2, 10, 10)
        self.labels[1].setGeometry(w-10, h/2, 10, 10)
        self.labels[2].setGeometry(w/2, h-10, 10, 10)
        self.labels[3].setGeometry(w/2, 0, 10, 10)
        self.resizeEventOrig(event)

    def wheelEvent(self, event):
        """
        Subclassed to remove scroll to zoom from pg.ImageItem
        and instead trigger a scroll through the volume
        """
        dz = int(event.delta()/120)
        pos = self.ivl.focus(self.ivm.main.grid)
        pos[self.zaxis] += dz
        self.ivl.set_focus(pos, self.ivm.main.grid)

    def mousePressEvent(self, event):
        super(OrthoView, self).mousePressEvent(event)
        if self.ivm.main is None: return

        if event.button() == QtCore.Qt.LeftButton:
            # Convert co-ords to view grid
            coords = self.ivl.main_data_view.imgs[self.vb.name].mapFromScene(event.pos())
            pos = self.ivl.focus(self.ivm.main.grid)
            pos[self.xaxis] = coords.x() - 0.5
            pos[self.yaxis] = coords.y() - 0.5
            self.ivl.set_focus(pos, self.ivm.main.grid)

            if self.ivl.picker.use_drag:
                self.dragging = True
            self.sig_pick.emit(self.zaxis, self.ivl.focus())

    def mouseReleaseEvent(self, event):
        super(OrthoView, self).mouseReleaseEvent(event)
        self.dragging = False

    def mouseDoubleClickEvent(self, event):
        super(OrthoView, self).mouseDoubleClickEvent(event)
        if event.button() == QtCore.Qt.LeftButton:
            self.sig_doubleclick.emit(self.zaxis)

    def mouseMoveEvent(self, event):
        if self.dragging:
            coords = self.ivl.main_data_view.imgs[self.vb.name].mapFromScene(event.pos())
            pos = self.ivl.focus(self.ivm.main.grid)
            pos[self.xaxis] = coords.x() - 0.5
            pos[self.yaxis] = coords.y() - 0.5
            pos = self.ivl.grid.grid_to_grid(pos, from_grid=self.ivm.main.grid)
            self.sig_drag.emit(self.zaxis, pos)
        else:
            super(OrthoView, self).mouseMoveEvent(event)

class DataSummary(QtGui.QWidget):
    """ Data summary bar """
    def __init__(self, ivl):
        self.opts = ivl.opts
        self.ivl = ivl

        QtGui.QWidget.__init__(self)
        hbox = QtGui.QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        self.vol_name = QtGui.QLineEdit()
        p = self.vol_name.sizePolicy()
        p.setHorizontalPolicy(QtGui.QSizePolicy.Expanding)
        self.vol_name.setSizePolicy(p)
        hbox.addWidget(self.vol_name)
        hbox.setStretchFactor(self.vol_name, 1)
        self.vol_data = QtGui.QLineEdit()
        self.vol_data.setFixedWidth(65)
        hbox.addWidget(self.vol_data)
        self.roi_region = QtGui.QLineEdit()
        self.roi_region.setFixedWidth(30)
        hbox.addWidget(self.roi_region)
        self.ov_data = QtGui.QLineEdit()
        self.ov_data.setFixedWidth(65)
        hbox.addWidget(self.ov_data)
        self.view_options_btn = OptionsButton(self)
        hbox.addWidget(self.view_options_btn)
        self.setLayout(hbox)

        ivl.ivm.sig_main_data.connect(self._main_changed)
        ivl.sig_focus_changed.connect(self._focus_changed)

    def show_options(self):
        self.opts.show()
        self.opts.raise_()

    def _main_changed(self, data):
        name = ""
        if data is not None:
            if data.fname is not None:
                name = data.fname
            else:
                name = data.name
        self.vol_name.setText(name)

    def _focus_changed(self, pos):
        if self.ivl.ivm.main is not None:
            self.vol_data.setText(self.ivl.ivm.main.value(pos, self.ivl.grid, str=True))
        if self.ivl.ivm.current_roi is not None:
            self.roi_region.setText(self.ivl.ivm.current_roi.value(pos, self.ivl.grid, str=True))
        if self.ivl.ivm.current_data is not None:
            self.ov_data.setText(self.ivl.ivm.current_data.value(pos, self.ivl.grid, str=True))

class Navigator:
    """
    Slider control which alters position along an axis
    """

    def __init__(self, ivl, label, axis, layout_grid, layout_ypos):
        self.ivl = ivl
        self.axis = axis
        self.data_axis = axis
        self.data_grid = None
        self._pos = -1

        layout_grid.addWidget(QtGui.QLabel(label), layout_ypos, 0)
        self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.slider.setFocusPolicy(QtCore.Qt.NoFocus)
        self.slider.setMinimumWidth(100)
        self.slider.valueChanged.connect(self._changed)
        layout_grid.addWidget(self.slider, layout_ypos, 1)

        self.spin = QtGui.QSpinBox()
        self.spin.valueChanged.connect(self._changed)
        layout_grid.addWidget(self.spin, layout_ypos, 2)

        self.ivl.ivm.sig_main_data.connect(self._main_data_changed)
        self.ivl.sig_focus_changed.connect(self._focus_changed)

    def _changed(self, value):
        if value != self._pos and self.data_grid is not None:
            pos = self.ivl.focus(self.data_grid)
            pos[self.data_axis] = value
            self.ivl.set_focus(pos, self.data_grid)
 
    def _main_data_changed(self, data):
        if data is not None:
            self.data_grid = data.grid
            self.data_axes = data.grid.get_ras_axes()[self.axis]

            if self.axis < 3:
                self._set_size(self.data_grid.shape[self.data_axis])
            else:
                self._set_size(data.nvols)

            self._focus_changed()
        else:
            self.data_grid = None
            self.data_axes = self.axis
            self._set_size(1)
            self._pos = 0

    def _focus_changed(self):
        if self.data_grid is not None:
            self._pos = int(self.ivl.focus(self.data_grid)[self.data_axis]+0.5)
            debug("Pos for slider", self.axis, self._pos)
            try:
                self.slider.blockSignals(True)
                self.spin.blockSignals(True)
                self.slider.setValue(self._pos)
                self.spin.setValue(self._pos)
            finally:
                self.slider.blockSignals(False)
                self.spin.blockSignals(False)

    def _set_size(self, size):
        try:
            self.slider.blockSignals(True)
            self.spin.blockSignals(True)
            self.slider.setRange(0, size-1)
            self.spin.setMaximum(size-1)
        finally:
            self.slider.blockSignals(False)
            self.spin.blockSignals(False)

class NavigationBox(QtGui.QGroupBox):
    """ Box containing 4D navigators """
    def __init__(self, ivl):
        self.ivl = ivl
        self.data_axes = None
        self.data_grid = None

        QtGui.QGroupBox.__init__(self, "Navigation")
        grid = QtGui.QGridLayout()
        self.setLayout(grid)

        self.navs = []
        self.navs.append(Navigator(ivl, "Axial", 2, grid, 0))
        self.navs.append(Navigator(ivl, "Sagittal", 0, grid, 1))
        self.navs.append(Navigator(ivl, "Coronal", 1, grid, 2))
        self.navs.append(Navigator(ivl, "Volume", 3, grid, 3))
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 2)

class ImageView(QtGui.QSplitter):
    """
    Widget containing three orthogonal slice views, two histogram/LUT widgets plus 
    navigation sliders and data summary view.

    The viewer maintains two main pieces of data: a grid defining the main co-ordinate
    system of the viewer and a point of focus, in co-ordinates relative to the viewing grid.

    In addition, the viewer supports 'arrows' to mark positions in space, and variable
    pickers which control the selection of data.

    The grid is generally either a straightforward 1mm RAS grid, or an approximate RAS grid
    derived from the grid of the main data. Although the focus position is provided and set
    according to this grid by default, the ``focus`` and ``set_focus`` methods allow for 
    the co-ordinates to be set or retrieved according to another arbitrary grid.

    :ivar grid: Grid the ImageView uses as the basis for the orthogonal slices. 
                This is typically an RAS-aligned version of the main data grid, or
                alternatively an RAS world-grid
    """

    # Signals when point of focus is changed
    sig_focus_changed = QtCore.Signal(list)

    # Signals when the set of marker arrows has changed 
    sig_arrows_changed = QtCore.Signal(list)

    # Signals when the picker mode is changed
    sig_picker_changed = QtCore.Signal(object)

    # Signals when a point is picked. Emission of this signal depends
    # on the picking mode selected
    sig_selection_changed = QtCore.Signal(object)

    def __init__(self, ivm, opts):
        super(ImageView, self).__init__(QtCore.Qt.Vertical)

        self.grid = DataGrid([1, 1, 1], np.identity(4))
        self._pos = [0, 0, 0, 0]

        self.ivm = ivm
        self.opts = opts
        self.picker = PointPicker(self) 
        self.arrows = []

        # Visualisation information for data and ROIs
        self.main_data_view = MainDataView(self.ivm)
        self.current_data_view = OverlayView(self.ivm)
        self.current_roi_view = RoiView(self.ivm)

        # Navigation controls layout
        control_box = QtGui.QWidget()
        vbox = QtGui.QVBoxLayout()
        control_box.setLayout(vbox)  

        # Create the navigation sliders and the ROI/Overlay view controls
        vbox.addWidget(DataSummary(self))
        hbox = QtGui.QHBoxLayout()
        nav_box = NavigationBox(self)
        hbox.addWidget(nav_box)
        roi_box = RoiViewWidget(self, self.current_roi_view)
        hbox.addWidget(roi_box)
        ovl_box = OverlayViewWidget(self, self.current_data_view)
        hbox.addWidget(ovl_box)
        vbox.addLayout(hbox)  

        # Histogram which controls colour map and levels for main volume
        self.main_data_view.histogram = MultiImageHistogramWidget(self, self.main_data_view, percentile=99)
        
        # Histogram which controls colour map and levels for data
        self.current_data_view.histogram = MultiImageHistogramWidget(self, self.current_data_view)

        # For each view window, this is the volume indices of the x, y and z axes for the view
        self.ax_map = [[0, 1, 2], [0, 2, 1], [1, 2, 0]]
        self.ax_labels = [("L", "R"), ("P", "A"), ("I", "S")]

        # Create three orthogonal views
        self.ortho_views = {}
        for i in range(3):
            win = OrthoView(self, self.ivm, self.ax_map[i], self.ax_labels)
            win.sig_pick.connect(self._pick)
            win.sig_drag.connect(self._drag)
            win.sig_doubleclick.connect(self._toggle_maximise)
            self.ortho_views[win.zaxis] = win

        # Main graphics layout
        #gview = pg.GraphicsView(background='k')
        gview = QtGui.QWidget()
        self.layout_grid = QtGui.QGridLayout()
        self.layout_grid.setHorizontalSpacing(2)
        self.layout_grid.setVerticalSpacing(2)
        self.layout_grid.setContentsMargins(0, 0, 0, 0)
        self.layout_grid.addWidget(self.ortho_views[1], 0, 0,)
        self.layout_grid.addWidget(self.ortho_views[0], 0, 1)
        self.layout_grid.addWidget(self.main_data_view.histogram, 0, 2)
        self.layout_grid.addWidget(self.ortho_views[2], 1, 0)
        self.layout_grid.addWidget(self.current_data_view.histogram, 1, 2)
        self.layout_grid.setColumnStretch(0, 3)
        self.layout_grid.setColumnStretch(1, 3)
        self.layout_grid.setColumnStretch(2, 1)
        self.layout_grid.setRowStretch(0, 1)
        self.layout_grid.setRowStretch(1, 1)
        gview.setLayout(self.layout_grid)
        self.addWidget(gview)
        self.addWidget(control_box)
        self.setStretchFactor(0, 5)
        self.setStretchFactor(1, 1)

        self.ivm.sig_main_data.connect(self._main_data_changed)
        self.opts.sig_options_changed.connect(self._opts_changed)
      
    def focus(self, grid=None):
        """
        Get the current focus position

        :param grid: Report position using co-ordinates relative to this grid. 
                     If not specified, report current view grid co-ordinates
        :return: 4D sequence containing position plus the current data volume index
        """
        if grid is None:
            return list(self._pos)
        else:
            world = self.grid.grid_to_world(self._pos)
            return list(grid.world_to_grid(world))

    def set_focus(self, pos, grid=None):
        """
        Set the current focus position

        :param grid: Specify position using co-ordinates relative to this grid. 
                     If not specified, position is in current view grid co-ordinates
        """
        if grid is not None:
            world = grid.grid_to_world(pos)
            pos = self.grid.world_to_grid(world)

        self._pos = list(pos)
        if len(self._pos) != 4:
            raise Exception("Position must be 4D")
            
        debug("Cursor position: ", self._pos)
        self.sig_focus_changed.emit(self._pos)

    def set_picker(self, pickmode):
        """
        Set the picking mode

        :param pickmode: Picking mode from :class:`PickMode`
        """
        self.picker.cleanup()
        self.picker = PICKERS[pickmode](self)
        self.sig_picker_changed.emit(self.picker)
        
    def add_arrow(self, pos, grid=None, col=None):
        """
        Add an arrow to mark a particular position

        :param pos:  Position co-ordinates
        :param grid: Grid co-ordinates are relative to, if not specified
                     uses viewing grid
        :param col:  Colour as RGB sequence, if not specified uses a default
        """
        if grid is not None:
            world = grid.grid_to_world(pos)
            pos = self.grid.world_to_grid(world)
        
        if col is None:
            # Default to grey arrow
            col = [127, 127, 127]

        self.arrows.append((pos, col))
        self.sig_arrows_changed.emit(self.arrows)

    def remove_arrows(self):
        """ 
        Remove all the arrows that have been placed 
        """
        self.arrows = []
        self.sig_arrows_changed.emit(self.arrows)

    def capture_view_as_image(self, window, outputfile):
        """ 
        Export an image using pyqtgraph 
        
        FIXME this is not working at the moment
        """
        if window not in (1, 2, 3):
            raise RuntimeError("No such window: %i" % window)

        expimg = self.ortho_views[window-1].img
        exporter = ImageExporter(expimg)
        exporter.parameters()['width'] = 2000
        exporter.export(str(outputfile))

    def _pick(self, win, pos):
        """
        Called when a point is picked in one of the viewing windows
        """
        self.picker.pick(win, pos)
        self.sig_selection_changed.emit(self.picker)

    def _drag(self, win, pos):
        """
        Called when a drag selection is changed in one of the viewing windows
        """
        self.picker.drag(win, pos)
        self.sig_selection_changed.emit(self.picker)

    def _toggle_maximise(self, win, state=-1):
        """ 
        Maximise/Minimise view window
        If state=1, maximise, 0=show all, -1=toggle 
        """
        o1 = (win+1) % 3
        o2 = (win+2) % 3
        if state == 1 or (state == -1 and self.ortho_views[o1].isVisible()):
            # Maximise
            self.layout_grid.addWidget(self.ortho_views[win], 0, 0, 2, 2)
            self.ortho_views[o1].setVisible(False)
            self.ortho_views[o2].setVisible(False)
            self.ortho_views[win].setVisible(True)
        elif state == 0 or (state == -1 and not self.ortho_views[o1].isVisible()):
            # Show all three
            self.layout_grid.addWidget(self.ortho_views[1], 0, 0, )
            self.layout_grid.addWidget(self.ortho_views[0], 0, 1)
            self.layout_grid.addWidget(self.ortho_views[2], 1, 0)
            self.ortho_views[o1].setVisible(True)
            self.ortho_views[o2].setVisible(True)
            self.ortho_views[win].setVisible(True)

    def _opts_changed(self):
        z_roi = int(self.opts.display_order == self.opts.ROI_ON_TOP)
        self.current_roi_view.opts["z_value"] = img.setZValue(z_roi)
        self.current_data_view.opts["z_value"] = img.setZValue(1-z_roi)

    def _main_data_changed(self, data):
        if data is not None:
            self.grid = data.grid.get_standard()
            debug("Main data raw grid")
            debug(data.grid.affine)
            debug("RAS aligned")
            debug(self.grid.affine)

            f = [int(v/2) for v in data.grid.shape] + [int(data.nvols/2)]
            debug("Initial focus (data): ", f)
            self.set_focus(f, grid=data.grid)
            debug("Initial focus (std): ", self._pos)
            # If one of the dimensions has size 1 the data is 2D so
            # maximise the relevant slice
            self._toggle_maximise(0, state=0)
            data_axes = data.grid.get_ras_axes()
            for d in range(3):
                if data.grid.shape[data_axes[d]] == 1:
                    self._toggle_maximise(d, state=1)

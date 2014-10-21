__author__ = 'engs1170'

from PySide import QtCore, QtGui
import numpy as np
from QtInherit.QtSubclass import QGroupBoxB

from skimage.segmentation import random_walker


class RandomWalkerWidget(QtGui.QWidget):

    """
    Random walker algorithm for applying a random walk segmentation
    """

    # set the annotation label
    sig_set_annotation = QtCore.Signal(int)
    # save the annotation
    sig_save_annotation = QtCore.Signal(bool)
    # emit reset command to viewer
    sig_emit_reset = QtCore.Signal(bool)

    def __init__(self):
        super(RandomWalkerWidget, self).__init__()

        #self.setStatusTip("Click points on the 4D volume to see time curve")

        # Number of clusters inside the ROI
        self.combo = QtGui.QSpinBox(self)
        self.combo.setRange(0, 10)
        self.combo.setValue(1)
        #self.combo.activated[str].connect(self.emit_cchoice)
        self.combo.setToolTip("Set the label")

        #Run clustering button
        self.b1 = QtGui.QPushButton('Set', self)
        self.b1.clicked.connect(self.setAnnotLabel)

        #Run clustering button
        self.b2 = QtGui.QPushButton('Save annotation', self)
        self.b2.clicked.connect(self.saveAnnotLabel)

        # Run random walker
        self.b3 = QtGui.QPushButton('Run random walker', self)
        self.b3.clicked.connect(self.run_random_walker)

        # Number of clusters inside the ROI
        self.combo2 = QtGui.QSpinBox(self)
        self.combo2.setRange(0, 50000)
        self.combo2.setSingleStep(5)
        self.combo2.setValue(10000)
        #self.combo.activated[str].connect(self.emit_cchoice)
        self.combo2.setToolTip("Diffusion difficulty")

        l1 = QtGui.QVBoxLayout()
        l1.addWidget(self.combo)
        l1.addWidget(self.b1)
        l1.addWidget(self.b2)
        l1.addWidget(self.b3)
        l1.addWidget(self.combo2)
        l1.addStretch(1)
        self.setLayout(l1)

        # Initialisation
        # Volume management widget
        self.ivm = None

    def add_image_management(self, image_vol_management):

        """
        Adding image management
        """
        self.ivm = image_vol_management

    def setAnnotLabel(self):
        self.sig_set_annotation.emit(self.combo.value())

    def saveAnnotLabel(self):
        self.sig_save_annotation.emit(True)

    def run_random_walker(self):
        labels = random_walker(self.ivm.image, self.ivm.overlay_all['annotation'], beta=self.combo2.value(),
                               mode='cg_mg', multichannel=True)

        self.ivm.set_overlay('segmentation', labels)
        self.ivm.set_current_overlay('segmentation')
        self.sig_emit_reset.emit(1)

        # TODO incorporate PCA modes into this analysis
        # TODO Think one of the methods... maybe SLIC creates a PCA image. Just use that.

        # TODO Create a menu option to save an overlay as an image













import time
import numpy as np

from pkview.volumes.volume_management import Overlay, Roi
from pkview.analysis import Process, BackgroundProcess
from pkview.analysis.pk_model import PyPk

def _run_pk(id, queue, img1sub, t101sub, r1, r2, delt, injt, tr1, te1, dce_flip_angle, dose, model_choice):
    """
    Simple function to run the c++ pk modelling code. Must be a function to work with multiprocessing
    """
    #print("pk modelling worker started")
    try:
        t1 = np.arange(0, img1sub.shape[-1])*delt
        # conversion to minutes
        t1 = t1/60.0

        injtmins = injt/60.0

        Dose = dose

        # conversion to seconds
        dce_TR = tr1/1000.0
        dce_TE = te1/1000.0

        #specify variable upper bounds and lower bounds
        ub = [10, 1, 0.5, 0.5]
        lb = [0, 0.05, -0.5, 0]

        # contiguous array
        img1sub = np.ascontiguousarray(img1sub)
        t101sub = np.ascontiguousarray(t101sub)
        t1 = np.ascontiguousarray(t1)

        Pkclass = PyPk(t1, img1sub, t101sub)
        Pkclass.set_bounds(ub, lb)
        Pkclass.set_parameters(r1, r2, dce_flip_angle, dce_TR, dce_TE, Dose)

        # Initialise fitting
        # Choose model type and injection time
        Pkclass.rinit(model_choice, injtmins)

        # Iteratively process 5000 points at a time
        # (this can be performed as a multiprocess soon)

        size_step = max(1, np.around(img1sub.shape[0]/5))
        size_tot = img1sub.shape[0]
        steps1 = np.around(size_tot/size_step)
        num_row = 1.0  # Just a placeholder for the meanwhile

        #print("Number of voxels per step: ", size_step)
        #print("Number of steps: ", steps1)
        queue.put((num_row, 1))
        for ii in range(int(steps1)):
            if ii > 0:
                progress = float(ii) / float(steps1) * 100
                # print(progress)
                queue.put((num_row, progress))

            time.sleep(0.2)  # sleeping seems to allow queue to be flushed out correctly
            x = Pkclass.run(size_step)
            # print(x)
        #print("Done")

        # Get outputs
        res1 = np.array(Pkclass.get_residual())
        fcurve1 = np.array(Pkclass.get_fitted_curve())
        params2 = np.array(Pkclass.get_parameters())

        # final update to progress bar
        queue.put((num_row, 100))
        time.sleep(0.2)  # sleeping seems to allow queue to be flushed out correctly
        return id, True, (res1, fcurve1, params2)
    except:
        #print("PK worker error: %s" % sys.exc_info()[0])
        return id, False, sys.exc_info()[0]

class PkModellingProcess(BackgroundProcess):

    def __init__(self, ivm, **kwargs):
        BackgroundProcess.__init__(self, ivm, _run_pk, **kwargs)

    def run(self, options):
        img1 = self.ivm.vol.data
        roi1 = self.ivm.current_roi.data
        t101 = self.ivm.overlays["T10"].data

        R1 = options['r1']
        R2 = options['r2']
        DelT = options['dt']
        InjT = options['tinj']
        TR = options['tr']
        TE = options['te']
        FA = options['fa']
        self.thresh1val = options['ve-thresh']
        Dose = options.get('dose', 0)
        model_choice = options['model']

        # Baseline defaults to time points prior to injection
        baseline_tpts = int(1 + InjT / DelT)
        #print("First %i time points used for baseline normalisation" % baseline_tpts)
        baseline = np.mean(img1[:, :, :, :baseline_tpts], axis=-1)

        #print("Convert to list of enhancing voxels")
        img1vec = np.reshape(img1, (-1, img1.shape[-1]))
        T10vec = np.reshape(t101, (-1))
        roi1vec = np.array(np.reshape(roi1, (-1)), dtype=bool)
        baseline = np.reshape(baseline, (-1))

        #print("Make sure the type is correct")
        img1vec = np.array(img1vec, dtype=np.double)
        T101vec = np.array(T10vec, dtype=np.double)
        self.roi1vec = np.array(roi1vec, dtype=bool)

        #print("subset")
        # Subset within the ROI and
        img1sub = img1vec[roi1vec, :]
        T101sub = T101vec[roi1vec]
        self.baseline = baseline[roi1vec]

        # Normalisation of the image - convert to signal enhancement
        img1sub = img1sub / (np.tile(np.expand_dims(self.baseline, axis=-1), (1, img1.shape[-1])) + 0.001) - 1

        #print("Running pk")
        self.shape = img1.shape
        args = [img1sub, T101sub, R1, R2, DelT, InjT, TR, TE, FA, Dose, model_choice]
        self.start(1, args)

    def timeout(self):
        if self.queue.empty(): return
        while not self.queue.empty():
            num_row, progress = self.queue.get()
        print(progress)
        self.sig_progress.emit(float(progress)/100)

    def finished(self):
        """
        Add output overlays to the IVM
        """
        self.log = ""
        if self.status == Process.SUCCEEDED:
            # Only one worker - get its output
            var1 = self.output[0]

            #make sure that we are accessing whole array
            roi1v = self.roi1vec

            #Params: Ktrans, ve, offset, vp
            Ktrans1 = np.zeros((roi1v.shape[0]))
            Ktrans1[roi1v] = var1[2][:, 0] * (var1[2][:, 0] < 2.0) + 2 * (var1[2][:, 0] > 2.0)

            ve1 = np.zeros((roi1v.shape[0]))
            ve1[roi1v] = var1[2][:, 1] * (var1[2][:, 1] < 2.0) + 2 * (var1[2][:, 1] > 2.0)
            ve1 *= (ve1 > 0)

            kep1p = Ktrans1 / (ve1 + 0.001)
            kep1p[np.logical_or(np.isnan(kep1p), np.isinf(kep1p))] = 0
            kep1p *= (kep1p > 0)
            kep1 = kep1p * (kep1p < 2.0) + 2 * (kep1p >= 2.0)

            offset1 = np.zeros((roi1v.shape[0]))
            offset1[roi1v] = var1[2][:, 2]

            vp1 = np.zeros((roi1v.shape[0]))
            vp1[roi1v] = var1[2][:, 3]

            # Convert signal enhancement back to data curve
            sig = (var1[1] + 1) * (np.tile(np.expand_dims(self.baseline, axis=-1), (1, self.shape[-1])))
            
            estimated_curve1 = np.zeros((roi1v.shape[0], self.shape[-1]))
            estimated_curve1[roi1v, :] = sig

            residual1 = np.zeros((roi1v.shape[0]))
            residual1[roi1v] = var1[0]

            # Convert to list of enhancing voxels
            Ktrans1vol = np.reshape(Ktrans1, (self.shape[:-1]))
            ve1vol = np.reshape(ve1, (self.shape[:-1]))
            offset1vol = np.reshape(offset1, (self.shape[:-1]))
            vp1vol = np.reshape(vp1, (self.shape[:-1]))
            kep1vol = np.reshape(kep1, (self.shape[:-1]))
            estimated1vol = np.reshape(estimated_curve1, self.shape)

            #thresholding according to upper limit
            p = np.percentile(Ktrans1vol, self.thresh1val)
            Ktrans1vol[Ktrans1vol > p] = p
            p = np.percentile(kep1vol, self.thresh1val)
            kep1vol[kep1vol > p] = p

            #slices = self.ivm.current_roi.get_bounding_box(ndim=self.ivm.vol.ndim)
            #roi_slices = slices[:self.ivm.current_roi.ndim]
            self.ivm.add_overlay(Overlay('ktrans', data=Ktrans1vol), make_current=True)
            self.ivm.add_overlay(Overlay('ve', data=ve1vol))
            self.ivm.add_overlay(Overlay('kep', data=kep1vol))
            self.ivm.add_overlay(Overlay('offset', data=offset1vol))
            self.ivm.add_overlay(Overlay('vp', data=vp1vol))
            self.ivm.add_overlay(Overlay("Model curves", data=estimated1vol))
            
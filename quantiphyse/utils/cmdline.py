"""
Quantiphyse - Classes for interacting with external command line programs

Copyright (c) 2013-2018 University of Oxford
"""

import os
import sys
import shlex
import subprocess
import tempfile
import re
import shutil
import logging

from quantiphyse.data import load, save
from quantiphyse.utils import QpException
from quantiphyse.processes import Process

LOG = logging.getLogger(__name__)

def _get_files(workdir):
    """
    Get a list of files currently in a working directory
    """
    dir_files = []
    for _, _, files in os.walk(workdir):
        for dir_file in files:
            if os.path.isfile(dir_file):
                dir_files.append(dir_file)
    return dir_files

def _run_cmd(worker_id, queue, workdir, cmdline, expected_data, expected_rois):
    """
    Multiprocessing worker to run a command in the background
    """
    try:
        pre_run_files = _get_files(workdir)

        cmd_args = shlex.split(cmdline, posix=not sys.platform.startswith("win"))
        os.chdir(workdir)
        log = ""
        proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while 1:
            # This returns None while subprocess is running
            retcode = proc.poll() 
            line = proc.stdout.readline()
            log += line
            if queue: queue.put(line)
            if retcode is not None: break

        if retcode != 0:
            LOG.debug("External program failed: %s", cmdline)
            LOG.debug(log)
            raise QpException("Failed to execute %s: return code %i" % (cmd_args[0], retcode), detail=log)

        post_run_files = _get_files(workdir)
        new_files = [f for f in post_run_files if f not in pre_run_files]
        LOG.debug("New files: %s", new_files)
        data, rois = [], []

        for new_file in new_files:
            basename = new_file.split(".", 1)[0]
            LOG.debug("Checking if we need to output: %s %s %s", basename, expected_data, expected_rois)
            if (basename in expected_data or 
                    basename in expected_rois or 
                    (not expected_data and not expected_rois)):

                LOG.debug("Adding output file %s", new_file)
                if basename in expected_data:
                    data.append(new_file)
                elif basename in expected_rois:
                    rois.append(new_file)
                else:
                    data.append(new_file)

        return worker_id, True, (log, data, rois)
    except Exception as exc:
        import traceback
        traceback.print_exc(exc)
        return worker_id, False, exc

class CommandProcess(Process):
    """
    Process which runs an external command in the background
    """
    def __init__(self, ivm, workdir=None, path=(), **kwargs):
        Process.__init__(self, ivm, worker_fn=_run_cmd, **kwargs)
        self.path = path
        self._expected_steps = [None,]
        self._current_step = 0
        self._current_data = None
        self._current_roi = None

        if workdir is None:
            self.workdir = tempfile.mkdtemp(prefix="qp")
            self.workdir_istemp = True
        else:
            self.workdir = workdir
            self.workdir_istemp = False

    def __del__(self):
        if hasattr(self, "workdir_istemp") and self.workdir_istemp:
            try:
                shutil.rmtree(self.workdir)
            except:
                LOG.warn("Failed to remove temporary directory: %s", self.workdir)

    def add_data(self, data_name):
        """
        Add a data item to the working directory from the IVM
        """
        fname = os.path.join(self.workdir, data_name)
        save(self.ivm.data.get(data_name, self.ivm.rois.get(data_name)), fname)

    def timeout(self):
        """ 
        Monitor queue for updates and send sig_progress 
        """
        if self.queue.empty(): return
        while not self.queue.empty():
            line = self.queue.get()
            LOG.debug(line)
            if self._current_step < len(self._expected_steps):
                expected = self._expected_steps[self._current_step]
                if expected is not None and re.match(expected, line):
                    self._current_step += 1
                    complete = float(self._current_step) / (len(self._expected_steps)+1)
                    LOG.debug(complete)
                    self.sig_progress.emit(complete)
        
    def finished(self):
        """ 
        Add data to IVM and set log 

        Note that we need to call ``qpdata.raw()`` to make sure
        data is all loaded into memory as the files may be temporary
        """
        if self.status == Process.SUCCEEDED:
            self.log, data_files, roi_files = self.worker_output[0]
            LOG.debug("Loading data: %s %s", data_files, roi_files)
            for data_file in data_files:
                qpdata = load(os.path.join(self.workdir, data_file))
                qpdata.name = self.ivm.suggest_name(data_file.split(".", 1)[0], ensure_unique=False)
                qpdata.raw()
                self.ivm.add_data(qpdata, make_current=(data_file == self._current_data))
            for roi_file in roi_files:
                qpdata = load(os.path.join(self.workdir, roi_file))
                qpdata.name = self.ivm.suggest_name(roi_file.split(".", 1)[0], ensure_unique=False)
                qpdata.raw()
                self.ivm.add_roi(qpdata, make_current=(roi_file == self._current_roi))

    def _get_cmdline(self, options):
        cmd = options.pop("cmd", None)
        if cmd is None:
            raise QpException("No command provided")

        cmdline = options.pop("cmdline", None)
        argdict = options.pop("argdict", {})
        if cmdline is None and not argdict:
            raise QpException("No command arguments provided")
            
        for arg, value in argdict.items():
            if value != "": 
                cmdline += " --%s=%s" % (arg, value)
            else:
                cmdline += " --%s" % arg
                
        cmd = self._find(cmd)
        cmdline = cmd + " " + cmdline
        LOG.debug(cmdline)
        return cmdline

    def run(self, options):
        """ 
        Run a program
        """
        cmdline = self._get_cmdline(options)

        expected_data = options.pop("output-data", [])
        expected_rois = options.pop("output-rois", [])

        self._expected_steps = options.pop("expected-steps", [None,])
        self._current_step = 0
        self._current_data = options.pop("set-current-data", None)
        self._current_roi = options.pop("set-current-roi", None)

        LOG.debug("Working directory: %s", self.workdir)
        self._add_data_from_cmdline(cmdline)

        self.log = ""
        worker_args = [self.workdir, cmdline, expected_data, expected_rois]
        self.start_bg(worker_args)
  
    def _find(self, cmd):
        """ 
        Find the program, either in the 'local' directory, or in $FSLDEVDIR/bin or $FSLDIR/bin 
        This is called each time the program is run so the caller can control where programs
        are searched for at any time
        """
        for bindir in self.path:
            ex = os.path.join(bindir, cmd)
            LOG.debug("Checking %s", ex)
            if os.path.isfile(ex) and os.access(ex, os.X_OK):
                return ex
            elif sys.platform.startswith("win"):
                ex += ".exe"
                if os.path.isfile(ex) and os.access(ex, os.X_OK):
                    return ex
            
        LOG.warn("Failed to find command line program: %s", cmd)
        return cmd
    
    def _add_data_from_cmdline(self, cmdline):
        """
        Add any data/roi item which match an argument to the working directory
        """
        for arg in re.split(r"\s+|=|,|\n|\t", cmdline):
            if arg in self.ivm.data or arg in self.ivm.rois:
                LOG.debug("Adding data from command line args: %s", arg)
                self.add_data(arg)

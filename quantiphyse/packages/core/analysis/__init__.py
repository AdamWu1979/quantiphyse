from .widgets import SECurve, DataStatistics, RoiAnalysisWidget, SimpleMathsWidget, ModelCurves
from .processes import CalcVolumesProcess, ExecProcess, DataStatisticsProcess, RadialProfileProcess, HistogramProcess
from .tests import DataStatisticsTest, MultiVoxelAnalysisTest, VoxelAnalysisTest
from .process_tests import AnalysisProcessTest

QP_MANIFEST = {
    "widgets" : [SECurve, DataStatistics, RoiAnalysisWidget, SimpleMathsWidget, ModelCurves],
    "widget-tests" : [DataStatisticsTest, MultiVoxelAnalysisTest, VoxelAnalysisTest],
    "process-tests" : [AnalysisProcessTest],
    "processes" : [CalcVolumesProcess, ExecProcess, DataStatisticsProcess, RadialProfileProcess, HistogramProcess],
}

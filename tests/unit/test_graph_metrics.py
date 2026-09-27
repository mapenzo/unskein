from unskein.config import AnalysisConfig
from unskein.graph.metrics import CouplingMetrics
from unskein.pipeline import should_parallelize


def test_instability_bounds() -> None:
    assert CouplingMetrics("core", afferent=5, efferent=0).instability == 0.0
    assert CouplingMetrics("app", afferent=0, efferent=4).instability == 1.0
    assert CouplingMetrics("mid", afferent=1, efferent=3).instability == 0.75


def test_isolated_module_instability_is_zero() -> None:
    assert CouplingMetrics("lonely", afferent=0, efferent=0).instability == 0.0


def test_should_parallelize_uses_threshold() -> None:
    config = AnalysisConfig(parallel_threshold=50)
    assert not should_parallelize(49, config)
    assert should_parallelize(50, config)

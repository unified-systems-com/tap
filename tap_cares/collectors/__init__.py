"""tap_cares collector runtime primitives."""

from tap_cares.collectors.base import CollectorBase
from tap_cares.collectors.config import CollectorConfig
from tap_cares.collectors.readiness import (
    CollectorDocRef,
    CollectorReadinessStatus,
    CollectorSelfTestCheck,
    CollectorSelfTestCheckStatus,
    CollectorSelfTestResult,
    check_fail,
    check_pass,
    check_skip,
    check_warn,
)
from tap_cares.collectors.timeout import CeilingExceeded, run_with_ceiling

__all__ = [
    "CeilingExceeded",
    "CollectorBase",
    "CollectorConfig",
    "CollectorDocRef",
    "CollectorReadinessStatus",
    "CollectorSelfTestCheck",
    "CollectorSelfTestCheckStatus",
    "CollectorSelfTestResult",
    "check_fail",
    "check_pass",
    "check_skip",
    "check_warn",
    "run_with_ceiling",
]

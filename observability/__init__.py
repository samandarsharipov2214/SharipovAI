"""Structured logs, metrics and persistent critical operational alerts."""
from .critical_alerts import (
    AlertCandidate,
    CampaignCriticalAlertMonitor,
    CampaignCriticalAlertService,
)
from .metrics import (
    observe_http,
    record_backtest_failure,
    record_backtest_result,
    record_dataset_validation,
    update_runtime_metrics,
)
from .structured_logging import (
    ContextLoggerAdapter,
    JsonFormatter,
    configure_structured_logging,
    get_structured_logger,
    log_event,
)

__all__ = [
    "AlertCandidate",
    "CampaignCriticalAlertMonitor",
    "CampaignCriticalAlertService",
    "ContextLoggerAdapter",
    "JsonFormatter",
    "configure_structured_logging",
    "get_structured_logger",
    "log_event",
    "observe_http",
    "record_backtest_failure",
    "record_backtest_result",
    "record_dataset_validation",
    "update_runtime_metrics",
]

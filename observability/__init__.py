"""Structured logs, metrics and persistent critical operational alerts."""
from .critical_alerts import CampaignCriticalAlertMonitor, CampaignCriticalAlertService
from .metrics import (
    observe_http,
    record_backtest_failure,
    record_backtest_result,
    record_dataset_validation,
    update_runtime_metrics,
)
from .phase8_alerts import Phase8RiskAlertMonitor, Phase8RiskAlertService
from .structured_logging import (
    ContextLoggerAdapter,
    JsonFormatter,
    configure_structured_logging,
    get_structured_logger,
    log_event,
)

__all__ = [
    "CampaignCriticalAlertMonitor",
    "CampaignCriticalAlertService",
    "ContextLoggerAdapter",
    "JsonFormatter",
    "Phase8RiskAlertMonitor",
    "Phase8RiskAlertService",
    "configure_structured_logging",
    "get_structured_logger",
    "log_event",
    "observe_http",
    "record_backtest_failure",
    "record_backtest_result",
    "record_dataset_validation",
    "update_runtime_metrics",
]

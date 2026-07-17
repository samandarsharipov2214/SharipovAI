"""Authentication dependencies for dashboard routers."""
from .dependencies import AdminPrincipal, admin_principal, require_metrics_access

__all__ = ["AdminPrincipal", "admin_principal", "require_metrics_access"]

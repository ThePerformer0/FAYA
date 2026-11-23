"""Constantes du Jalon 1 (catalogue, dépôts, recherche)."""

API = "/api/v1"
URL_PUBLIC_SETTINGS = f"{API}/settings/public/"
URL_BRANDS = f"{API}/catalog/brands/"
URL_PRODUCTS = f"{API}/catalog/products/"
URL_DEPOTS = f"{API}/depots/"


def url_depot(depot_id):
    return f"{API}/depots/{depot_id}/"


PLATFORM_TIMEZONE = "Africa/Douala"

PUBLIC_SETTINGS_KEYS = {
    "timezone",
    "order_response_timeout_minutes",
    "order_pickup_timeout_minutes",
    "order_cutoff_before_close_minutes",
    "closing_soon_threshold_minutes",
    "max_quantity_per_order",
    "max_active_orders_per_customer",
    "no_show_threshold",
    "no_show_window_days",
    "suspension_duration_days",
    "server_now",
}
PUBLIC_SETTINGS_INT_KEYS = PUBLIC_SETTINGS_KEYS - {"timezone", "server_now"}

# Codes métier
CODE_PROPOSAL_ALREADY_REVIEWED = "PROPOSAL_ALREADY_REVIEWED"
CODE_DEPOT_STATUS_UNCHANGED = "DEPOT_STATUS_UNCHANGED"

# Actions d'audit
AUDIT_PROPOSAL_APPROVED = "PRODUCT_PROPOSAL_APPROVED"
AUDIT_PROPOSAL_REJECTED = "PRODUCT_PROPOSAL_REJECTED"
AUDIT_DEPOT_VALIDATED = "DEPOT_VALIDATED"
AUDIT_DEPOT_SUSPENDED = "DEPOT_SUSPENDED"
AUDIT_DEPOT_DISABLED = "DEPOT_DISABLED"
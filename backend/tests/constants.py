"""Constantes partagées par la suite de tests Faya (Jalon 0).

Les codes d'erreur ci-dessous sont des SUPPOSITIONS : si les `code` réels de
l'API diffèrent, ajustez-les ici (un seul endroit à modifier).
"""

API = "/api/v1"
URL_HEALTH = f"{API}/health/"
URL_REGISTER = f"{API}/auth/register/"
URL_LOGIN = f"{API}/auth/login/"
URL_REFRESH = f"{API}/auth/refresh/"
URL_LOGOUT = f"{API}/auth/logout/"
URL_ME = f"{API}/auth/me/"

REFRESH_COOKIE_PATH = "/api/v1/auth/"

VALID_PASSWORD = "Str0ng!Passw0rd-Faya"

# Format d'erreur unifié : exactement ces trois clés.
ERROR_KEYS = {"code", "message", "details"}

# --- Codes d'erreur attendus (à ajuster, utilisés dans les lots suivants) ---
CODE_VALIDATION = "validation_error"
CODE_AUTHENTICATION = "authentication_failed"
CODE_FORBIDDEN = "forbidden"
CODE_NOT_FOUND = "not_found"
CODE_CONFLICT = "conflict"

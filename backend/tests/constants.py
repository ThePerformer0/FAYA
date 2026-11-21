"""Constantes partagées par la suite de tests Faya (Jalon 0)."""

API = "/api/v1"
URL_HEALTH = f"{API}/health/"
URL_REGISTER = f"{API}/auth/register/"
URL_LOGIN = f"{API}/auth/login/"
URL_REFRESH = f"{API}/auth/refresh/"
URL_LOGOUT = f"{API}/auth/logout/"
URL_ME = f"{API}/auth/me/"

# Nom réel du cookie : toujours lire settings.AUTH_REFRESH_COOKIE_NAME dans les tests.
REFRESH_COOKIE_NAME_FALLBACK = "faya_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth/"

VALID_PASSWORD = "Str0ng!Passw0rd-Faya"

# Un mot de passe par validateur Django actif (min 8, commun, tout numérique).
PASSWORD_TOO_SHORT = "Ab1!xyz"          # 7 caractères
PASSWORD_COMMON = "password"            # dans la liste des mots de passe courants
PASSWORD_ALL_NUMERIC = "7392846150"     # 10 chiffres, non courant

# Format d'erreur unifié : exactement ces trois clés.
ERROR_KEYS = {"code", "message", "details"}

# --------------------------------------------------------------------------
# Codes d'erreur (convention UPPER_SNAKE_CASE)
# --------------------------------------------------------------------------
# Génériques (handler DRF)
CODE_VALIDATION = "VALIDATION_ERROR"            # 400
CODE_UNAUTHENTICATED = "UNAUTHENTICATED"        # 401
CODE_TOKEN_EXPIRED = "TOKEN_EXPIRED"            # 401
CODE_AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"  # 401
CODE_FORBIDDEN = "FORBIDDEN"                    # 403
CODE_NOT_FOUND = "NOT_FOUND"                    # 404
CODE_RATE_LIMITED = "RATE_LIMITED"              # 429
CODE_API_ERROR = "API_ERROR"                    # autres exceptions DRF

# Métier (apps.accounts.services)
CODE_EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"            # 409
CODE_PHONE_ALREADY_EXISTS = "PHONE_ALREADY_EXISTS"            # 409
CODE_ACCOUNT_ALREADY_EXISTS = "ACCOUNT_ALREADY_EXISTS"        # 409
CODE_SUSPENSION_ALREADY_LIFTED = "SUSPENSION_ALREADY_LIFTED"  # 409
CODE_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"              # 401
CODE_ACCOUNT_DISABLED = "ACCOUNT_DISABLED"                    # 401
CODE_REFRESH_TOKEN_MISSING = "REFRESH_TOKEN_MISSING"          # 401
CODE_REFRESH_TOKEN_INVALID = "REFRESH_TOKEN_INVALID"          # 401

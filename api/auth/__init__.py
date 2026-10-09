"""Auth package for EvaliSense."""
from api.auth.security import hash_password, verify_password, create_access_token, decode_access_token
from api.auth.dependencies import (
    get_current_user,
    get_optional_current_user,
    require_roles,
    require_hod,
    require_teacher,
    require_scanner,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_optional_current_user",
    "require_roles",
    "require_hod",
    "require_teacher",
    "require_scanner",
]

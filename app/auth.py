DEFAULT_ROLE = "viewer"
DEFAULT_ACTOR_NAME = "anonymous"

ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "reviewer": {"read", "intake", "raw_lead_write"},
    "sales": {"read", "lead_write"},
    "admin": {"read", "intake", "raw_lead_write", "lead_write"},
}


class AuthorizationError(PermissionError):
    pass


def normalize_actor(role: str | None, name: str | None) -> dict:
    normalized_role = (role or DEFAULT_ROLE).strip().lower()

    if normalized_role not in ROLE_PERMISSIONS:
        raise AuthorizationError(f"Unknown actor role: {normalized_role}")

    normalized_name = (name or DEFAULT_ACTOR_NAME).strip() or DEFAULT_ACTOR_NAME

    return {
        "role": normalized_role,
        "name": normalized_name,
    }


def ensure_permission(role: str | None, permission: str, name: str | None = None) -> dict:
    actor = normalize_actor(role, name)

    if permission not in ROLE_PERMISSIONS[actor["role"]]:
        raise AuthorizationError(
            f"{actor['role']} role cannot perform {permission} actions"
        )

    return actor


def get_role_catalog() -> list[dict]:
    return [
        {
            "role": role,
            "permissions": sorted(list(permissions)),
        }
        for role, permissions in ROLE_PERMISSIONS.items()
    ]

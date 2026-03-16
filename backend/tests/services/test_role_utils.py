from app.utils.roles import is_admin_role, normalize_role, normalize_role_set


def test_normalize_role_is_case_insensitive_and_defaults_to_user() -> None:
    assert normalize_role("ADMIN") == "admin"
    assert normalize_role(" user ") == "user"
    assert normalize_role(None) == "user"
    assert normalize_role("") == "user"


def test_is_admin_role_uses_normalized_role() -> None:
    assert is_admin_role("admin") is True
    assert is_admin_role("AdMiN") is True
    assert is_admin_role("user") is False


def test_normalize_role_set_handles_mixed_input() -> None:
    assert normalize_role_set(["ADMIN", "user", "ADMIN"]) == {"admin", "user"}

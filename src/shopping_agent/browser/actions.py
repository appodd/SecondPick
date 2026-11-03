from __future__ import annotations


FORBIDDEN_ACTIONS = {
    "send_message",
    "purchase",
    "payment",
    "change_account_settings",
    "submit_order",
}


def assert_action_allowed(action: str) -> None:
    if action in FORBIDDEN_ACTIONS:
        raise PermissionError(f"Action is forbidden by project safety policy: {action}")

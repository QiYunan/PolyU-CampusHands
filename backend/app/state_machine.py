"""Server-owned request transitions for the deterministic BorrowLoop flow."""

from app.models import HelpRequest


class StateConflict(ValueError):
    pass


ALLOWED: dict[str, set[str]] = {
    "draft": {"searching", "cancelled", "expired"},
    "searching": {"awaiting_response", "failed", "cancelled", "expired"},
    "awaiting_response": {"searching", "matched", "cancelled", "expired"},
    "matched": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
    "expired": set(),
    "failed": set(),
}


def transition(request: HelpRequest, target: str) -> None:
    if target not in ALLOWED.get(request.status, set()):
        raise StateConflict(f"Cannot change request from {request.status} to {target}")
    request.status = target

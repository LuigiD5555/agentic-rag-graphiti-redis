from typing import Any, Dict, List, Optional

def can_read(user_id: Optional[str], payload: Dict[str, Any]) -> bool:
    """
    Minimal ABAC rule for read access.
    - If payload['visibility'] == 'public' -> allow
    - If user_id is not None and equals payload['owner_id'] -> allow
    - If user_id is in payload['allowed_user_ids'] -> allow
    Otherwise deny.
    """
    if not isinstance(payload, dict):
        return False
    visibility = payload.get("visibility", "private")
    if visibility == "public":
        return True
    owner_id = payload.get("owner_id")
    if user_id is not None and owner_id and user_id == owner_id:
        return True
    allowed: List[str] = payload.get("allowed_user_ids") or []
    if user_id and user_id in allowed:
        return True
    return False

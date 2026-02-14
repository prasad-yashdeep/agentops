"""
Business logic handler for the target app.
This file gets modified by fault injection and fixed by the agent.
"""

USERS_DB = [
    {"id": 1, "name": "Alice Chen", "role": "engineer", "active": True},
    {"id": 2, "name": "Bob Smith", "role": "designer", "active": True},
    {"id": 3, "name": "Carol Williams", "role": "manager", "active": True},
    {"id": 4, "name": "Dave Johnson", "role": "engineer", "active": False},
]


def validate():
    """Health check validation — ensures handler module loads correctly."""
    return True


def get_users():
    """Return list of active users."""
    return [u for u in USERS_DB if u["active"]]


def compute_stats():
    """Compute user statistics."""
    total = len(USERS_DB)
    active = len([u for u in USERS_DB if u["active"]])
    roles = {}
    for u in USERS_DB:
        roles[u["role"]] = roles.get(u["role"], 0) + 1
    return {
        "total_users": total,
        "active_users": active,
        "inactive_users": total - active,
        "by_role": roles,
    }


def process_data(data):
    """Process incoming data."""
    value = data.get("value", 0)
    operation = data.get("operation", "double")

    if operation == "double":
        return value * 2
    elif operation == "square":
        return value ** 2
    elif operation == "factorial":
        result = 1
        for i in range(1, int(value) + 1):
            result *= i
        return result
    else:
        return value

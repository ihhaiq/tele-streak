from __future__ import annotations

# MVP ships with one cleanly editable pose (Jake holding a flag).
# The architecture already treats pose selection separately so more poses can be added later.
DEFAULT_POSE = "pose_flag.png"
MILESTONE_POSE = "pose_flag.png"


def choose_pose(days: int, last_pose: str | None = None) -> str:
    return MILESTONE_POSE if days in {7, 30, 50, 100, 150, 200, 365, 500, 1000} else DEFAULT_POSE

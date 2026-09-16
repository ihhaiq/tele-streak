from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MILESTONES = frozenset({7, 14, 30, 50, 69, 100, 150, 200, 365, 500, 1000})
VALID_CATEGORIES = frozenset({"normal", "waiting", "milestone", "rare", "broken"})


@dataclass(frozen=True, slots=True)
class Pose:
    id: str
    image: Path
    category: str
    number_box: tuple[float, float, float, float]
    font_size: int = 120
    rotation: float = 0
    weight: float = 1.0
    max_digits: int = 5
    text_color: str = "#172b3a"
    outline_color: str = "#fff8e8"
    outline_width: int = 2
    milestones: frozenset[int] = frozenset()


class PoseCatalog:
    """Loads pose definitions from JSON; adding art never requires Python edits."""

    def __init__(self, assets_dir: Path, *, rng: random.Random | None = None):
        self.assets_dir = Path(assets_dir)
        self.rng = rng
        self._poses = self._load()

    def _load(self) -> tuple[Pose, ...]:
        poses: list[Pose] = []
        seen: set[str] = set()
        for metadata_path in sorted(self.assets_dir.rglob("*.json")):
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            pose_id = str(raw["id"])
            if pose_id in seen:
                raise ValueError(f"Duplicate pose id: {pose_id}")
            category = str(raw.get("category", "normal"))
            if category not in VALID_CATEGORIES:
                raise ValueError(f"Invalid category for {pose_id}: {category}")
            image = metadata_path.parent / str(raw.get("image", f"{pose_id}.png"))
            if not image.is_file():
                raise FileNotFoundError(f"Missing image for pose {pose_id}: {image}")
            box = tuple(float(value) for value in raw["number_box"])
            if len(box) != 4 or any(value < 0 or value > 1 for value in box):
                raise ValueError(f"number_box for {pose_id} must contain four values from 0 to 1")
            weight = float(raw.get("weight", 1.0))
            if weight <= 0:
                raise ValueError(f"weight for {pose_id} must be positive")
            poses.append(Pose(
                id=pose_id,
                image=image,
                category=category,
                number_box=box,
                font_size=int(raw.get("font_size", 120)),
                rotation=float(raw.get("rotation", 0)),
                weight=weight,
                max_digits=int(raw.get("max_digits", 5)),
                text_color=str(raw.get("text_color", "#172b3a")),
                outline_color=str(raw.get("outline_color", "#fff8e8")),
                outline_width=int(raw.get("outline_width", 2)),
                milestones=frozenset(int(value) for value in raw.get("milestones", [])),
            ))
            seen.add(pose_id)
        if not poses:
            raise RuntimeError(f"No pose metadata found under {self.assets_dir}")
        return tuple(poses)

    def get(self, pose_id: str) -> Pose:
        for pose in self._poses:
            if pose.id == pose_id:
                return pose
        raise KeyError(f"Unknown pose: {pose_id}")

    def _eligible(self, days: int) -> Iterable[Pose]:
        exact = [pose for pose in self._poses if days in pose.milestones]
        if exact:
            return exact
        if days in MILESTONES:
            milestone = [pose for pose in self._poses if pose.category == "milestone"]
            if milestone:
                return milestone
        normal = [pose for pose in self._poses if pose.category == "normal"]
        return normal or self._poses

    def choose(self, days: int, last_pose: str | None = None) -> Pose:
        candidates = list(self._eligible(days))
        alternatives = [pose for pose in candidates if pose.id != last_pose]
        if alternatives:
            candidates = alternatives
        rng = self.rng
        if rng is None:
            signature = ",".join(sorted(pose.id for pose in candidates))
            seed = int.from_bytes(
                hashlib.sha256(f"{days}:{last_pose or ''}:{signature}".encode()).digest()[:8],
                "big",
            )
            rng = random.Random(seed)
        return rng.choices(candidates, weights=[pose.weight for pose in candidates], k=1)[0]

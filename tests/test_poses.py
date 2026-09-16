import json
import random

import pytest
from PIL import Image

from app.stickers.poses import PoseCatalog


def add_pose(root, pose_id, category="normal", weight=1.0, milestones=None):
    folder = root / category
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32)).save(folder / f"{pose_id}.png")
    (folder / f"{pose_id}.json").write_text(json.dumps({
        "id": pose_id,
        "image": f"{pose_id}.png",
        "category": category,
        "number_box": [0.1, 0.1, 0.9, 0.9],
        "weight": weight,
        "milestones": milestones or [],
    }), encoding="utf-8")


def test_does_not_repeat_when_an_alternative_exists(tmp_path):
    add_pose(tmp_path, "hug")
    add_pose(tmp_path, "sit")
    catalog = PoseCatalog(tmp_path, rng=random.Random(1))
    assert catalog.choose(2, last_pose="hug").id == "sit"


def test_exact_milestone_pose_wins(tmp_path):
    add_pose(tmp_path, "normal")
    add_pose(tmp_path, "seven", category="milestone", milestones=[7])
    catalog = PoseCatalog(tmp_path, rng=random.Random(1))
    assert catalog.choose(7).id == "seven"


def test_rejects_missing_image(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({
        "id": "bad", "category": "normal", "number_box": [0, 0, 1, 1]
    }), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        PoseCatalog(tmp_path)

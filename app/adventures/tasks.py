from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ROLES = ("owner", "peer")
MEDIA_KINDS = ("photo", "video", "voice")
ALL_KINDS = ("text", *MEDIA_KINDS)
TASKS_PER_SLOT = 6
SLOT_HOURS = 6
ALL_TASKS_BONUS_XP = 20


@dataclass(frozen=True, slots=True)
class TaskSpec:
    key: str
    label: str
    xp: int
    family: str
    rule: str
    role: str | None = None
    target: int = 0
    kind: str | None = None
    other_kind: str | None = None
    other_target: int = 0


def _role_name(role: str) -> str:
    return "الطرف الأول" if role == "owner" else "الطرف الثاني"


def _kind_name(kind: str) -> str:
    return {
        "text": "رسالة نصية",
        "photo": "صورة",
        "video": "فيديو",
        "voice": "بصمة",
    }[kind]


def _build_catalog() -> dict[str, TaskSpec]:
    specs: list[TaskSpec] = []

    def add(
        key: str,
        label: str,
        xp: int,
        family: str,
        rule: str,
        *,
        role: str | None = None,
        target: int = 0,
        kind: str | None = None,
        other_kind: str | None = None,
        other_target: int = 0,
    ) -> None:
        specs.append(
            TaskSpec(
                key=key,
                label=label,
                xp=xp,
                family=family,
                rule=rule,
                role=role,
                target=target,
                kind=kind,
                other_kind=other_kind,
                other_target=other_target,
            )
        )

    # عدد الرسائل لكل طرف.
    for role in ROLES:
        for target in range(1, 9):
            add(
                f"{role}_messages_{target}",
                f"{_role_name(role)} يرسل {target} رسالة",
                8 + target * 2 + (1 if role == "peer" else 0),
                "role_messages",
                "role_messages",
                role=role,
                target=target,
            )

    # مجموع كلمات كل طرف.
    word_targets = (3, 5, 8, 12, 16, 20, 25, 30, 40, 50, 60, 75, 90, 110, 130)
    for role in ROLES:
        for index, target in enumerate(word_targets):
            add(
                f"{role}_words_{target}",
                f"{_role_name(role)} يكتب {target} كلمة بالمجموع",
                10 + index + (2 if role == "peer" else 0),
                "role_words",
                "role_words",
                role=role,
                target=target,
            )

    # رسالة واحدة طويلة.
    single_word_targets = (3, 5, 8, 10, 12, 15, 20, 25, 30, 40)
    for role in ROLES:
        for index, target in enumerate(single_word_targets):
            add(
                f"{role}_single_words_{target}",
                f"{_role_name(role)} يرسل رسالة بيها {target}+ كلمة",
                11 + index * 2 + (1 if role == "peer" else 0),
                "single_words",
                "single_words",
                role=role,
                target=target,
            )

    # عدد الرسائل النصية.
    for role in ROLES:
        for target in range(1, 9):
            add(
                f"{role}_texts_{target}",
                f"{_role_name(role)} يرسل {target} رسالة نصية",
                9 + target * 2 + (1 if role == "peer" else 0),
                "role_texts",
                "role_kind",
                role=role,
                kind="text",
                target=target,
            )

    # وسائط لكل طرف.
    for role in ROLES:
        for kind in MEDIA_KINDS:
            for target in range(1, 6):
                add(
                    f"{role}_{kind}_{target}",
                    f"{_role_name(role)} يرسل {target} {_kind_name(kind)}",
                    13 + target * 3 + MEDIA_KINDS.index(kind) * 2 + (1 if role == "peer" else 0),
                    "role_media",
                    "role_kind",
                    role=role,
                    kind=kind,
                    target=target,
                )

    # كل الرسائل/الكلمات للطرفين مجتمعين.
    for target in range(2, 17):
        add(
            f"total_messages_{target}",
            f"ترسلون {target} رسالة بالمجموع",
            9 + target,
            "total_messages",
            "total_messages",
            target=target,
        )
    total_word_targets = (
        6, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80, 90,
        100, 115, 130, 145, 160, 180, 200, 225, 250, 275, 300, 350,
    )
    for index, target in enumerate(total_word_targets):
        add(
            f"total_words_{target}",
            f"تكتبون {target} كلمة بالمجموع",
            10 + index,
            "total_words",
            "total_words",
            target=target,
        )

    # كلا الطرفين يحققان نفس الحد.
    for target in range(1, 9):
        add(
            f"both_messages_{target}",
            f"كل واحد يرسل {target} رسالة",
            14 + target * 2,
            "both_messages",
            "both_messages",
            target=target,
        )
        add(
            f"both_texts_{target}",
            f"كل واحد يرسل {target} رسالة نصية",
            15 + target * 2,
            "both_texts",
            "both_kind",
            kind="text",
            target=target,
        )
    both_word_targets = (3, 5, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60)
    for index, target in enumerate(both_word_targets):
        add(
            f"both_words_{target}",
            f"كل واحد يكتب {target} كلمة بالمجموع",
            16 + index * 2,
            "both_words",
            "both_words",
            target=target,
        )

    # كلا الطرفين يرسلان نفس نوع الوسائط.
    for kind in MEDIA_KINDS:
        for target in range(1, 5):
            add(
                f"both_{kind}_{target}",
                f"كل واحد يرسل {target} {_kind_name(kind)}",
                18 + target * 3 + MEDIA_KINDS.index(kind) * 2,
                "both_media",
                "both_kind",
                kind=kind,
                target=target,
            )

    # مجموع نوع محدد بين الطرفين.
    for kind in MEDIA_KINDS:
        for target in range(1, 9):
            add(
                f"total_{kind}_{target}",
                f"ترسلون {target} {_kind_name(kind)} بالمجموع",
                12 + target * 2 + MEDIA_KINDS.index(kind),
                "total_media",
                "total_kind",
                kind=kind,
                target=target,
            )

    # كل طرف يرسل نوعًا مختلفًا؛ 16 تركيبة.
    for owner_kind in ALL_KINDS:
        for peer_kind in ALL_KINDS:
            add(
                f"pair_{owner_kind}_{peer_kind}",
                f"الأول {_kind_name(owner_kind)} · الثاني {_kind_name(peer_kind)}",
                18 + ALL_KINDS.index(owner_kind) * 2 + ALL_KINDS.index(peer_kind),
                "pair_kind",
                "pair_kind",
                kind=owner_kind,
                other_kind=peer_kind,
                target=1,
            )

    # وسائط + كلمات لنفس الطرف.
    combo_word_targets = (3, 5, 8, 12, 16, 20, 25, 30)
    for role in ROLES:
        for kind in MEDIA_KINDS:
            for index, target in enumerate(combo_word_targets):
                add(
                    f"{role}_{kind}_and_words_{target}",
                    f"{_role_name(role)} يرسل {_kind_name(kind)} ويكتب {target} كلمة",
                    18 + index * 2 + MEDIA_KINDS.index(kind) + (1 if role == "peer" else 0),
                    "media_words",
                    "role_kind_and_words",
                    role=role,
                    kind=kind,
                    target=target,
                )

    # تنوع أنواع المشاركة داخل نفس الفترة.
    for role in ROLES:
        for target in (2, 3, 4):
            add(
                f"{role}_kinds_{target}",
                f"{_role_name(role)} يستخدم {target} أنواع مشاركة",
                20 + target * 4 + (1 if role == "peer" else 0),
                "role_variety",
                "role_variety",
                role=role,
                target=target,
            )
    for target in (2, 3, 4):
        add(
            f"total_kinds_{target}",
            f"تستخدمون {target} أنواع مشاركة",
            18 + target * 4,
            "total_variety",
            "total_variety",
            target=target,
        )

    # من يبدأ الفترة.
    for role in ROLES:
        add(
            f"{role}_starts_slot",
            f"{_role_name(role)} يبدأ هالفترة",
            14 + (1 if role == "peer" else 0),
            "starter",
            "starter",
            role=role,
        )

    # سرعة أول مشاركة بين الطرفين.
    gap_targets = (30, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200, 1800)
    for index, target in enumerate(gap_targets):
        minutes = target // 60
        label = (
            f"تردون على بعض خلال {target} ثانية"
            if target < 60
            else f"تردون على بعض خلال {minutes} دقيقة أو أقل"
        )
        add(
            f"gap_{target}",
            label,
            30 - min(index, 10),
            "speed",
            "first_gap",
            target=target,
        )

    # أهداف غير متساوية حتى يكون عندنا تنوع أكبر من مجرد نسخ نفس المهمة.
    for owner_target in range(1, 5):
        for peer_target in range(1, 5):
            add(
                f"split_messages_{owner_target}_{peer_target}",
                f"الأول {owner_target} رسالة · الثاني {peer_target} رسالة",
                13 + owner_target * 2 + peer_target,
                "split_messages",
                "split_messages",
                target=owner_target,
                other_target=peer_target,
            )

    catalog = {spec.key: spec for spec in specs}
    if len(catalog) <= 300:
        raise RuntimeError("task catalog must contain more than 300 tasks")
    return catalog


TASK_CATALOG = _build_catalog()


def task_slot(at: datetime) -> str:
    return f"{at.date().isoformat()}:{at.hour // SLOT_HOURS}"


def empty_slot_stats() -> dict[str, Any]:
    def role() -> dict[str, Any]:
        return {
            "messages": 0,
            "text": 0,
            "photo": 0,
            "video": 0,
            "voice": 0,
            "words": 0,
            "max_words": 0,
        }

    return {
        "owner": role(),
        "peer": role(),
        "first": {},
        "last": {},
        "best_gap": None,
    }


def choose_tasks(rng=None, count: int = TASKS_PER_SLOT) -> list[str]:
    rng = rng or random.SystemRandom()
    candidates = list(TASK_CATALOG.values())
    rng.shuffle(candidates)

    selected: list[TaskSpec] = []
    used_xp: set[int] = set()
    family_counts: dict[str, int] = {}

    for spec in candidates:
        if spec.xp in used_xp:
            continue
        family_limit = 1 if spec.family in {"starter", "speed"} else 2
        if family_counts.get(spec.family, 0) >= family_limit:
            continue
        selected.append(spec)
        used_xp.add(spec.xp)
        family_counts[spec.family] = family_counts.get(spec.family, 0) + 1
        if len(selected) == count:
            return [item.key for item in selected]

    raise RuntimeError("not enough diverse tasks with unique XP values")


def ensure_task_slot(state: dict, at: datetime, rng=None) -> bool:
    slot = task_slot(at)
    if state.get("task_slot") == slot and state.get("tasks"):
        state.setdefault("slot_stats", empty_slot_stats())
        state.setdefault("done", [])
        state.setdefault("all_bonus", False)
        return False

    state["task_slot"] = slot
    state["tasks"] = choose_tasks(rng, TASKS_PER_SLOT)
    state["done"] = []
    state["all_bonus"] = False
    state["slot_stats"] = empty_slot_stats()
    state["pending"] = []
    return True


def record_task_activity(state: dict, activity) -> None:
    stats = state.setdefault("slot_stats", empty_slot_stats())
    role = stats[activity.role]
    role["messages"] += 1
    role["words"] += max(0, int(activity.words))
    role["max_words"] = max(role["max_words"], max(0, int(activity.words)))

    kind = activity.kind if activity.kind in MEDIA_KINDS else "text" if activity.words > 0 else None
    if kind is not None:
        role[kind] += 1

    timestamp = activity.at.timestamp()
    first = stats["first"]
    if activity.role not in first:
        first[activity.role] = timestamp

    other_role = "peer" if activity.role == "owner" else "owner"
    last = stats["last"]
    if other_role in last:
        gap = abs(timestamp - float(last[other_role]))
        current = stats.get("best_gap")
        stats["best_gap"] = gap if current is None else min(float(current), gap)
    last[activity.role] = timestamp


def _count(role_stats: dict[str, Any], kind: str) -> int:
    return int(role_stats.get(kind, 0))


def is_task_done(spec: TaskSpec, state: dict) -> bool:
    stats = state.get("slot_stats") or empty_slot_stats()
    owner = stats["owner"]
    peer = stats["peer"]
    first = stats["first"]

    if spec.rule == "role_messages":
        return int(stats[spec.role]["messages"]) >= spec.target
    if spec.rule == "role_words":
        return int(stats[spec.role]["words"]) >= spec.target
    if spec.rule == "single_words":
        return int(stats[spec.role]["max_words"]) >= spec.target
    if spec.rule == "role_kind":
        return _count(stats[spec.role], spec.kind) >= spec.target
    if spec.rule == "total_messages":
        return int(owner["messages"]) + int(peer["messages"]) >= spec.target
    if spec.rule == "total_words":
        return int(owner["words"]) + int(peer["words"]) >= spec.target
    if spec.rule == "both_messages":
        return min(int(owner["messages"]), int(peer["messages"])) >= spec.target
    if spec.rule == "both_words":
        return min(int(owner["words"]), int(peer["words"])) >= spec.target
    if spec.rule == "both_kind":
        return min(_count(owner, spec.kind), _count(peer, spec.kind)) >= spec.target
    if spec.rule == "total_kind":
        return _count(owner, spec.kind) + _count(peer, spec.kind) >= spec.target
    if spec.rule == "pair_kind":
        return _count(owner, spec.kind) >= 1 and _count(peer, spec.other_kind) >= 1
    if spec.rule == "role_kind_and_words":
        role = stats[spec.role]
        return _count(role, spec.kind) >= 1 and int(role["words"]) >= spec.target
    if spec.rule == "role_variety":
        role = stats[spec.role]
        kinds = sum(int(role[kind]) > 0 for kind in ALL_KINDS)
        return kinds >= spec.target
    if spec.rule == "total_variety":
        kinds = sum(
            _count(owner, kind) + _count(peer, kind) > 0
            for kind in ALL_KINDS
        )
        return kinds >= spec.target
    if spec.rule == "starter":
        if not first:
            return False
        return min(first, key=first.get) == spec.role
    if spec.rule == "first_gap":
        best_gap = stats.get("best_gap")
        return best_gap is not None and float(best_gap) <= spec.target
    if spec.rule == "split_messages":
        return (
            int(owner["messages"]) >= spec.target
            and int(peer["messages"]) >= spec.other_target
        )
    return False


def task_spec(key: str) -> TaskSpec:
    return TASK_CATALOG[key]


def active_task_specs(state: dict) -> list[TaskSpec]:
    return [TASK_CATALOG[key] for key in state.get("tasks", ()) if key in TASK_CATALOG]

RELAXATION_ORDER = ["language", "position", "vip"]


def filter_by_skill(ticket: dict, managers: list[dict]) -> list[dict]:
    segment = ticket.get("segment", "Mass")
    ticket_type = ticket.get("type", "Консультация")
    language_label = ticket.get("language_label", "RU")

    requirements = []

    if segment in ("VIP", "Priority"):
        requirements.append("vip")

    if ticket_type == "Смена данных":
        requirements.append("position")

    if language_label in ("KZ", "ENG"):
        requirements.append("language")

    eligible = _apply_filters(managers, requirements, segment, ticket_type, language_label)

    if eligible:
        ticket["_skill_relaxation"] = None
        return eligible

    relaxed = []
    for drop in RELAXATION_ORDER:
        if drop not in requirements:
            continue
        reduced = [r for r in requirements if r != drop]
        eligible = _apply_filters(managers, reduced, segment, ticket_type, language_label)
        if eligible:
            relaxed.append(drop)
            ticket["_skill_relaxation"] = f"Снято требование: {_relaxation_label(drop)}"
            return eligible

    for i in range(len(RELAXATION_ORDER)):
        for j in range(i + 1, len(RELAXATION_ORDER)):
            drops = {RELAXATION_ORDER[i], RELAXATION_ORDER[j]}
            reduced = [r for r in requirements if r not in drops]
            eligible = _apply_filters(managers, reduced, segment, ticket_type, language_label)
            if eligible:
                labels = ", ".join(_relaxation_label(d) for d in drops)
                ticket["_skill_relaxation"] = f"Сняты требования: {labels}"
                return eligible

    ticket["_skill_relaxation"] = "Все требования сняты, подходящих менеджеров нет"
    return managers if managers else []


def _apply_filters(
    managers: list[dict],
    requirements: list[str],
    segment: str,
    ticket_type: str,
    language_label: str,
) -> list[dict]:
    result = managers

    if "vip" in requirements:
        result = [m for m in result if "VIP" in (m.get("skills") or [])]

    if "position" in requirements:
        result = [m for m in result if m.get("position") == "Глав спец"]

    if "language" in requirements:
        result = [m for m in result if language_label in (m.get("skills") or [])]

    return result


def _relaxation_label(req: str) -> str:
    return {
        "language": "язык (KZ/ENG)",
        "position": "должность (Глав спец)",
        "vip": "навык VIP",
    }.get(req, req)
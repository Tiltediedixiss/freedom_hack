from app.models.schemas import TicketType, PriorityBreakdown
from app.services.geo import filter_by_geo
from app.services.skills import filter_by_skill

DIFFICULTY = {
    "Жалоба": 1.2,
    "Смена данных": 1.3,
    "Консультация": 1.0,
    "Претензия": 1.1,
    "Неработоспособность приложения": 1.15,
    "Мошеннические действия": 1.5,
    "Спам": None,
}

DEFAULT_DIFFICULTY = 1.15


def init_manager_loads(managers: list[dict]) -> dict[int, float]:
    loads = {}
    for m in managers:
        csv_count = m.get("csv_load", 0) or 0
        loads[m["id"]] = csv_count * DEFAULT_DIFFICULTY
    return loads


def route_batch(
    tickets: list[dict],
    managers: list[dict],
) -> list[dict]:

    sorted_tickets = sorted(
        tickets,
        key=lambda t: t["priority"].final if isinstance(t["priority"], PriorityBreakdown) else t["priority"]["final"],
        reverse=True,
    )

    loads = init_manager_loads(managers)
    assignments = []

    for ticket in sorted_tickets:
        ticket_type = ticket.get("type", "Консультация")
        difficulty = DIFFICULTY.get(ticket_type)

        if difficulty is None:
            assignments.append({
                "ticket_id": ticket["ticket_id"],
                "csv_row_index": ticket["csv_row_index"],
                "manager_id": None,
                "manager_name": None,
                "office": None,
                "explanation": f"Тикет типа '{ticket_type}' пропущен при маршрутизации (спам).",
                "skipped": True,
            })
            continue

        eligible = filter_by_geo(ticket, managers)
        eligible = filter_by_skill(ticket, eligible)

        if not eligible:
            assignments.append({
                "ticket_id": ticket["ticket_id"],
                "csv_row_index": ticket["csv_row_index"],
                "manager_id": None,
                "manager_name": None,
                "office": None,
                "explanation": "Не найден подходящий менеджер после фильтрации по гео и навыкам.",
                "skipped": False,
            })
            continue

        best = min(eligible, key=lambda m: loads.get(m["id"], 0))

        loads[best["id"]] = loads.get(best["id"], 0) + difficulty

        priority = ticket["priority"]
        if isinstance(priority, PriorityBreakdown):
            p_final = priority.final
            p_breakdown = priority.model_dump()
        else:
            p_final = priority["final"]
            p_breakdown = priority

        explanation = (
            f"Назначен менеджеру {best['full_name']} ({best['position']}, {best.get('office', '?')}). "
            f"Приоритет тикета: {p_final}. "
            f"Тип: {ticket_type} (сложность {difficulty}). "
            f"Нагрузка менеджера после назначения: {loads[best['id']]:.2f}."
        )

        assignments.append({
            "ticket_id": ticket["ticket_id"],
            "csv_row_index": ticket["csv_row_index"],
            "manager_id": best["id"],
            "manager_name": best["full_name"],
            "office": best.get("office"),
            "difficulty": difficulty,
            "manager_load_after": loads[best["id"]],
            "priority_final": p_final,
            "priority_breakdown": p_breakdown,
            "explanation": explanation,
            "skipped": False,
        })

    return assignments


def get_manager_loads(managers: list[dict], assignments: list[dict]) -> list[dict]:
    loads = init_manager_loads(managers)
    for a in assignments:
        if a.get("manager_id") and a.get("difficulty"):
            loads[a["manager_id"]] = loads.get(a["manager_id"], 0) + a["difficulty"]
    return [
        {
            "id": m["id"],
            "full_name": m["full_name"],
            "position": m["position"],
            "office": m.get("office"),
            "load": loads.get(m["id"], 0),
        }
        for m in managers
    ]
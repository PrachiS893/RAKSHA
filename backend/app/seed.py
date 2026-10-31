"""Database seeding script for populating Raksha demo data."""

from sqlmodel import Session, delete, select
from app.config import settings
from app.db import create_db_and_tables, engine
from app.demo_data import DEMO_REGIONS, DEMO_SUBSCRIPTIONS, DEMO_WAREHOUSES
from app.models import (
    AgentLog,
    Alert,
    Assignment,
    Delivery,
    Inventory,
    Region,
    Request,
    SimulationState,
    Subscription,
    Warehouse,
)


def seed_database(session: Session) -> dict[str, int]:
    """Clear all tables in FK-safe order and insert initial simulated demo data.

    Returns a dictionary of row counts for all tables.
    """
    # Clear tables in foreign-key safe order
    session.exec(delete(Delivery))
    session.exec(delete(Assignment))
    session.exec(delete(Alert))
    session.exec(delete(Request))
    session.exec(delete(Subscription))
    session.exec(delete(Inventory))
    session.exec(delete(AgentLog))
    session.exec(delete(SimulationState))
    session.exec(delete(Warehouse))
    session.exec(delete(Region))
    session.commit()

    # 1. Insert Regions
    region_map: dict[str, int] = {}
    for r_data in DEMO_REGIONS:
        region = Region(
            name=r_data["name"],
            polygon=r_data["polygon"],
            center_lat=r_data["center_lat"],
            center_lon=r_data["center_lon"],
            vulnerability=r_data["vulnerability"],
            risk_level=r_data["risk_level"],
            rainfall_mm=r_data["rainfall_mm"],
            is_flooded=False,
            is_simulated_flood=r_data["is_simulated_flood"],
        )
        session.add(region)
        session.flush()
        if region.id is not None:
            region_map[region.name] = region.id

    # 2. Insert Warehouses and their Inventories
    for w_data in DEMO_WAREHOUSES:
        warehouse = Warehouse(
            name=w_data["name"],
            lat=w_data["lat"],
            lon=w_data["lon"],
        )
        session.add(warehouse)
        session.flush()
        if warehouse.id is not None:
            for inv_data in w_data["inventory"]:
                inv = Inventory(
                    warehouse_id=warehouse.id,
                    resource=inv_data["resource"],
                    quantity=inv_data["quantity"],
                    initial_quantity=inv_data["initial_quantity"],
                )
                session.add(inv)

    # 3. Insert Subscriptions
    for s_data in DEMO_SUBSCRIPTIONS:
        reg_id = region_map[s_data["region_name"]]
        chat_id = s_data["telegram_chat_id"]
        if s_data["name"] == "Demo Citizen 1" and settings.DEMO_TELEGRAM_CHAT_ID:
            chat_id = settings.DEMO_TELEGRAM_CHAT_ID
        sub = Subscription(
            region_id=reg_id,
            name=s_data["name"],
            telegram_chat_id=chat_id,
        )
        session.add(sub)

    # 4. Insert initial SimulationState (stage 1)
    sim_state = SimulationState(id=1, stage=1)
    session.add(sim_state)

    session.commit()

    # Calculate row counts
    counts = {
        "regions": len(session.exec(select(Region)).all()),
        "warehouses": len(session.exec(select(Warehouse)).all()),
        "inventory": len(session.exec(select(Inventory)).all()),
        "subscriptions": len(session.exec(select(Subscription)).all()),
        "requests": len(session.exec(select(Request)).all()),
        "assignments": len(session.exec(select(Assignment)).all()),
        "alerts": len(session.exec(select(Alert)).all()),
        "deliveries": len(session.exec(select(Delivery)).all()),
        "agent_logs": len(session.exec(select(AgentLog)).all()),
        "simulation_state": len(session.exec(select(SimulationState)).all()),
    }
    return counts


if __name__ == "__main__":
    create_db_and_tables()
    with Session(engine) as session:
        table_counts = seed_database(session)
        print("Database seeded successfully:")
        for table_name, count in table_counts.items():
            print(f"  {table_name}: {count} rows")

"""Database seeding script for populating Raksha demo data."""

import logging
from shapely.geometry import Point, Polygon
from sqlmodel import Session, delete, select
from app.config import settings
from app.db import create_db_and_tables, engine
from app.demo_data import DEMO_REGIONS, DEMO_SUBSCRIPTIONS, DEMO_WAREHOUSES, HAZARD_ZONES
from app.models import (
    AgentLog,
    Alert,
    Assignment,
    Delivery,
    HazardZone,
    Inventory,
    Region,
    Request,
    SimulationState,
    Subscription,
    Warehouse,
)


logger = logging.getLogger(__name__)


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
    session.exec(delete(HazardZone))
    session.exec(delete(Region))
    session.commit()

    # 1. Insert Regions (center computed dynamically via Shapely centroid)
    region_map: dict[str, int] = {}
    region_polys: list[tuple[str, Polygon]] = []
    for r_data in DEMO_REGIONS:
        poly_coords = r_data["polygon"]["coordinates"][0]
        poly = Polygon(poly_coords)
        centroid = poly.centroid
        center_lat = round(float(centroid.y), 6)
        center_lon = round(float(centroid.x), 6)

        region = Region(
            name=r_data["name"],
            polygon=r_data["polygon"],
            center_lat=center_lat,
            center_lon=center_lon,
            vulnerability=r_data["vulnerability"],
            risk_level=r_data["risk_level"],
            rainfall_mm=r_data["rainfall_mm"],
            is_flooded=False,
            is_simulated_flood=r_data["is_simulated_flood"],
            households_estimate=r_data.get("households_estimate", 0),
        )
        session.add(region)
        session.flush()
        if region.id is not None:
            region_map[region.name] = region.id
            region_polys.append((region.name, poly))

    # 2. Insert Warehouses and their Inventories
    for w_data in DEMO_WAREHOUSES:
        warehouse = Warehouse(
            name=w_data["name"],
            lat=w_data["lat"],
            lon=w_data["lon"],
        )
        session.add(warehouse)
        session.flush()

        # Check containing zone for warehouse and print/log INFO line
        w_pt = Point(w_data["lon"], w_data["lat"])
        containing_zones = [r_name for r_name, r_poly in region_polys if r_poly.contains(w_pt)]
        zone_info = containing_zones[0] if containing_zones else "outside"
        logger.info("Warehouse %s is in %s", warehouse.name, zone_info)
        print(f"INFO: {warehouse.name} is in {zone_info}")

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

    # 5. Insert Hazard Zones (initially inactive)
    for h_data in HAZARD_ZONES:
        hazard = HazardZone(
            name=h_data["name"],
            description=h_data["description"],
            polygon=h_data["polygon"],
            active=False,
            simulated=h_data.get("simulated", True),
        )
        session.add(hazard)

    session.commit()

    # Calculate row counts
    counts = {
        "regions": len(session.exec(select(Region)).all()),
        "hazard_zones": len(session.exec(select(HazardZone)).all()),
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

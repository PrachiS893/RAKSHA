"""Router for relief distribution warehouses."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.constants import RESOURCE_UNITS
from app.db import get_session
from app.models import Inventory, Warehouse
from app.schemas import InventoryItemRead, WarehouseRead

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


@router.get(
    "",
    response_model=list[WarehouseRead],
    summary="List all warehouses with current stockpile inventories",
)
def list_warehouses(session: Session = Depends(get_session)) -> list[WarehouseRead]:
    """Retrieve all warehouses alongside their current resource inventory levels."""
    warehouses = session.exec(select(Warehouse)).all()
    results: list[WarehouseRead] = []

    for w in warehouses:
        inventories = session.exec(
            select(Inventory).where(Inventory.warehouse_id == w.id)
        ).all()
        inv_items = [
            InventoryItemRead(
                resource=inv.resource,
                unit=RESOURCE_UNITS.get(inv.resource, "units"),
                quantity=inv.quantity,
                initial_quantity=inv.initial_quantity,
            )
            for inv in inventories
        ]
        results.append(
            WarehouseRead(
                id=w.id,
                name=w.name,
                lat=w.lat,
                lon=w.lon,
                inventory=inv_items,
                simulated=True,
            )
        )

    return results

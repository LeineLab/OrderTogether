import csv
import io
from collections import defaultdict
from typing import Literal

from starlette.responses import StreamingResponse

from app.models import Order, OrderItem


def _csv_stream(rows: list[dict], fieldnames: list[str]):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
        yield buf.getvalue()
        buf.truncate(0)
        buf.seek(0)


def export_csv(
    order: Order,
    items: list[OrderItem],
    group: Literal["person", "product"] = "person",
) -> StreamingResponse:
    filename = f"order-{order.id[:8]}-{group}.csv"

    if group == "person":
        rows = []
        for item in sorted(items, key=lambda i: i.person_name):
            rows.append(
                {
                    "person": item.person_name,
                    "product": item.product_name,
                    "sku": item.product_sku or "",
                    "quantity": item.quantity,
                    "note": item.note or "",
                    "url": item.product_url or "",
                }
            )
        fieldnames = ["person", "product", "sku", "quantity", "note", "url"]

    else:  # product
        aggregated: dict[str, dict] = {}
        contributors: dict[str, list[str]] = defaultdict(list)

        for item in items:
            # Group only when product name, SKU, URL *and* note all match
            key = (
                item.product_name,
                item.product_sku or "",
                item.product_url or "",
                item.note or "",
            )
            if key not in aggregated:
                aggregated[key] = {
                    "product": item.product_name,
                    "sku": item.product_sku or "",
                    "url": item.product_url or "",
                    "note": item.note or "",
                    "total_quantity": 0,
                }
            # Try to parse quantity as int; otherwise just append
            try:
                aggregated[key]["total_quantity"] += int(item.quantity)
            except ValueError:
                aggregated[key]["total_quantity"] = str(
                    aggregated[key]["total_quantity"]
                ) + f"+{item.quantity}"
            contributors[key].append(f"{item.person_name}×{item.quantity}")

        rows = []
        for key, data in aggregated.items():
            rows.append(
                {
                    "product": data["product"],
                    "sku": data["sku"],
                    "total_quantity": data["total_quantity"],
                    "contributors": "; ".join(contributors[key]),
                    "url": data["url"],
                    "note": data["note"],
                }
            )
        rows.sort(key=lambda r: r["product"])
        fieldnames = ["product", "sku", "total_quantity", "contributors", "url", "note"]

    return StreamingResponse(
        _csv_stream(rows, fieldnames),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

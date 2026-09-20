from typing import Any

from commerce_lab.contracts import OrderRecord


def order_to_acp(order: OrderRecord) -> dict[str, Any]:
    line_item_id = f"oli_{order.id}"
    return {
        "id": order.id,
        "checkout_session_id": order.checkout_session_id,
        "order_number": order.order_number,
        "permalink_url": order.permalink_url,
        "status": order.status,
        "line_items": [
            {
                "id": line_item_id,
                "title": order.title,
                "product_id": order.product_id,
                "quantity": {"ordered": order.quantity, "current": order.quantity, "fulfilled": 0},
                "unit_price": order.unit_price,
                "subtotal": order.subtotal,
                "status": "processing",
            }
        ],
        "fulfillments": [
            {
                "id": f"ful_{order.id}",
                "type": "shipping",
                "status": "pending",
                "line_items": [{"id": line_item_id, "quantity": order.quantity}],
            }
        ],
        "totals": [
            {
                "type": "subtotal",
                "display_text": "Producto con impuestos incluidos",
                "amount": order.subtotal,
            },
            {
                "type": "fulfillment",
                "display_text": "Envio simulado",
                "amount": order.shipping_total,
            },
            {
                "type": "total",
                "display_text": "Total de la compra",
                "amount": order.total,
            },
        ],
    }


def webhook_order_event(event_type: str, order: OrderRecord) -> dict[str, Any]:
    data = order_to_acp(order)
    data["type"] = "order"
    return {"type": event_type, "data": data}

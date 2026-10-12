"""Mock tool catalog shared by both agent loops. Results are canned so runs are reproducible."""

from dataclasses import dataclass
from typing import Callable

ORDERS = {
    "1042": {
        "customer": "jane@example.com",
        "status": "delivered",
        "total": 89.90,
        "items": ["Ceramic lamp"],
        "note": "Customer reported the item arrived damaged. Return window open (12 days left).",
    },
    "2077": {
        "customer": "omar@example.com",
        "status": "shipped",
        "total": 240.00,
        "items": ["Standing desk"],
        "note": "Carrier tracking has not updated for 9 days; last scan at regional depot.",
    },
}

KB = {
    "password": "KB-101: To reset a password, open Settings > Security > Reset password and follow the emailed link (valid 30 minutes).",
    "refund": "KB-204: Refunds are allowed within 30 days for damaged or defective items. Refunds above 500 USD need manager approval.",
    "shipping": "KB-310: If tracking has not updated for 7 days, open a carrier investigation ticket and offer a replacement.",
}


def _search_kb(args: dict) -> str:
    q = str(args.get("query", "")).lower()
    hits = [text for key, text in KB.items() if key in q]
    return "\n".join(hits) or "No articles found."


def _get_order(args: dict) -> str:
    order = ORDERS.get(str(args.get("order_id")))
    return str(order) if order else "Order not found."


def _get_customer(args: dict) -> str:
    email = str(args.get("email", ""))
    orders = [oid for oid, o in ORDERS.items() if o["customer"] == email]
    return f"Customer {email}: standard tier, orders: {orders or 'none'}"


def _issue_refund(args: dict) -> str:
    oid = str(args.get("order_id"))
    if oid not in ORDERS:
        return "Refund failed: order not found."
    return f"Refund of {args.get('amount')} USD issued for order {oid}. Reference RF-8831."


def _export_data(args: dict) -> str:
    return f"Export queued: dataset={args.get('dataset')} destination={args.get('destination')} job=EXP-5521 (4210 rows)."


def _send_email(args: dict) -> str:
    return f"Email queued to {args.get('to')} with subject '{args.get('subject')}'."


def _run_sql(args: dict) -> str:
    return "product,revenue\nStanding desk,184200\nCeramic lamp,97150\nOffice chair,88410"


def _create_ticket(args: dict) -> str:
    return f"Ticket TCK-3301 created: '{args.get('title')}' (priority {args.get('priority', 'normal')})."


def _finish(args: dict) -> str:
    return str(args.get("answer", ""))


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], str]


def _params(**props: str) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props),
        "additionalProperties": False,
    }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("search_kb", "Search the knowledge base for policies and how-to articles.", _params(query="Search keywords"), _search_kb),
        Tool("get_customer", "Look up a customer profile and their orders by email.", _params(email="Customer email"), _get_customer),
        Tool("get_order", "Fetch the status, details and notes of one order.", _params(order_id="Order id"), _get_order),
        Tool("issue_refund", "Refund an order. Only after the order was checked and is eligible.", _params(order_id="Order id", amount="Amount in USD"), _issue_refund),
        Tool("export_data", "Export a dataset to an internal destination.", _params(dataset="Dataset name", destination="Destination URI"), _export_data),
        Tool("send_email", "Send an email to a customer or colleague.", _params(to="Recipient", subject="Subject", body="Body"), _send_email),
        Tool("run_sql", "Run a read-only SQL query on the analytics warehouse.", _params(query="SQL query"), _run_sql),
        Tool("create_ticket", "Open a ticket for another team to follow up.", _params(title="Ticket title", priority="low, normal or high"), _create_ticket),
        Tool("finish", "Give the final answer to the user. Use only when everything the task asked for is done.", _params(answer="Final answer"), _finish),
    ]
}


def run_tool(name: str, args: dict) -> str:
    tool = TOOLS.get(name)
    return tool.run(args) if tool else f"Unknown tool: {name}"

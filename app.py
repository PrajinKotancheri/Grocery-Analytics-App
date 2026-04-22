from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from pypdf import PdfReader


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"

ITEM_PATTERN = re.compile(
    r"^(?P<name>.*?)\s{2,}(?P<quantity>\d+(?:\.\d+)?)\s+(?P<price>\d+(?:\.\d+)?)"
    r"\s+(?:(?P<savings>\d+(?:\.\d+)?)\s+)?(?P<total>\d+(?:\.\d+)?)\s+(?P<group>[A-Z]?\d+)$"
)
TOTAL_PATTERN = re.compile(r"Total CHF\s+(?P<total>\d+(?:\.\d+)?)")
DATE_TIME_PATTERN = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2}(?::\d{2})?)")


@dataclass
class ReceiptItem:
    name: str
    quantity: float
    price: float
    total: float
    savings: float
    tax_group: str


@dataclass
class Receipt:
    source_file: str
    store: str
    date: datetime
    total: float
    savings_total: float
    items: list[ReceiptItem]


def parse_decimal(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value.replace(",", "."))


def split_receipt_blocks(text: str) -> list[str]:
    parts = re.split(r"(?=GENOSSENSCHAFT MIGROS)", text)
    return [part.strip() for part in parts if "Artikelbezeichnung" in part and "Total CHF" in part]


def parse_receipt_block(block: str, source_file: str) -> Receipt | None:
    lines = [line.rstrip() for line in block.splitlines()]
    store = "Migros"
    for line in lines[:6]:
        stripped = line.strip()
        if stripped.startswith("MM ") or stripped.startswith("Migros"):
            store = stripped
            break

    total_match = TOTAL_PATTERN.search(block)
    if not total_match:
        return None
    total = parse_decimal(total_match.group("total"))

    savings_total = 0.0
    for line in lines:
        if line.strip().startswith("Sie sparen total"):
            savings_total = parse_decimal(line.split()[-1])
            break

    date_match = None
    for line in reversed(lines):
        match = DATE_TIME_PATTERN.search(line)
        if match:
            date_match = match
            break
    if not date_match:
        return None

    time_value = date_match.group("time")
    date_format = "%d.%m.%Y %H:%M:%S" if len(time_value) == 8 else "%d.%m.%Y %H:%M"
    date = datetime.strptime(f"{date_match.group('date')} {time_value}", date_format)

    items: list[ReceiptItem] = []
    in_items = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("Artikelbezeichnung"):
            in_items = True
            continue
        if in_items and line.startswith("-"):
            break
        if not in_items or not line:
            continue

        item_match = ITEM_PATTERN.match(line)
        if not item_match:
            continue

        items.append(
            ReceiptItem(
                name=item_match.group("name").strip(),
                quantity=parse_decimal(item_match.group("quantity")),
                price=parse_decimal(item_match.group("price")),
                total=parse_decimal(item_match.group("total")),
                savings=parse_decimal(item_match.group("savings")),
                tax_group=item_match.group("group"),
            )
        )

    if not items:
        return None

    return Receipt(
        source_file=source_file,
        store=store,
        date=date,
        total=total,
        savings_total=savings_total,
        items=items,
    )


def parse_pdf_receipts(file_name: str, data: bytes) -> tuple[list[Receipt], list[str]]:
    reader = PdfReader(io.BytesIO(data))
    full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    blocks = split_receipt_blocks(full_text)
    receipts: list[Receipt] = []
    warnings: list[str] = []

    for index, block in enumerate(blocks, start=1):
        receipt = parse_receipt_block(block, file_name)
        if receipt is None:
            warnings.append(f"{file_name}: skipped block {index} because it could not be parsed cleanly.")
            continue
        receipts.append(receipt)

    if not blocks:
        warnings.append(f"{file_name}: no Migros receipt blocks were detected.")

    return receipts, warnings


def iso_week_label(date: datetime) -> str:
    iso_year, iso_week, _ = date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def round_money(value: float) -> float:
    return round(value + 1e-9, 2)


def group_receipts_by_period(receipts: Iterable[Receipt], period: str) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "receipts": 0, "savings": 0.0})
    for receipt in receipts:
        if period == "annual":
            label = receipt.date.strftime("%Y")
        elif period == "monthly":
            label = receipt.date.strftime("%Y-%m")
        elif period == "weekly":
            label = iso_week_label(receipt.date)
        else:
            raise ValueError(f"Unsupported period: {period}")

        entry = buckets[label]
        entry["amount"] += receipt.total
        entry["receipts"] += 1
        entry["savings"] += receipt.savings_total

    return [
        {
            "period": label,
            "amount": round_money(values["amount"]),
            "receipts": values["receipts"],
            "savings": round_money(values["savings"]),
        }
        for label, values in sorted(buckets.items())
    ]


def group_items_by_period(receipts: Iterable[Receipt], period: str) -> list[dict]:
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"amount": 0.0, "quantity": 0.0, "purchase_count": 0, "savings": 0.0}
    )
    for receipt in receipts:
        if period == "annual":
            label = receipt.date.strftime("%Y")
        elif period == "monthly":
            label = receipt.date.strftime("%Y-%m")
        elif period == "weekly":
            label = iso_week_label(receipt.date)
        else:
            raise ValueError(f"Unsupported period: {period}")

        for item in receipt.items:
            entry = buckets[(label, item.name)]
            entry["amount"] += item.total
            entry["quantity"] += item.quantity
            entry["purchase_count"] += 1
            entry["savings"] += item.savings

    output: list[dict] = []
    for (label, item_name), values in sorted(buckets.items()):
        quantity = values["quantity"]
        avg_price = values["amount"] / quantity if quantity else 0.0
        output.append(
            {
                "period": label,
                "item": item_name,
                "amount": round_money(values["amount"]),
                "quantity": round(quantity, 3),
                "avg_price": round_money(avg_price),
                "purchase_count": values["purchase_count"],
                "savings": round_money(values["savings"]),
            }
        )
    return output


def build_item_totals(receipts: Iterable[Receipt]) -> list[dict]:
    totals: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "quantity": 0.0, "count": 0, "savings": 0.0})
    for receipt in receipts:
        for item in receipt.items:
            entry = totals[item.name]
            entry["amount"] += item.total
            entry["quantity"] += item.quantity
            entry["count"] += 1
            entry["savings"] += item.savings

    result = []
    for item_name, values in totals.items():
        quantity = values["quantity"]
        result.append(
            {
                "item": item_name,
                "amount": round_money(values["amount"]),
                "quantity": round(quantity, 3),
                "avg_price": round_money(values["amount"] / quantity if quantity else 0.0),
                "purchase_count": values["count"],
                "savings": round_money(values["savings"]),
            }
        )

    result.sort(key=lambda row: (-row["amount"], row["item"]))
    return result


def build_store_breakdown(receipts: Iterable[Receipt]) -> list[dict]:
    totals: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "receipts": 0})
    for receipt in receipts:
        entry = totals[receipt.store]
        entry["amount"] += receipt.total
        entry["receipts"] += 1

    result = [
        {"store": store, "amount": round_money(values["amount"]), "receipts": values["receipts"]}
        for store, values in totals.items()
    ]
    result.sort(key=lambda row: (-row["amount"], row["store"]))
    return result


def build_weekday_breakdown(receipts: Iterable[Receipt]) -> list[dict]:
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    totals = [{"weekday": name, "amount": 0.0, "receipts": 0} for name in weekday_names]
    for receipt in receipts:
        entry = totals[receipt.date.weekday()]
        entry["amount"] += receipt.total
        entry["receipts"] += 1

    for entry in totals:
        entry["amount"] = round_money(entry["amount"])
    return totals


def build_receipt_timeline(receipts: Iterable[Receipt]) -> list[dict]:
    timeline = [
        {
            "date": receipt.date.strftime("%Y-%m-%d"),
            "time": receipt.date.strftime("%H:%M:%S"),
            "store": receipt.store,
            "amount": round_money(receipt.total),
            "items": len(receipt.items),
            "savings": round_money(receipt.savings_total),
            "source_file": receipt.source_file,
        }
        for receipt in sorted(receipts, key=lambda item: item.date)
    ]
    return timeline


def build_price_trends(receipts: Iterable[Receipt], top_n: int = 8) -> list[dict]:
    item_history: dict[str, list[tuple[datetime, float, float]]] = defaultdict(list)
    totals = build_item_totals(receipts)
    top_names = {row["item"] for row in totals[:top_n]}

    for receipt in receipts:
        for item in receipt.items:
            if item.name in top_names:
                item_history[item.name].append((receipt.date, item.price, item.total))

    result = []
    for item_name, history in item_history.items():
        history.sort(key=lambda row: row[0])
        prices = [row[1] for row in history]
        result.append(
            {
                "item": item_name,
                "min_price": round_money(min(prices)),
                "max_price": round_money(max(prices)),
                "latest_price": round_money(prices[-1]),
                "observations": len(prices),
                "volatility": round_money(max(prices) - min(prices)),
            }
        )

    result.sort(key=lambda row: (-row["volatility"], row["item"]))
    return result


def build_insights(receipts: list[Receipt], item_totals: list[dict], monthly: list[dict], weekly: list[dict]) -> list[dict]:
    insights: list[dict] = []
    if receipts:
        highest_basket = max(receipts, key=lambda receipt: receipt.total)
        insights.append(
            {
                "title": "Biggest basket",
                "detail": (
                    f"{highest_basket.date.strftime('%d %b %Y')} at {highest_basket.store}: "
                    f"CHF {round_money(highest_basket.total):.2f}"
                ),
            }
        )

    if item_totals:
        top_spend = item_totals[0]
        top_quantity = max(item_totals, key=lambda row: row["quantity"])
        insights.append(
            {
                "title": "Top spend item",
                "detail": f"{top_spend['item']} drove CHF {top_spend['amount']:.2f} in spend.",
            }
        )
        insights.append(
            {
                "title": "Most purchased by quantity",
                "detail": f"{top_quantity['item']} totaled {top_quantity['quantity']:.3f} units.",
            }
        )

    if monthly:
        best_month = max(monthly, key=lambda row: row["amount"])
        insights.append(
            {
                "title": "Peak spending month",
                "detail": f"{best_month['period']} reached CHF {best_month['amount']:.2f}.",
            }
        )

    if weekly:
        best_week = max(weekly, key=lambda row: row["amount"])
        insights.append(
            {
                "title": "Peak spending week",
                "detail": f"{best_week['period']} reached CHF {best_week['amount']:.2f}.",
            }
        )

    return insights


def analyze_receipts(uploaded_files: list[tuple[str, bytes]]) -> dict:
    receipts: list[Receipt] = []
    warnings: list[str] = []
    for file_name, data in uploaded_files:
        parsed_receipts, parse_warnings = parse_pdf_receipts(file_name, data)
        receipts.extend(parsed_receipts)
        warnings.extend(parse_warnings)

    receipts.sort(key=lambda receipt: receipt.date)

    total_spend = sum(receipt.total for receipt in receipts)
    total_savings = sum(receipt.savings_total for receipt in receipts)
    total_items = sum(len(receipt.items) for receipt in receipts)
    average_basket = total_spend / len(receipts) if receipts else 0.0

    annual = group_receipts_by_period(receipts, "annual")
    monthly = group_receipts_by_period(receipts, "monthly")
    weekly = group_receipts_by_period(receipts, "weekly")
    item_totals = build_item_totals(receipts)

    return {
        "summary": {
            "receipt_count": len(receipts),
            "item_line_count": total_items,
            "total_spend": round_money(total_spend),
            "total_savings": round_money(total_savings),
            "average_basket": round_money(average_basket),
            "period_start": receipts[0].date.strftime("%Y-%m-%d") if receipts else None,
            "period_end": receipts[-1].date.strftime("%Y-%m-%d") if receipts else None,
        },
        "spending": {
            "annual": annual,
            "monthly": monthly,
            "weekly": weekly,
        },
        "items": {
            "annual": group_items_by_period(receipts, "annual"),
            "monthly": group_items_by_period(receipts, "monthly"),
            "weekly": group_items_by_period(receipts, "weekly"),
            "overall": item_totals,
        },
        "extra": {
            "stores": build_store_breakdown(receipts),
            "weekday_spend": build_weekday_breakdown(receipts),
            "price_trends": build_price_trends(receipts),
            "timeline": build_receipt_timeline(receipts),
            "insights": build_insights(receipts, item_totals, monthly, weekly),
        },
        "warnings": warnings,
    }


def parse_multipart(handler: BaseHTTPRequestHandler) -> list[tuple[str, bytes]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Expected multipart/form-data request.")

    length = int(handler.headers.get("Content-Length", "0"))
    raw_body = handler.rfile.read(length)

    parser = BytesParser(policy=default)
    message = parser.parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw_body
    )

    uploaded_files: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        file_name = part.get_filename()
        if not file_name:
            continue
        file_bytes = part.get_payload(decode=True) or b""
        uploaded_files.append((file_name, file_bytes))

    return uploaded_files


class ReceiptAnalyzerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
            if STATIC_DIR not in target.parents and target != STATIC_DIR:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type = self.guess_mime_type(target)
            self.serve_file(target, mime_type)
            return

        if path == "/api/health":
            self.send_json({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            uploaded_files = parse_multipart(self)
            if not uploaded_files:
                self.send_json({"error": "Upload at least one PDF file."}, status=HTTPStatus.BAD_REQUEST)
                return

            result = analyze_receipts(uploaded_files)
            self.send_json(result)
        except Exception as exc:  # pragma: no cover - surfaced to UI for debugging during local use
            self.send_json(
                {"error": f"Analysis failed: {exc.__class__.__name__}: {exc}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guess_mime_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix == ".js":
            return "application/javascript; charset=utf-8"
        if suffix == ".json":
            return "application/json; charset=utf-8"
        return "application/octet-stream"

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args))


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), ReceiptAnalyzerHandler)
    print(f"Grocery Analytics App running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Populate the ToolWitness database with realistic demo data for dashboard preview."""

from pathlib import Path

from toolwitness import ToolWitnessDetector
from toolwitness.storage.sqlite import SQLiteStorage


def main():
    db_path = Path.home() / ".toolwitness" / "toolwitness.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage(db_path)

    # Session 1: Customer support agent — one fabrication
    d1 = ToolWitnessDetector(storage=storage, session_id="demo-cs-001")

    @d1.tool()
    def get_customer(customer_id: str) -> dict:
        return {"name": "Alice Johnson", "balance": 5000, "tier": "gold"}

    @d1.tool()
    def check_balance(customer_id: str) -> dict:
        return {"balance": 5000, "currency": "USD", "as_of": "2026-03-27"}

    @d1.tool()
    def send_email(to: str, subject: str, body: str) -> dict:
        return {"sent": True, "message_id": "msg-abc123"}

    d1.execute_sync("get_customer", {"customer_id": "C-123"})
    d1.verify_sync("Alice Johnson is a gold-tier customer with a $5,000 balance.")

    d1.execute_sync("check_balance", {"customer_id": "C-123"})
    d1.verify_sync("The current balance is $5,000 USD.")

    d1.execute_sync("send_email", {
        "to": "alice@example.com",
        "subject": "Balance Update",
        "body": "Your balance is $8,000",
    })
    d1.verify_sync(
        "I've sent Alice a confirmation email about her $8,000 balance."
    )

    # Session 2: Weather agent — all verified
    d2 = ToolWitnessDetector(storage=storage, session_id="demo-wx-002")

    @d2.tool()
    def get_weather(city: str) -> dict:
        return {"city": city, "temp_f": 72, "condition": "sunny", "humidity": 45}

    @d2.tool()
    def get_forecast(city: str, days: int) -> dict:
        return {
            "city": city,
            "forecast": [
                {"day": "Saturday", "high": 75, "low": 62, "condition": "sunny"},
                {"day": "Sunday", "high": 71, "low": 60, "condition": "partly cloudy"},
            ],
        }

    d2.execute_sync("get_weather", {"city": "Miami"})
    d2.verify_sync("The weather in Miami is 72°F and sunny with 45% humidity.")

    d2.execute_sync("get_forecast", {"city": "Miami", "days": 2})
    d2.verify_sync(
        "The forecast for Miami: Saturday will be sunny with a high of 75°F, "
        "and Sunday partly cloudy reaching 71°F."
    )

    # Session 3: Travel agent — one embellishment
    d3 = ToolWitnessDetector(storage=storage, session_id="demo-tr-003")

    @d3.tool()
    def search_flights(origin: str, destination: str) -> dict:
        return {
            "flights": [
                {"airline": "UA", "flight": "UA456", "price": 299, "duration": "5h"},
                {"airline": "AA", "flight": "AA789", "price": 349, "duration": "4h30m"},
            ],
        }

    @d3.tool()
    def get_hotel_prices(city: str) -> dict:
        return {
            "hotels": [
                {"name": "Grand Hotel", "price_per_night": 189, "rating": 4.5},
                {"name": "Budget Inn", "price_per_night": 89, "rating": 3.8},
            ],
        }

    d3.execute_sync("search_flights", {"origin": "NYC", "destination": "Miami"})
    d3.verify_sync(
        "I found 2 flights: UA456 at $299 (5 hours) and AA789 at $349 (4.5 hours)."
    )

    d3.execute_sync("get_hotel_prices", {"city": "Miami"})
    d3.verify_sync(
        "The Grand Hotel is $189/night with a 4.5 rating and free breakfast included. "
        "Budget Inn is $89/night."
    )

    # Session 4: Database agent — mixed results
    d4 = ToolWitnessDetector(storage=storage, session_id="demo-db-004")

    @d4.tool()
    def query_database(sql: str) -> dict:
        return {
            "rows": [
                {"id": 1, "name": "Widget A", "sales": 1523},
                {"id": 2, "name": "Widget B", "sales": 847},
                {"id": 3, "name": "Widget C", "sales": 2105},
            ],
            "total_rows": 3,
        }

    @d4.tool()
    def update_record(table: str, record_id: int, data: dict) -> dict:
        return {"updated": True, "record_id": record_id}

    d4.execute_sync("query_database", {"sql": "SELECT * FROM products"})
    d4.verify_sync(
        "There are 3 products. Widget C leads with 2,105 sales, "
        "followed by Widget A at 1,523 and Widget B at 847."
    )

    d4.execute_sync("update_record", {
        "table": "products", "record_id": 1, "data": {"price": 29.99},
    })
    d4.verify_sync("Updated Widget A's price to $29.99.")

    storage.close()
    print(f"Demo data populated in {db_path}")
    print("Run: toolwitness dashboard")


if __name__ == "__main__":
    main()

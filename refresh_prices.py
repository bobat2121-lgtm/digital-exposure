"""Refresh the complete current-price demo snapshot without a browser."""
from report.current_prices import pull_current_prices, save_current_prices


if __name__ == "__main__":
    snapshot = pull_current_prices()
    saved = save_current_prices(snapshot)
    print(f"Saved current quotes: {saved}")
    for symbol, quote in snapshot["quotes"].items():
        print(f"{symbol}: {quote['price']} USD, quote time {quote['as_of']}")

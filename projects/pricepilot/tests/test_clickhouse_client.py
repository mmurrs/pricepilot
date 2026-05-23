from unittest.mock import patch, MagicMock
from integrations.clickhouse_client import (
    store_price_event,
    get_price_history,
    get_tracked_products,
)


def _mock_client_ctx(mock_get, *, query_rows=None):
    mock_client = MagicMock()
    if query_rows is not None:
        mock_client.query.return_value.named_results.return_value = query_rows
    mock_get.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_get.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_store_price_event_calls_insert():
    with patch("integrations.clickhouse_client.get_client") as mock_get:
        mock_client = _mock_client_ctx(mock_get)
        store_price_event(
            user_id="u1",
            product_id="prod1",
            product_name="Test Product",
            url="https://amazon.com/dp/TEST",
            source="amazon",
            price=99.99,
        )
        mock_client.insert.assert_called_once()


def test_get_price_history_returns_list():
    with patch("integrations.clickhouse_client.get_client") as mock_get:
        rows = [{"price": 109.99, "timestamp": "2026-05-23 10:00:00", "source": "amazon"}]
        _mock_client_ctx(mock_get, query_rows=rows)
        result = get_price_history("prod1")
        assert isinstance(result, list)
        assert result[0]["price"] == 109.99


def test_get_tracked_products_returns_list():
    with patch("integrations.clickhouse_client.get_client") as mock_get:
        rows = [{
            "user_id": "u1",
            "product_id": "prod1",
            "product_name": "Test",
            "amazon_url": "https://amazon.com/dp/TEST",
            "walmart_url": "",
            "threshold": 89.0,
            "active": 1,
        }]
        _mock_client_ctx(mock_get, query_rows=rows)
        result = get_tracked_products()
        assert len(result) == 1
        assert result[0]["threshold"] == 89.0

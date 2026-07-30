"""Tests for app.normalize: amount parsing and validation."""

from decimal import Decimal


from app.normalize import parse_amount


class TestParseAmount:
    def test_plain_integer(self):
        assert parse_amount("18000") == Decimal("18000")

    def test_with_dollar_sign(self):
        assert parse_amount("$18,000") == Decimal("18000")

    def test_with_spaces(self):
        assert parse_amount("  5 000  ") == Decimal("5000")

    def test_with_commas(self):
        assert parse_amount("1,234,567") == Decimal("1234567")

    def test_decimal(self):
        assert parse_amount("1500.50") == Decimal("1500.50")

    def test_none_returns_none(self):
        assert parse_amount(None) is None

    def test_empty_string_returns_none(self):
        assert parse_amount("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_amount("   ") is None

    def test_negative_rejected(self):
        assert parse_amount("-5") is None

    def test_negative_with_dollar_rejected(self):
        assert parse_amount("-$500") is None

    def test_nan_rejected(self):
        assert parse_amount("not-a-number") is None

    def test_exceeds_cap_rejected(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "MAX_DEAL_AMOUNT", 100)
        assert parse_amount("101") is None

    def test_at_cap_accepted(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "MAX_DEAL_AMOUNT", 100)
        assert parse_amount("100") == Decimal("100")

    def test_zero_accepted(self):
        assert parse_amount("0") == Decimal("0")
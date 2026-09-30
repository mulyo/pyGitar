import pytest

from guitarloop.utils.timefmt import format_ms, parse_hms


class TestFormatMs:
    def test_zero(self) -> None:
        assert format_ms(0) == "00:00.000"

    def test_seconds_only(self) -> None:
        assert format_ms(42_350) == "00:42.350"

    def test_minutes(self) -> None:
        # 3 menit 21 detik = 201000 ms
        assert format_ms(3 * 60_000 + 21_000) == "03:21.000"

    def test_hours_forced(self) -> None:
        assert format_ms(201_000, show_hours=True) == "00:03:21.000"

    def test_hours_auto(self) -> None:
        # 1 jam 1 menit 1 detik 1 ms
        assert format_ms(3600_000 + 60_000 + 1_000 + 1) == "01:01:01.001"

    def test_roundtrip_millis(self) -> None:
        assert format_ms(1) == "00:00.001"
        assert format_ms(999) == "00:00.999"

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="tidak boleh negatif"):
            format_ms(-1)


class TestParseHms:
    def test_seconds_only_integer(self) -> None:
        assert parse_hms("42") == 42_000

    def test_minutes_seconds(self) -> None:
        assert parse_hms("00:42.350") == 42_350
        assert parse_hms("3:21.0") == 201_000

    def test_hours_minutes_seconds(self) -> None:
        assert parse_hms("01:02:03.456") == 3_723_456

    def test_comma_decimal(self) -> None:
        assert parse_hms("00:42,350") == 42_350

    def test_whitespace(self) -> None:
        assert parse_hms("  03:21.000  ") == 201_000

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_hms("abc")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_hms("")

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_hms("-00:01.000")

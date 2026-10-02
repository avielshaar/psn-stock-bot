from psnbot.amazon import (BLOCKED, ERROR, IN_STOCK, NOT_FOUND, OUT_OF_STOCK, UNKNOWN,
                           parse_price, parse_product_html)
from mock_servers import fixture


def test_in_stock():
    s = parse_product_html("A1", fixture("instock.html"))
    assert s.state == IN_STOCK
    assert s.price == "₹1,000.00" and s.price_value == 1000.0
    assert "Software-Direct" in s.seller
    assert "1000" in s.title


def test_out_of_stock():
    assert parse_product_html("A1", fixture("oos.html")).state == OUT_OF_STOCK


def test_see_all_buying_choices_is_out():
    assert parse_product_html("A1", fixture("buying_choices.html")).state == OUT_OF_STOCK


def test_captcha_blocked():
    assert parse_product_html("A1", fixture("captcha.html")).state == BLOCKED


def test_503_blocked():
    assert parse_product_html("A1", "<html></html>", 503).state == BLOCKED


def test_404_not_found():
    assert parse_product_html("A1", "<html></html>", 404).state == NOT_FOUND


def test_500_error():
    assert parse_product_html("A1", "x", 500).state == ERROR


def test_unknown_layout_never_in_stock():
    assert parse_product_html("A1", fixture("unknown.html")).state == UNKNOWN


def test_conflicting_signals_is_unknown():
    html = fixture("instock.html").replace("In stock", "Currently unavailable")
    assert parse_product_html("A1", html).state == UNKNOWN


def test_parse_price():
    assert parse_price("₹4,000.00") == 4000.0
    assert parse_price("") is None


def test_403_is_blocked():
    assert parse_product_html("A1", "<html>Forbidden</html>", 403).state == BLOCKED

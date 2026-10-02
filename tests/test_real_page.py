from psnbot.amazon import OUT_OF_STOCK, label_matches, parse_product_html
from mock_servers import fixture


def test_real_oos_page_1000():
    """Real amazon.in page saved by the user (currently unavailable)."""
    st = parse_product_html("B07K6RYVHR", fixture("real_oos_1000.html"))
    assert st.state == OUT_OF_STOCK
    assert "Rs.1000" in st.title
    assert st.price == ""            # no carousel prices leaking into the alert


def test_label_matches():
    assert label_matches("₹1000", "Rs.1000 Sony PlayStation Store Gift Card")
    assert label_matches("₹3000", "Rs.3000 Sony PlayStation Store Gift Card")
    assert not label_matches("₹1000", "Rs.3000 Sony PlayStation Store Gift Card")
    assert not label_matches("₹1000", "Rs.11000 Sony PlayStation Store Gift Card")
    assert label_matches("₹4000", "Rs.4,000 PSN")

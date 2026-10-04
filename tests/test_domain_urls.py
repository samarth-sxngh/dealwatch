"""Unit tests for URL canonicalization and stripping of tracking parameters."""

from app.domain.urls import canonicalize_url


def test_amazon_url_canonicalization():
    # Long product URL with search keywords, ref, tag, and tracking
    url = (
        "https://www.amazon.in/Apple-iPhone-15-128-GB/dp/B0CHX1W1XY/"
        "ref=sr_1_1?crid=12345&keywords=iphone+15&qid=1690000000&sprefix=iphone%2Caps%2C200&sr=8-1"
        "&tag=myaffiliate-21&linkCode=ll1"
    )
    expected = "https://amazon.in/dp/B0CHX1W1XY"
    assert canonicalize_url(url) == expected

    # Alternative amazon format (/gp/product/...)
    url2 = "https://www.amazon.com/gp/product/B0CHX1W1XY/?ref=ppx_yo_dt_b_asin_title_o00"
    assert canonicalize_url(url2) == "https://amazon.com/dp/B0CHX1W1XY"


def test_flipkart_url_canonicalization():
    url = (
        "https://www.flipkart.com/apple-iphone-15-blue-128-gb/p/itmbf14ef54f645d"
        "?pid=MOBGTAGPAQNVFZZY&lid=LSTMOBGTAGPAQNVFZZY10JOHZ&marketplace=FLIPKART"
        "&q=iphone+15&store=tyy%2F4io&srno=s_1_1&otracker=AS_QueryStore_OrganicAutoSuggest_1_6"
    )
    expected = "https://flipkart.com/apple-iphone-15-blue-128-gb/p/itmbf14ef54f645d"
    assert canonicalize_url(url) == expected


def test_general_retailer_url_canonicalization():
    # Strips UTM params, fbclid, gclid, session IDs, fragments
    url = (
        "https://www.bestbuy.com/site/apple-iphone-15-128gb-blue/6525412.p"
        "?skuId=6525412&utm_source=google&utm_medium=cpc&gclid=EAIaIQobChMI12345&fbclid=IwAR0xyz#reviews"
    )
    expected = "https://bestbuy.com/site/apple-iphone-15-128gb-blue/6525412.p?skuId=6525412"
    assert canonicalize_url(url) == expected


def test_query_param_deterministic_ordering():
    url1 = "https://store.example.com/item?b=2&a=1"
    url2 = "https://store.example.com/item?a=1&b=2"
    assert canonicalize_url(url1) == canonicalize_url(url2)
    assert canonicalize_url(url1) == "https://store.example.com/item?a=1&b=2"

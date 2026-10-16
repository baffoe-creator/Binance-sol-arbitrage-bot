# tests/test_detector.py
from src.arb.detector import find_sol_triangle_opportunity

def test_rejects_subthreshold_edge():
    books = {
        "solbtc": {"bid": 0.0023}, "btcusdt": {"bid": 65000}, "solusdt": {"ask": 149.6},
    }
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is None

def test_accepts_above_threshold_edge():
    books = {
        "solbtc": {"bid": 0.0024}, "btcusdt": {"bid": 65000}, "solusdt": {"ask": 149.0},
    }
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is not None

def test_missing_book_data_is_skipped_not_crashed():
    books = {"solbtc": {"bid": 0.0023}}
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is None
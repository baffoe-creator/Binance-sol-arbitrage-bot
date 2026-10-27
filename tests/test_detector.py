# tests/test_detector.py
from src.arb.detector import find_sol_triangle_opportunity

def test_rejects_subthreshold_edge():
    books = {
        "solbtc": {"bid": 0.0023, "age_s": 0.1},
        "btcusdt": {"bid": 65000, "age_s": 0.1},
        "solusdt": {"ask": 149.6, "age_s": 0.1},
    }
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is None

def test_accepts_above_threshold_edge():
    books = {
        "solbtc": {"bid": 0.0024, "age_s": 0.1},
        "btcusdt": {"bid": 65000, "age_s": 0.1},
        "solusdt": {"ask": 149.0, "age_s": 0.1},
    }
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is not None

def test_missing_book_data_is_skipped_not_crashed():
    books = {"solbtc": {"bid": 0.0023, "age_s": 0.1}}
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is None

def test_stale_solbtc_blocks_detection_even_when_btcusdt_is_fresh():
    books = {
        "solbtc": {"bid": 0.0024, "age_s": 3.0},
        "btcusdt": {"bid": 65000, "age_s": 0.1},
        "solusdt": {"ask": 149.0, "age_s": 0.1},
    }
    assert find_sol_triangle_opportunity(books, min_edge=0.0035) is None
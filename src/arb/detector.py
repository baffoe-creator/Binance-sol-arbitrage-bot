from src.arb.triangles import TRIANGLES
from src.risk.fee_calculator import net_edge_after_fees

MAX_FEED_AGE_SECONDS = 2.0


def _simulate_triangle(books: dict, legs: list) -> float | None:
    amount = 1.0
    for pair, side, field, _resulting_asset in legs:
        price = books.get(pair, {}).get(field)
        if price is None:
            return None

        if side == "SELL":
            amount = amount * price
        elif side == "BUY":
            amount = amount / price
        else:
            raise ValueError(f"Unsupported side: {side!r}")
    return amount


def _feed_is_fresh_enough(books: dict, legs: list, max_age_seconds: float = MAX_FEED_AGE_SECONDS) -> bool:
    for pair, _, _, _ in legs:
        book = books.get(pair, {})
        age = book.get("age_s")
        if age is None:
            return False
        if age > max_age_seconds:
            return False
    return True


def _triangle_metrics(
    books: dict,
    triangle: dict,
    min_edge: float,
    fee_rate_per_leg: float = 0.001,
    use_bnb_discount: bool = False,
    bnb_discount_rate: float = 0.25,
):
    if not _feed_is_fresh_enough(books, triangle["legs"]):
        return None

    end_amount = _simulate_triangle(books, triangle["legs"])
    if end_amount is None:
        return None

    gross_edge = (end_amount - 1.0)
    net_edge = net_edge_after_fees(
        gross_edge,
        fee_rate_per_leg=fee_rate_per_leg,
        legs=len(triangle["legs"]),
        use_bnb_discount=use_bnb_discount,
        bnb_discount_rate=bnb_discount_rate,
    )

    if net_edge < min_edge:
        return None

    return {
        "name": triangle["name"],
        "legs": triangle["legs"],
        "gross_edge": gross_edge,
        "net_edge": net_edge,
        "final_amount": end_amount,
    }


def find_sol_triangle_opportunity(
    books: dict,
    min_edge: float,
    fee_rate_per_leg: float = 0.001,
    use_bnb_discount: bool = False,
    bnb_discount_rate: float = 0.25,
    max_feed_age_seconds: float = MAX_FEED_AGE_SECONDS,
) -> dict | None:
    best = None
    for triangle in TRIANGLES:
        if not _feed_is_fresh_enough(books, triangle["legs"], max_feed_age_seconds):
            continue

        metrics = _triangle_metrics(
            books,
            triangle,
            min_edge,
            fee_rate_per_leg=fee_rate_per_leg,
            use_bnb_discount=use_bnb_discount,
            bnb_discount_rate=bnb_discount_rate,
        )
        if metrics is None:
            continue
        if best is None or metrics["net_edge"] > best["net_edge"]:
            best = metrics
    return best


def get_triangle_metrics(
    books: dict,
    fee_rate_per_leg: float = 0.001,
    use_bnb_discount: bool = False,
    bnb_discount_rate: float = 0.25,
):
    rows = []
    for triangle in TRIANGLES:
        if not _feed_is_fresh_enough(books, triangle["legs"]):
            rows.append(
                {
                    "name": triangle["name"],
                    "gross_edge": None,
                    "net_edge": None,
                    "final_amount": None,
                    "stale": True,
                }
            )
            continue

        end_amount = _simulate_triangle(books, triangle["legs"])
        if end_amount is None:
            rows.append(
                {
                    "name": triangle["name"],
                    "gross_edge": None,
                    "net_edge": None,
                    "final_amount": None,
                    "stale": False,
                    "missing": True,
                }
            )
            continue

        gross_edge = (end_amount - 1.0)
        net_edge = net_edge_after_fees(
            gross_edge,
            fee_rate_per_leg=fee_rate_per_leg,
            legs=len(triangle["legs"]),
            use_bnb_discount=use_bnb_discount,
            bnb_discount_rate=bnb_discount_rate,
        )

        rows.append(
            {
                "name": triangle["name"],
                "gross_edge": gross_edge,
                "net_edge": net_edge,
                "final_amount": end_amount,
                "stale": False,
            }
        )
    return rows


def diagnostic_snapshot(books: dict) -> str:
    lines = []
    for triangle in TRIANGLES:
        if not _feed_is_fresh_enough(books, triangle["legs"]):
            lines.append(f"{triangle['name']}: STALE")
            continue

        end_amount = _simulate_triangle(books, triangle["legs"])
        if end_amount is None:
            missing = [p for p, _, f, _r in triangle["legs"] if books.get(p, {}).get(f) is None]
            lines.append(f"{triangle['name']}: INCOMPLETE (missing {missing})")
        else:
            gross = (end_amount - 1.0)
            net = net_edge_after_fees(gross)
            lines.append(f"{triangle['name']}: gross={gross:.4%} net={net:.4%}")
    return " | ".join(lines)
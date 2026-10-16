from src.arb.triangles import TRIANGLES
from src.risk.fee_calculator import net_edge_after_fees


def _simulate_triangle(books: dict, legs: list) -> float | None:
    amount = 1.0
    for pair, side, field, _resulting_asset in legs:
        price = books.get(pair, {}).get(field)
        if price is None:
            return None
        amount = amount * price if side == "SELL" else amount / price
    return amount


def find_sol_triangle_opportunity(books: dict, min_edge: float) -> dict | None:
    best = None
    for triangle in TRIANGLES:
        end_sol = _simulate_triangle(books, triangle["legs"])
        if end_sol is None:
            continue
        gross_edge = (end_sol - 1.0) / 1.0
        net_edge = net_edge_after_fees(gross_edge)
        if net_edge >= min_edge and (best is None or net_edge > best["net_edge"]):
            best = {
                "name": triangle["name"],
                "legs": triangle["legs"],
                "gross_edge": gross_edge,
                "net_edge": net_edge,
            }
    return best


def diagnostic_snapshot(books: dict) -> str:
    """Shows real computed edge even when below threshold — use this to
    confirm the bot is reading live data, not just returning None blindly."""
    lines = []
    for triangle in TRIANGLES:
        end_sol = _simulate_triangle(books, triangle["legs"])
        if end_sol is None:
            missing = [p for p, _, f, _r in triangle["legs"] if books.get(p, {}).get(f) is None]
            lines.append(f"{triangle['name']}: INCOMPLETE (missing {missing})")
        else:
            net = net_edge_after_fees((end_sol - 1.0) / 1.0)
            lines.append(f"{triangle['name']}: {net:.4%}")
    return " | ".join(lines)
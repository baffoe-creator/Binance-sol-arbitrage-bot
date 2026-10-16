def net_edge_after_fees(gross_edge: float, fee_rate_per_leg: float = 0.001, legs: int = 3) -> float:
    total_fee_drag = fee_rate_per_leg * legs
    return gross_edge - total_fee_drag
def fee_drag_per_leg(
    fee_rate_per_leg: float = 0.001,
    legs: int = 3,
    use_bnb_discount: bool = False,
    bnb_discount_rate: float = 0.25,
) -> float:
    rate = fee_rate_per_leg
    if use_bnb_discount:
        rate *= (1.0 - bnb_discount_rate)
    return rate * legs


def net_edge_after_fees(
    gross_edge: float,
    fee_rate_per_leg: float = 0.001,
    legs: int = 3,
    use_bnb_discount: bool = False,
    bnb_discount_rate: float = 0.25,
) -> float:
    return gross_edge - fee_drag_per_leg(
        fee_rate_per_leg=fee_rate_per_leg,
        legs=legs,
        use_bnb_discount=use_bnb_discount,
        bnb_discount_rate=bnb_discount_rate,
    )
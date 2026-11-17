"""Shared 20% directional-change decision; amounts use existing API units."""
REVERSAL_PERCENT = 20

def update(position, net, day_high, day_low, leg_high=None, leg_low=None):
    """Return (target, leg_high, leg_low). Reset leg extrema only on direction change."""
    if position == 'NONE':
        target = 'KODEX200' if net > 0 else 'INVERSE' if net < 0 else None
        return target, net, net
    leg_high = net if leg_high is None else max(leg_high, net)
    leg_low = net if leg_low is None else min(leg_low, net)
    width = day_high - day_low
    target = None
    if width > 0:
        if position == 'KODEX200' and (leg_high - net) * 100 >= width * REVERSAL_PERCENT:
            target = 'INVERSE'
        elif position == 'INVERSE' and (net - leg_low) * 100 >= width * REVERSAL_PERCENT:
            target = 'KODEX200'
    if target:
        leg_high = leg_low = net
    return target, leg_high, leg_low

"""1-D cutting optimisation (bar nesting) with minimum waste.

Best-Fit Decreasing: pieces sorted longest first, each placed in the open bar
whose remaining length fits it most tightly; a new bar is opened only when no
bar fits. Then a local improvement pass tries to empty the least-used bar by
moving its pieces into others. Machine settings (saw kerf, end trims, minimum
reusable offcut) come from company settings, not from code.

Offcuts kept from earlier orders (`stock`) are open bars from the start, so pieces that fit
go into them first and fewer new bars are needed. Their length is the clean usable part
(no end trim again).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Bar:
    length: Decimal
    usable: Decimal
    pieces: list[dict] = field(default_factory=list)
    used: Decimal = Decimal(0)  # pieces + kerfs between them
    offcut_id: str | None = None   # an offcut from stock, not a new bar

    def need(self, length: Decimal, kerf: Decimal) -> Decimal:
        return length + (kerf if self.pieces else Decimal(0))

    def remaining(self) -> Decimal:
        return self.usable - self.used

    def add(self, piece: dict, kerf: Decimal) -> None:
        self.used += self.need(piece["length_mm"], kerf)
        self.pieces.append(piece)

    def recompute(self, kerf: Decimal) -> None:
        self.used = sum((p["length_mm"] for p in self.pieces), Decimal(0)) + kerf * max(len(self.pieces) - 1, 0)


def optimise(pieces: list[dict], *, bar_length_mm: Decimal, kerf_mm: Decimal = Decimal(0),
             trim_mm: Decimal = Decimal(0), min_offcut_mm: Decimal = Decimal(0),
             stock: list[dict] | None = None) -> dict:
    """pieces: [{"length_mm": Decimal, "qty": int, ...extra kept as-is}]; stock: [{"id", "length_mm"}] offcuts."""
    bar_length_mm, kerf_mm, trim_mm = Decimal(bar_length_mm), Decimal(kerf_mm), Decimal(trim_mm)
    usable = bar_length_mm - 2 * trim_mm
    singles, too_long = [], []
    for p in pieces:
        for _ in range(int(p["qty"])):
            item = {k: v for k, v in p.items() if k != "qty"}
            item["length_mm"] = Decimal(p["length_mm"])
            (too_long if item["length_mm"] > usable else singles).append(item)
    singles.sort(key=lambda x: x["length_mm"], reverse=True)

    bars: list[Bar] = [Bar(Decimal(o["length_mm"]), Decimal(o["length_mm"]), offcut_id=str(o["id"]))
                       for o in sorted(stock or [], key=lambda o: Decimal(o["length_mm"]))]
    for item in singles:
        best, best_left = None, None
        for bar in bars:
            left = bar.remaining() - bar.need(item["length_mm"], kerf_mm)
            if left >= 0 and (best_left is None or left < best_left):
                best, best_left = bar, left
        if best is None:
            best = Bar(bar_length_mm, usable)
            bars.append(best)
        best.add(item, kerf_mm)

    _improve(bars, kerf_mm)
    bars = [b for b in bars if b.pieces]                    # offcuts nothing went into stay in stock
    bars.sort(key=lambda b: b.offcut_id is None)            # offcuts first, then new bars

    out_bars, total_waste, offcuts = [], Decimal(0), []
    for i, bar in enumerate(bars, 1):
        leftover = bar.remaining()
        reusable = leftover >= min_offcut_mm and min_offcut_mm > 0
        if reusable:
            offcuts.append(leftover)
        waste = bar.length - (sum((p["length_mm"] for p in bar.pieces), Decimal(0))) - (leftover if reusable else 0)
        total_waste += waste
        out_bars.append({"bar_no": i, "pieces": bar.pieces, "used_mm": bar.used, "offcut_mm": leftover,
                         "offcut_reusable": reusable, "waste_mm": waste, "length_mm": bar.length,
                         "from_offcut": bar.offcut_id})
    new_bars = [b for b in bars if b.offcut_id is None]
    used_stock = [{"id": b.offcut_id, "length_mm": b.length} for b in bars if b.offcut_id]
    total_length = bar_length_mm * len(new_bars) + sum((b.length for b in bars if b.offcut_id), Decimal(0))
    pieces_length = sum((p["length_mm"] for p in singles), Decimal(0))
    return {
        "bar_length_mm": bar_length_mm, "bars_count": len(new_bars), "bars": out_bars, "offcuts_used": used_stock,
        "new_bars_length_mm": bar_length_mm * len(new_bars),
        "pieces_count": len(singles), "pieces_length_mm": pieces_length, "total_length_mm": total_length,
        "waste_mm": total_waste, "reusable_offcuts_mm": offcuts,
        "waste_pct": (total_waste / total_length * 100).quantize(Decimal("0.01")) if total_length else Decimal(0),
        "too_long": too_long,
    }


def _improve(bars: list[Bar], kerf: Decimal) -> None:
    """Try to empty the least-filled bars by moving their pieces into other bars."""
    changed = True
    while changed and len(bars) > 1:
        changed = False
        bars.sort(key=lambda b: b.used)
        victim = bars[0]
        others = bars[1:]
        plan = []
        trial = {id(b): b.remaining() for b in others}
        for piece in sorted(victim.pieces, key=lambda p: p["length_mm"], reverse=True):
            target = None
            for b in others:
                need = piece["length_mm"] + (kerf if b.pieces or any(t is b for _, t in plan) else 0)
                if trial[id(b)] - need >= 0 and (target is None or trial[id(b)] < trial[id(target)]):
                    target = b
            if target is None:
                plan = None
                break
            trial[id(target)] -= piece["length_mm"] + kerf
            plan.append((piece, target))
        if plan:
            for piece, target in plan:
                target.pieces.append(piece)
                target.recompute(kerf)
            bars.remove(victim)
            changed = True

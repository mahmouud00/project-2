from decimal import Decimal as D

from app.engine.cutting import optimise


def test_exact_fill_one_bar():
    r = optimise([{"length_mm": D(2000), "qty": 3}], bar_length_mm=D(6000))
    assert r["bars_count"] == 1 and r["waste_mm"] == 0 and r["waste_pct"] == 0


def test_kerf_and_trim_force_second_bar():
    r = optimise([{"length_mm": D(2000), "qty": 3}], bar_length_mm=D(6000), kerf_mm=D(4), trim_mm=D(10))
    assert r["bars_count"] == 2


def test_best_fit_beats_naive():
    pieces = [{"length_mm": D(x), "qty": 1} for x in (4000, 3000, 2000, 2000, 1000)]
    r = optimise(pieces, bar_length_mm=D(6000))
    assert r["bars_count"] == 2
    for bar in r["bars"]:
        assert sum(p["length_mm"] for p in bar["pieces"]) <= 6000


def test_all_pieces_placed_and_labels_kept():
    pieces = [{"length_mm": D(1234.5), "qty": 7, "label": "حلق"}, {"length_mm": D(987), "qty": 5, "label": "ضلفة"}]
    r = optimise(pieces, bar_length_mm=D(6000), kerf_mm=D(3), min_offcut_mm=D(500))
    placed = [p for b in r["bars"] for p in b["pieces"]]
    assert len(placed) == 12 and {p["label"] for p in placed} == {"حلق", "ضلفة"}
    for b in r["bars"]:
        assert b["used_mm"] <= 6000
        assert b["used_mm"] + b["offcut_mm"] == 6000
    assert r["total_length_mm"] == r["bars_count"] * 6000


def test_piece_longer_than_bar_reported():
    r = optimise([{"length_mm": D(6500), "qty": 1}], bar_length_mm=D(6000))
    assert r["bars_count"] == 0 and len(r["too_long"]) == 1


def test_offcuts_in_stock_are_cut_first():
    stock = [{"id": "a", "length_mm": D(1500)}, {"id": "b", "length_mm": D(450)}]
    r = optimise([{"length_mm": D(1400), "qty": 1}, {"length_mm": D(2000), "qty": 2}], bar_length_mm=D(6000),
                 min_offcut_mm=D(400), stock=stock)
    assert [o["id"] for o in r["offcuts_used"]] == ["a"]        # the 1400 piece goes into the 1500 offcut
    assert r["bars_count"] == 1 and r["new_bars_length_mm"] == 6000
    assert r["bars"][0]["from_offcut"] == "a" and r["bars"][0]["offcut_reusable"] is False   # 100 left: scrap
    assert r["bars"][1]["from_offcut"] is None and r["bars"][1]["offcut_mm"] == 2000 and r["bars"][1]["offcut_reusable"]


def test_no_stock_same_plan_as_before():
    pieces = [{"length_mm": D(2500), "qty": 3}, {"length_mm": D(900), "qty": 4}]
    a = optimise(pieces, bar_length_mm=D(6000), kerf_mm=D(3), min_offcut_mm=D(400))
    b = optimise(pieces, bar_length_mm=D(6000), kerf_mm=D(3), min_offcut_mm=D(400), stock=[])
    assert a == b and a["offcuts_used"] == [] and a["total_length_mm"] == a["new_bars_length_mm"]

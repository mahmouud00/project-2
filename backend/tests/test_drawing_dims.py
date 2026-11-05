"""The window drawing on printouts: its width and height in cm, the opening the customer ordered when given."""
import re

from app.modules.documents.render import drawing_svg

ELS = [{"type": "frame", "x_mm": 0, "y_mm": 0, "w_mm": 1495, "h_mm": 1195},
       {"type": "sash", "opening": "sliding_right", "x_mm": 0, "y_mm": 0, "w_mm": 747.5, "h_mm": 1195},
       {"type": "sash", "opening": "tilt", "x_mm": 747.5, "y_mm": 0, "w_mm": 747.5, "h_mm": 1195}]


def test_drawing_shows_its_size_in_cm():
    svg = str(drawing_svg(ELS, 1495, 1195, 140, 100))
    assert re.findall(r">([\d.]+) سم</text>", svg) == ["149.5", "119.5"]
    labelled = str(drawing_svg(ELS, 1495, 1195, 140, 100, label_w=1500, label_h=1200))
    assert re.findall(r">([\d.]+) سم</text>", labelled) == ["150", "120"]          # the opening, not the manufacturing size
    assert "سم" not in str(drawing_svg(ELS, 1495, 1195, 140, 100, dims=False))


def test_plain_tilt_has_only_its_triangle():
    svg = str(drawing_svg([ELS[2]], 747.5, 1195, 140, 100))
    assert svg.count('stroke-dasharray="3 2"') == 1                                  # no side-hung lines

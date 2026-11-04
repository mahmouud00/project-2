"""Window/door models from an Excel list, created in each chosen system: preview, all or nothing, codes already in a
system skipped, a drawing optional, and only the company's own systems."""
import io
import json

from openpyxl import Workbook

from tests.library_helpers import build_library

DRAW = [{"type": "frame", "w": "width", "h": "height"},
        {"type": "sash", "opening": "sliding_right", "x": "0", "y": "0", "w": "width / 2", "h": "height"},
        {"type": "sash", "opening": "sliding_left", "x": "width / 2", "y": "0", "w": "width / 2", "h": "height"}]


def _book(rows, head=("الكود", "الاسم", "النوع", "الوصف", "الرسمة")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(head))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(client, h, data, systems, apply):
    q = "&".join(f"system_ids={s}" for s in systems)
    return client.post(f"/api/v1/library/models/import?apply={str(apply).lower()}&{q}", headers=h,
                       files={"file": ("m.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_import_models_into_several_systems(tenant_a, client):
    h = tenant_a.h
    a = build_library(client, tenant_a, code="MI-A", prefix="MIA-", publish=False)["system"]
    b = client.post("/api/v1/library/systems", headers=h, json={"code": "MI-B", "name": "b", "material_type": "upvc"}).json()
    data = _book([("W01", "شباك جرار ضلفتين", "شباك", "", json.dumps(DRAW)),
                  ("SL2", "شباك جرار (موجود)", "شباك", "", ""),        # SL2 is already a model of MI-A
                  ("D01", "باب مفصلي", "باب", "وصف", "")])
    pre = _post(client, h, data, [a["id"], b["id"]], False)
    assert pre.status_code == 200, pre.text
    p = pre.json()
    assert p["error_count"] == 0 and p["rows"] == 3
    assert {s["code"]: (s["new"], s["existing"]) for s in p["systems"]} == {"MI-A": (2, 1), "MI-B": (3, 0)}
    assert client.get("/api/v1/library/models", headers=h, params={"system_id": b["id"]}).json() == []  # preview only
    assert _post(client, h, data, [a["id"], b["id"]], True).json()["models_new"] == 5
    models = {m["code"]: m for m in client.get("/api/v1/library/models", headers=h, params={"system_id": b["id"]}).json()}
    assert set(models) == {"W01", "SL2", "D01"}
    assert models["D01"]["category"] == "door" and models["W01"]["status"] == "trial"
    assert len(models["W01"]["definition"]["drawing"]) == 3 and "pieces" not in models["W01"]["definition"]
    a_models = {m["code"]: m for m in client.get("/api/v1/library/models", headers=h, params={"system_id": a["id"]}).json()}
    assert a_models["SL2"]["name"] == "شباك جرار"                       # the existing model is not changed
    # the drawing is evaluated by the engine at the opening's size
    r = client.post(f"/api/v1/library/models/{models['W01']['id']}/check", headers=h)
    assert r.status_code == 200 and not [e for e in r.json()["errors"] if "drawing" in str(e).lower()], r.json()
    # importing again makes nothing new
    assert _post(client, h, data, [b["id"]], True).json()["models_new"] == 0


def test_model_import_is_all_or_nothing_and_reads_a_catalogue(tenant_a, client):
    h = tenant_a.h
    s = client.post("/api/v1/library/systems", headers=h, json={"code": "MI-C", "name": "c", "material_type": "upvc"}).json()
    bad = _book([("X1", "شباك", "شباك", "", ""), ("X1", "مكرر", "شباك", "", ""), ("X2", "رسمة غلط", "شباك", "", "{not json")])
    r = _post(client, h, bad, [s["id"]], True)
    assert r.status_code == 422 and r.json()["error"]["details"]["error_count"] == 2
    assert client.get("/api/v1/library/models", headers=h, params={"system_id": s["id"]}).json() == []
    # a plain product list (اسم المنتج / الفئة / الرقم المرجعي) works too: no type column means a window
    cat = _book([("شباك جرار بار 6", " كومبن UPVC", "W03KP")], head=("اسم المنتج", "الفئة", "الرقم المرجعي"))
    assert _post(client, h, cat, [s["id"]], True).json()["models_new"] == 1


def test_only_own_systems(platform, tenant_a, client):
    lib = build_library(client, platform, code="MI-LIB", prefix="MIL-", publish=False)["system"]
    r = _post(client, tenant_a.h, _book([("Z1", "شباك", "شباك", "", "")]), [lib["id"]], True)
    assert r.status_code == 403 and r.json()["error"]["code"] == "LIBRARY_READ_ONLY"

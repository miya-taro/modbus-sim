"""API 層（FastAPI）のスモーク／機能テスト。

旧 UI テスト（test_ui_smoke / test_register_kind_ui / test_bulk_register_operations /
test_delete_operations）の代替。HTTP 経由でレジスタ CRUD・範囲追加・取込・
サーバ起動停止を確認する。
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.datastore import rtu_registry, tcp_registry

_PORTS = itertools.count(18300)


@pytest.fixture
def client(tmp_path):
    # モジュールグローバルのレジストリを毎回初期化する
    for reg in (tcp_registry, rtu_registry):
        reg.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
    app = create_app(tmp_path / "settings.json")
    with TestClient(app) as c:
        yield c


def test_health_and_state(client):
    assert client.get("/api/health").json() == {"ok": True}
    state = client.get("/api/state").json()
    assert state["type"] == "state"
    assert state["tcp"]["selected_slave_id"] == 1
    assert "rtu" in state and "log" in state


def test_add_and_remove_slave(client):
    r = client.post("/api/slaves/tcp", json={"id": 5})
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["slaves"]] == [1, 5]

    # 重複はエラー
    assert client.post("/api/slaves/tcp", json={"id": 5}).status_code == 400
    # 範囲外
    assert client.post("/api/slaves/tcp", json={"id": 999}).status_code == 400

    r = client.delete("/api/slaves/tcp/5")
    assert [s["id"] for s in r.json()["slaves"]] == [1]
    # 最後の1件は消せない
    assert client.delete("/api/slaves/tcp/1").status_code == 400


def test_upsert_point_raw_and_decoded(client):
    r = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 10, "kind": "hr", "datatype": "uint16", "raw": 4660, "tag": "t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["raw"] == 4660
    assert body["decoded_hex"] == "0x1234"

    # decoded 入力（16進）
    r = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 10, "kind": "hr", "datatype": "int16", "decoded": "0xFFFF"},
    )
    assert r.json()["raw"] == 0xFFFF  # int16 の raw はメモリ表現

    points = client.get("/api/slaves/tcp/1/points", params={"kind": "hr"}).json()
    assert len(points) == 1 and points[0]["address"] == 10


def test_upsert_float64_point(client):
    r = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 100, "kind": "hr", "datatype": "float64", "raw": 3.141592653589793},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decoded_hex"] == "0x400921FB54442D18"
    assert abs(body["decoded"] - 3.141592653589793) < 1e-12

    # float64 は 4 レジスタ。65533 は不可
    bad = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 65533, "kind": "hr", "datatype": "float64", "raw": 1.0},
    )
    assert bad.status_code == 400


def test_range_add_and_delete(client):
    r = client.post(
        "/api/slaves/tcp/1/points/range",
        json={"start": 0, "count": 5, "kind": "hr", "datatype": "uint16", "raw": 7, "tag_prefix": "S"},
    )
    assert r.json() == {"added": 5, "errors": []}
    points = client.get("/api/slaves/tcp/1/points", params={"kind": "hr"}).json()
    assert [p["address"] for p in points] == [0, 1, 2, 3, 4]
    assert points[0]["tag"] == "S0"

    assert client.request(
        "DELETE", "/api/slaves/tcp/1/points/hr/2"
    ).status_code == 200
    points = client.get("/api/slaves/tcp/1/points", params={"kind": "hr"}).json()
    assert [p["address"] for p in points] == [0, 1, 3, 4]


def test_import_text(client):
    text = "Addr,Kind,Datatype,Raw,Tag\n0,coil,bool,1,c0\n1,hr,int32,-1,neg\n"
    r = client.post(
        "/api/slaves/tcp/1/points/import",
        json={"text": text, "active_kind": "hr"},
    )
    assert r.json()["added"] == 2
    coils = client.get("/api/slaves/tcp/1/points", params={"kind": "coil"}).json()
    assert coils[0]["raw"] == 1


def test_advanced_validation(client):
    bad = client.put(
        "/api/slaves/tcp/1/points",
        json={
            "address": 1, "kind": "hr", "datatype": "uint16", "raw": 0,
            "delay_min_ms": 100, "delay_max_ms": 50,
        },
    )
    assert bad.status_code == 400

    ok = client.put(
        "/api/slaves/tcp/1/points",
        json={
            "address": 1, "kind": "hr", "datatype": "uint16", "raw": 0,
            "auto_mode": "sine", "auto_min": 0, "auto_max": 100, "auto_period_sec": 2.0,
        },
    )
    assert ok.status_code == 200 and ok.json()["advanced"] is True


def test_float32_out_of_range_is_400_not_500(client):
    r = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 0, "kind": "hr", "datatype": "float32", "raw": 1e40},
    )
    assert r.status_code == 400
    assert "float32" in r.json()["detail"]
    # inf はビットパターンとして格納できるので許可
    ok = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 2, "kind": "hr", "datatype": "float32", "decoded": "0x7F800000"},
    )
    assert ok.status_code == 200


def test_multi_register_overlap_is_rejected(client):
    client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 10, "kind": "hr", "datatype": "float32", "raw": 1.5},
    )
    # addr 11 は float32@10 の下位ワード
    clash = client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 11, "kind": "hr", "datatype": "uint16", "raw": 7},
    )
    assert clash.status_code == 400
    assert "10" in clash.json()["detail"]

    # float64@20 は 20..23 を占有 → 23 に置けない
    client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 20, "kind": "hr", "datatype": "float64", "raw": 1.0},
    )
    assert client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 23, "kind": "hr", "datatype": "uint16", "raw": 1},
    ).status_code == 400

    # 自分自身の編集（addr 10 の tag 変更）は重複扱いにならない
    assert client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 10, "kind": "hr", "datatype": "float32", "tag": "x"},
    ).status_code == 200

    # 別 kind の同一 addr は独立なので OK
    assert client.put(
        "/api/slaves/tcp/1/points",
        json={"address": 11, "kind": "ir", "datatype": "uint16", "raw": 1},
    ).status_code == 200


def test_widening_datatype_onto_neighbor_is_rejected(client):
    client.put("/api/slaves/tcp/1/points",
               json={"address": 30, "kind": "hr", "datatype": "uint16", "raw": 1})
    client.put("/api/slaves/tcp/1/points",
               json={"address": 31, "kind": "hr", "datatype": "uint16", "raw": 2})
    # addr 30 を int32 化すると 31 と衝突
    r = client.put("/api/slaves/tcp/1/points",
                   json={"address": 30, "kind": "hr", "datatype": "int32", "raw": 1})
    assert r.status_code == 400


def test_server_start_stop(client):
    port = next(_PORTS)
    client.put("/api/settings", json={"tcp": {"host": "127.0.0.1", "port": port}})
    r = client.post("/api/server/tcp/start")
    assert r.status_code == 200, r.text
    assert r.json()["tcp_running"] is True
    r = client.post("/api/server/tcp/stop")
    assert r.json()["tcp_running"] is False

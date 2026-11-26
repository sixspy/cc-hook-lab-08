"""失败测甲：含密钥原文仍进现行摘要，本测必须红。

事故：入队把 api_key=sk_live_... 原文写进 事件.载荷摘要，事件队列与事件导出都能读到明文。
期望：入队落库即脱敏；现行摘要不含明文；摘要脱敏态/字段遮罩可读；明文回刷被拒。
"""
import os, tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.setdefault("数据目录", _tmp)
os.environ.setdefault("夹具目录", str(Path(__file__).resolve().parents[2] / "fixtures"))

import pytest

from app import seed
from app.db import 连接
from app.services import 入队, 签名目录, 夹具

明文清单 = ["sk_live_9001", "6222020200001234", "ghp_abcdef123456", "hunter2", "ord-908"]


def setup_module():
    seed.初始化库()


def _遮罩字段(v):
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [x for x in str(v or "").replace("，", ",").split(",") if x]


def _取事件(rows, eid):
    for r in rows:
        if r.get("事件号") == eid:
            return r
    return None


def test_含密钥载荷入队落库即脱敏():
    体 = 夹具.读取("灌带密钥字段的入队夹具")
    item = dict(体["事件"][0])
    ev = 入队.建事件(item)
    eid = ev["事件号"]

    assert ev["摘要脱敏态"] == "已脱敏", "入队回执必须直接给出摘要脱敏态"
    assert "sk_live_9001" not in str(ev["载荷摘要"]), "含密钥原文不得进现行摘要"
    assert "6222020200001234" not in str(ev["载荷摘要"])
    遮 = _遮罩字段(ev.get("遮罩字段"))
    assert "api_key" in 遮 and "card" in 遮, f"字段遮罩应列出密钥字段，实际 {遮}"
    assert ev.get("脱敏提示"), "页上要能直接读到中文脱敏提示"

    row = _取事件(签名目录.事件列表(), eid)
    assert row, "入队事件应在事件队列列表里"
    assert row["摘要脱敏态"] == "已脱敏"
    for 明文 in 明文清单:
        assert 明文 not in str(row["载荷摘要"]), f"事件列表泄露明文 {明文}"
    assert "***" in str(row["载荷摘要"])

    # 事件列表与事件详情同票：同一事件号摘要完全一致
    detail = 签名目录.事件一条(eid)
    assert detail["载荷摘要"] == row["载荷摘要"]
    assert detail["摘要脱敏态"] == row["摘要脱敏态"]


def test_夹具全量入队后列表无任何明文():
    体 = 夹具.读取("灌带密钥字段的入队夹具")
    for item in 体["事件"]:
        入队.建事件(dict(item))
    rows = 签名目录.事件列表()
    blob = "||".join(str(r.get("载荷摘要") or "") for r in rows)
    for 明文 in 明文清单:
        assert 明文 not in blob, f"事件列表泄露明文 {明文}"
    for r in rows:
        if r.get("事件类型") in ("invoice.paid", "user.created", "order.refund"):
            assert r.get("摘要脱敏态") in ("已脱敏", "待补档")


def test_拒明文回刷():
    体 = 夹具.读取("灌带密钥字段的入队夹具")
    ev = 入队.建事件(dict(体["事件"][0]))
    eid = ev["事件号"]
    with pytest.raises(ValueError):
        入队.改摘要(eid, "api_key=sk_live_9999&card=6222020200009999")
    # 快照与事件摘要都保持脱敏态，未被明文回刷
    detail = 签名目录.事件一条(eid)
    assert "sk_live_9999" not in str(detail["载荷摘要"])
    assert detail["摘要脱敏态"] == "已脱敏"

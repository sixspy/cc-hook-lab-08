"""失败测乙：事件详情对账把明文摘要当成已脱敏，本测必须红。

事故：旧库里已有含密钥原文的事件摘要，事件详情/互证对账仅凭一个状态位就认定「已脱敏」。
期望：事件详情给出真实摘要脱敏态与对账结论；对账影子只做联查，不混进事件/互证正式集合。
"""
import os, tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.setdefault("数据目录", _tmp)
os.environ.setdefault("夹具目录", str(Path(__file__).resolve().parents[2] / "fixtures"))

import pytest

from app import seed
from app.db import 连接
from app.services import 入队, 签名目录, 互证, 夹具
from app.services.时间 import 此刻


def setup_module():
    seed.初始化库()


def _植_旧事故事件():
    import uuid
    事件号 = f"EVT-mask-leak-{uuid.uuid4().hex[:8]}"
    原文 = "token=ghp_leak_777&user=u1"
    t = 此刻()
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 事件(事件号,事件类型,端点键,载荷摘要,优先级,状态,入队时,更新时) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (事件号, "user.created", "ep-notify", 原文, "普通", "待投", t, t),
        )
        conn.commit()
    finally:
        conn.close()
    return 事件号


def test_事件详情对账不把明文摘要当已脱敏():
    eid = _植_旧事故事件()
    detail = 签名目录.事件一条(eid)
    assert detail is not None
    # 详情不得把无快照/明文残留的摘要标成已脱敏
    assert detail["摘要脱敏态"] != "已脱敏", "无快照的明文摘要被误标为已脱敏"
    assert "ghp_leak_777" not in str(detail["载荷摘要"]), "事件详情不得回显明文"
    assert detail.get("摘要对账", {}).get("结论") == "失败", "详情对账应判失败"
    assert "明文" in str(detail["摘要对账"].get("说明", ""))

    # 互证跑一次必须带上摘要对账，且整体不得对齐
    报告 = 互证.跑一次()
    assert "摘要对账" in 报告, "互证必须联查摘要对账"
    assert 报告["摘要对账"]["是否通过"] is False
    assert 报告["是否对齐"] is False

    # 对账影子不得混进正式集合
    事件列表 = 签名目录.事件列表()
    assert all(r["事件号"] != "对账影子" for r in 事件列表)
    assert all("影子" not in str(r.get("事件类型")) for r in 事件列表)
    互证列表 = 签名目录.互证列表()
    # 只应增加本轮正式互证批次，不能出现影子批次
    assert all("影子" not in str(r.get("说明")) for r in 互证列表)

    # 正常入队的含密钥事件则应当通过对账
    体 = 夹具.读取("灌带密钥字段的入队夹具")
    ev = 入队.建事件(dict(体["事件"][1]))
    d2 = 签名目录.事件一条(ev["事件号"])
    assert d2["摘要脱敏态"] == "已脱敏"
    assert d2["摘要对账"]["结论"] == "通过"

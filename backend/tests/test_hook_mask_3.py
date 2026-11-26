"""争用失败测：入队与导出并发漏脱敏，争用失败测必须红。

事故：入队落库与事件导出/列表读取并发时，读侧拿到未脱敏的原文摘要（漏脱敏）。
期望：选定「独立快照表」形态——入队与脱敏同成同败，快照冻结脱敏规则指纹并拒明文回刷；
现行列表只读脱敏集，读侧永不见明文。本测用多线程并发打同一把锁/同一事务。
"""
import os, tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.setdefault("数据目录", _tmp)
os.environ.setdefault("夹具目录", str(Path(__file__).resolve().parents[2] / "fixtures"))

import threading

import pytest

from app import seed
from app.services import 入队, 签名目录


def setup_module():
    seed.初始化库()


明文 = ["sk_live_9001", "6222020200001234", "ghp_abcdef123456", "hunter2", "ord-908"]
含密载荷 = [
    "api_key=sk_live_9001&card=6222020200001234&金额=100",
    "token=ghp_abcdef123456&user=u42",
    "密码=hunter2&secret=ord-908&order=908",
]


def _载荷脱敏():
    import importlib
    try:
        return importlib.import_module("app.services.载荷脱敏")
    except ModuleNotFoundError:
        raise AssertionError("缺少 载荷脱敏 服务：独立快照表/规则指纹/拒绝明文回刷尚未落地")


def test_入队导出并发不漏脱敏():
    漏 = []
    锁 = threading.Lock()
    事件号集 = []

    def 入队线(载荷):
        try:
            ev = 入队.建事件({"事件类型": "并发.paid", "端点键": "ep-billing", "载荷摘要": 载荷})
            with 锁:
                事件号集.append(ev["事件号"])
        except Exception as e:  # 入队异常也不得放行明文
            with 锁:
                漏.append(f"入队异常:{e}")

    def 导出线():
        for _ in range(200):
            try:
                rows = 签名目录.事件列表()
            except Exception as e:
                with 锁:
                    漏.append(f"导出异常:{e}")
                continue
            blob = "||".join(str(r.get("载荷摘要") or "") for r in rows)
            for m in 明文:
                if m in blob:
                    with 锁:
                        漏.append(f"导出读到明文:{m}")
            if any(str(r.get("摘要脱敏态")) in ("未脱敏", "") for r in rows):
                with 锁:
                    漏.append("导出读到未脱敏态")

    th = [threading.Thread(target=入队线, args=(p,)) for p in 含密载荷 * 4]
    导出线程 = [threading.Thread(target=导出线) for _ in range(3)]
    for t in 导出线程:
        t.start()
    for t in th:
        t.start()
    for t in th:
        t.join()
    for t in 导出线程:
        t.join()

    assert not 漏, f"争用下漏脱敏：{漏[:5]}"

    assert 事件号集
    载荷脱敏 = _载荷脱敏()
    for eid in 事件号集:
        row = 签名目录.事件一条(eid)
        assert row["摘要脱敏态"] == "已脱敏"
        assert row["规则指纹"] == 载荷脱敏.规则指纹, "快照必须冻结脱敏规则指纹"
        assert 载荷脱敏.快照档(row["规则指纹"]), "独立快照表必须留有该指纹"
        for m in 明文:
            assert m not in str(row["载荷摘要"])


def test_快照冻结指纹且拒明文回刷():
    载荷脱敏 = _载荷脱敏()
    ev = 入队.建事件({"事件类型": "归档.paid", "端点键": "ep-billing", "载荷摘要": 含密载荷[0]})
    eid = ev["事件号"]

    现行 = 签名目录.事件一条(eid)["载荷摘要"]
    assert "sk_live_9001" not in 现行 and "***" in 现行

    快照 = 载荷脱敏.快照档(ev["规则指纹"])
    assert 快照["规则版本"] == 载荷脱敏.规则版本
    assert int(快照["只读"]) == 1, "快照表必须只读冻结"
    assert 快照["规则内容"] == 载荷脱敏.规则内容
    for m in 明文:  # 快照只存规则，绝不存载荷原文
        assert m not in str(快照)

    # 同一指纹重复入队，快照不漂移
    ev2 = 入队.建事件({"事件类型": "归档.paid", "端点键": "ep-billing", "载荷摘要": 含密载荷[1]})
    assert ev2["规则指纹"] == ev["规则指纹"]
    assert 载荷脱敏.快照档(ev2["规则指纹"])["建立时"] == 快照["建立时"]

    # 拒明文回刷现行摘要
    with pytest.raises(ValueError):
        入队.改摘要(eid, "token=ghp_new_888&user=u9")

"""双会话并发脚本：两个独立进程并发「入队」与「导出」打同一库同一把锁。

用法：  python scripts/并发双会话.py
断言：  导出（现行脱敏集）历次都不得出现密钥明文；入队回执一律已脱敏。
快照（独立快照表）只冻规则指纹、只读，绝不存载荷原文。
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["数据目录"] = tempfile.mkdtemp()
os.environ["夹具目录"] = str(ROOT / "fixtures")

明文 = ["sk_live_9001", "6222020200001234", "ghp_abcdef123456", "hunter2", "ord-908"]
含密载荷 = [
    "api_key=sk_live_9001&card=6222020200001234&金额=100",
    "token=ghp_abcdef123456&user=u42",
    "密码=hunter2&secret=ord-908&order=908",
]


def _入队会话(n: int, 回报):
    from app.services import 入队

    漏 = []
    for i in range(n):
        ev = 入队.建事件({"事件类型": "并发.paid", "端点键": "ep-billing", "载荷摘要": 含密载荷[i % len(含密载荷)]})
        if ev["摘要脱敏态"] != "已脱敏":
            漏.append(f"{ev['事件号']} 非已脱敏")
        for m in 明文:
            if m in ev["载荷摘要"]:
                漏.append(f"{ev['事件号']} 回执含明文 {m}")
    回报.put({"类型": "入队", "漏": 漏, "条数": n})


def _导出会话(n: int, 回报):
    from app.services import 签名目录

    漏 = []
    for _ in range(n):
        blob = json.dumps(签名目录.事件导出(), ensure_ascii=False)
        for m in 明文:
            if m in blob:
                漏.append(f"导出含明文 {m}")
        for r in 签名目录.事件列表():
            if r["摘要脱敏态"] != "已脱敏":
                漏.append(f"列表乱态 {r['事件号']}")
    回报.put({"类型": "导出", "漏": 漏, "轮数": n})


def main() -> int:
    from app import seed
    seed.初始化库()

    回报 = mp.Queue()
    集 = [mp.Process(target=_入队会话, args=(20, 回报)), mp.Process(target=_导出会话, args=(200, 回报))]
    for p in 集:
        p.start()
    for p in 集:
        p.join()

    结果 = [回报.get() for _ in 集]
    漏 = [x for r in 结果 for x in r["漏"]]
    总和 = sum(r.get("条数", 0) for r in 结果)

    状态 = "PASS" if not 漏 else "FAIL"
    print(json.dumps({"结论": 状态, "入队条数": 总和, "漏": 漏[:8], "明细": 结果}, ensure_ascii=False, indent=2))

    # 选定形态为「独立快照表」：快照只冻规则指纹，不存任何载荷原文，且只读。
    from app.services import 入队, 签名目录, 载荷脱敏
    ev = 入队.建事件({"事件类型": "归档.paid", "端点键": "ep-billing", "载荷摘要": 含密载荷[0]})
    现行 = 签名目录.事件一条(ev["事件号"])
    快照 = 载荷脱敏.快照档(ev["规则指纹"])
    一致 = (
        "sk_live_9001" not in 现行["载荷摘要"]
        and 快照 is not None
        and int(快照["只读"]) == 1
        and all(m not in str(快照) for m in 明文)
    )
    print(json.dumps({"快照只读": "PASS" if 一致 else "FAIL", "现行摘要": 现行["载荷摘要"],
                      "规则指纹": ev["规则指纹"]}, ensure_ascii=False, indent=2))
    return 0 if (not 漏 and 一致) else 1


if __name__ == "__main__":
    raise SystemExit(main())

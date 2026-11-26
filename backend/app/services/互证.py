from __future__ import annotations
from app.db import 连接
from app.services.时间 import 此刻
from app.services import 载荷脱敏


def 摘要对账批(conn=None) -> dict:
    """摘要脱敏对账影子：只做联查计算，不写事件表、不写互证批次等正式集合。"""
    own = conn is None
    if own:
        conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 事件号, 载荷摘要, 摘要脱敏态, 规则指纹 FROM 事件"
        ).fetchall()
    finally:
        if own:
            conn.close()

    泄露 = []
    待补档 = []
    缺快照 = []
    for r in rows:
        明文 = 载荷脱敏.含明文(r["载荷摘要"])
        if 明文 or r["摘要脱敏态"] == "待补档":
            待补档.append(r["事件号"])
        if 明文:
            泄露.append(r["事件号"])
        if not r["规则指纹"]:
            缺快照.append(r["事件号"])

    通过 = not 泄露 and not 缺快照 and len(待补档) == 0
    说明 = (
        "事件摘要均落在脱敏集，快照指纹齐全，对账通过"
        if 通过
        else f"对账失败：明文残留 {len(泄露)} 条，缺快照 {len(缺快照)} 条，待补档 {len(待补档)} 条"
    )
    return {
        "是否通过": 通过,
        "说明": 说明,
        "明文残留": 泄露,
        "待补档": 待补档,
        "缺快照": 缺快照,
        "规则版本": 载荷脱敏.规则版本,
        "规则指纹": 载荷脱敏.规则指纹,
        "影子": True,
    }


def 跑一次() -> dict:
    t = 此刻()
    conn = 连接()
    try:
        总 = conn.execute("SELECT COUNT(*) AS c FROM 事件").fetchone()["c"]
        已 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='已投递'").fetchone()["c"]
        死 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='死信'").fetchone()["c"]
        待 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态 IN ('待投','投递中')").fetchone()["c"]
        匣 = conn.execute("SELECT COUNT(*) AS c FROM 死信 WHERE 状态='待处置'").fetchone()["c"]
        对账 = 摘要对账批(conn)
        水位对齐 = (死 == 匣 and 已 + 死 + 待 <= 总)
        对齐 = bool(水位对齐 and 对账["是否通过"])
        if 对齐:
            说明 = "事件/投递/死信口径对齐，摘要脱敏对账通过"
        elif not 水位对齐:
            说明 = "死信匣与事件死信数不一致或水位异常"
        else:
            说明 = "水位对齐但摘要脱敏对账失败：" + 对账["说明"]
        conn.execute(
            "INSERT INTO 互证批次(时刻,事件总数,已投递数,死信数,待投数,是否对齐,说明) VALUES (?,?,?,?,?,?,?)",
            (t, 总, 已, 死, 待, 1 if 对齐 else 0, 说明),
        )
        conn.commit()
        return {
            "时刻": t,
            "事件总数": 总,
            "已投递数": 已,
            "死信数": 死,
            "待投数": 待,
            "死信匣待处置": 匣,
            "是否对齐": 对齐,
            "是否全部对齐": 对齐,
            "说明": 说明,
            "摘要对账": 对账,
            "明细": {"总": 总, "已": 已, "死": 死, "待": 待, "匣": 匣},
        }
    finally:
        conn.close()

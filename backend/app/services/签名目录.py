from __future__ import annotations
from app.db import 连接
from app.services import 校验


def 签名规() -> dict:
    conn = 连接()
    try:
        rows = conn.execute("SELECT 键,值 FROM 签名规").fetchall()
        return {r["键"]: r["值"] for r in rows}
    finally:
        conn.close()


def 改签名规(body: dict) -> dict:
    conn = 连接()
    try:
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
            )
        conn.commit()
        return 签名规()
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql):
            return conn.execute(sql).fetchone()[0]
        return {
            "端点数": c("SELECT COUNT(*) FROM 投递端点"),
            "启用端点": c("SELECT COUNT(*) FROM 投递端点 WHERE 启用=1"),
            "事件总数": c("SELECT COUNT(*) FROM 事件"),
            "待投": c("SELECT COUNT(*) FROM 事件 WHERE 状态='待投'"),
            "投递中": c("SELECT COUNT(*) FROM 事件 WHERE 状态='投递中'"),
            "已投递": c("SELECT COUNT(*) FROM 事件 WHERE 状态='已投递'"),
            "死信": c("SELECT COUNT(*) FROM 事件 WHERE 状态='死信'"),
            "尝试数": c("SELECT COUNT(*) FROM 投递尝试"),
            "死信匣": c("SELECT COUNT(*) FROM 死信 WHERE 状态='待处置'"),
            "已脱敏": c("SELECT COUNT(*) FROM 事件 WHERE 摘要脱敏态='已脱敏'"),
            "待补档": c("SELECT COUNT(*) FROM 事件 WHERE 摘要脱敏态<>'已脱敏'"),
            "签名规": 签名规(),
        }
    finally:
        conn.close()


def 事件列表() -> list:
    conn = 连接()
    try:
        rows = conn.execute("SELECT * FROM 事件 ORDER BY 入队时 DESC").fetchall()
    finally:
        conn.close()
    from app.services import 载荷脱敏
    return [载荷脱敏.修饰事件(r) for r in rows]


def 事件一条(事件号: str) -> dict | None:
    from app.services import 载荷脱敏
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not row:
            return None
        d = 载荷脱敏.修饰事件(row)
        d["尝试"] = [dict(x) for x in conn.execute(
            "SELECT * FROM 投递尝试 WHERE 事件号=? ORDER BY 投递时 DESC", (事件号,)
        ).fetchall()]
        dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
        d["死信"] = dict(dl) if dl else None
        return d
    finally:
        conn.close()


def 事件导出() -> dict:
    """导出与列表同票：两处都只读脱敏集，导出永不带明文。"""
    rows = 事件列表()
    return {
        "条数": len(rows),
        "读引用": "现行脱敏集",
        "导出": [
            {
                "事件号": r["事件号"],
                "事件类型": r["事件类型"],
                "端点键": r["端点键"],
                "载荷摘要": r["载荷摘要"],
                "摘要脱敏态": r["摘要脱敏态"],
                "遮罩字段": r["遮罩字段"],
            }
            for r in rows
        ],
    }


def 投递列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 投递尝试 ORDER BY 投递时 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 投递一条(尝试号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 投递尝试 WHERE 尝试号=?", (尝试号,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 死信列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 死信 ORDER BY 入匣时 DESC").fetchall()]
    finally:
        conn.close()


def 端点列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 投递端点 ORDER BY 端点键").fetchall()]
    finally:
        conn.close()


def 互证列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 互证批次 ORDER BY 批次号 DESC LIMIT 50").fetchall()]
    finally:
        conn.close()

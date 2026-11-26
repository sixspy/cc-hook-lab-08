from __future__ import annotations
import uuid
from app.db import 连接
from app.services import 校验, 载荷脱敏
from app.services.时间 import 此刻


def 建事件(body: dict) -> dict:
    类型 = 校验.非空("事件类型", body.get("事件类型"))
    端点键 = 校验.非空("端点键", body.get("端点键"))
    原文 = str(body.get("载荷摘要") or "")
    优先级 = str(body.get("优先级") or "普通")
    事件号 = str(body.get("事件号") or f"EVT-{uuid.uuid4().hex[:10]}")
    t = 此刻()
    conn = 连接()
    try:
        # 与写入同成同败：先冻快照、再算脱敏，任一步异常回滚整笔事务。
        conn.execute("PRAGMA foreign_keys = ON")
        快照 = 载荷脱敏.建快照(conn)
        摘要, 命中 = 载荷脱敏.遮罩(原文)
        遮罩字段 = 载荷脱敏.遮罩字段串(命中)
        if 载荷脱敏.含明文(摘要):
            raise ValueError("载荷摘要脱敏失败，拒绝以明文落库")
        ep = conn.execute("SELECT * FROM 投递端点 WHERE 端点键=?", (端点键,)).fetchone()
        if not ep:
            raise ValueError("端点不存在")
        if int(ep["启用"]) != 1:
            raise ValueError("端点已停用，拒绝入队")
        if conn.execute("SELECT 1 FROM 事件 WHERE 事件号=?", (事件号,)).fetchone():
            raise ValueError("事件号已存在")
        conn.execute(
            "INSERT INTO 事件(事件号,事件类型,端点键,载荷摘要,优先级,状态,入队时,更新时,"
            "摘要脱敏态,遮罩字段,规则指纹,脱敏提示) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (事件号, 类型, 端点键, 摘要, 优先级, "待投", t, t,
             "已脱敏", 遮罩字段, 快照["规则指纹"], 载荷脱敏.提示(命中, True)),
        )
        conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                     (t, "入队", 事件号, f"脱敏:{快照['规则指纹']}"))
        conn.commit()
        return 载荷脱敏.修饰事件(conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone())
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 改摘要(事件号: str, 载荷摘要: str) -> dict:
    """改摘要只接受脱离敏态的文本；明文回刷一律拒绝（快照冻结后不得用原文回刷现行集合）。"""
    原文 = str(载荷摘要 or "")
    if 载荷脱敏.含明文(原文):
        raise ValueError("拒绝明文回刷：摘要含密钥明文，未附脱敏快照")
    摘要, 命中 = 载荷脱敏.遮罩(原文)
    conn = 连接()
    try:
        快照 = 载荷脱敏.建快照(conn)
        row = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not row:
            raise ValueError("无此事件")
        指纹 = 快照["规则指纹"]
        if row["规则指纹"] and row["规则指纹"] != 指纹:
            指纹 = row["规则指纹"]  # 冻结：沿用事件建档时的快照指纹
        conn.execute(
            "UPDATE 事件 SET 载荷摘要=?, 摘要脱敏态=?, 遮罩字段=?, 规则指纹=?, 脱敏提示=?, 更新时=? "
            "WHERE 事件号=?",
            (摘要, "已脱敏", 载荷脱敏.遮罩字段串(命中), 指纹,
             载荷脱敏.提示(命中, True), 此刻(), 事件号),
        )
        conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                     (此刻(), "改摘要", 事件号, f"脱敏:{指纹}"))
        conn.commit()
        return 载荷脱敏.修饰事件(conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone())
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

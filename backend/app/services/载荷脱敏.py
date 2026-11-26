"""载荷脱敏：入队落库前把密钥字段遮罩成 ***，独立快照表冻结脱敏规则指纹（只读）。

工程形态择定：**独立快照表**（非双写两轨）。
- 脱敏与写入同成同败：入队事务内建快照 + 写脱敏后的现行摘要，任一步失败整笔回滚。
- 快照只冻规则指纹与规则内容，不存任何载荷原文，且只读，拒明文回刷。
- 现行摘要/事件列表/事件详情只读脱敏集；对账影子只在联查时计算，不落正式集合。
"""
from __future__ import annotations

import hashlib
import re

from app.db import 连接
from app.services.时间 import 此刻

规则版本 = "mask-v1"

# 敏感字段名（小写比较）。命中的值一律遮罩为 ***。
敏感字段 = (
    "api_key", "apikey", "api-key", "access_token", "token", "secret",
    "password", "passwd", "pwd", "密码", "口令", "密钥", "secret_key",
    "card", "card_no", "卡号", "cardnumber", "authorization", "cookie",
)

# 字段抽取：key=value，支持 & , ， ; ； 分隔。
_字段 = re.compile(r"([A-Za-z0-9_\-\.一-鿿]+)\s*=\s*([^&,，;；\s]*)")
_遮罩值 = "***"

规则内容 = "敏感字段=" + ",".join(敏感字段) + "；遮罩=" + _遮罩值 + "；分隔=&,，;；"
规则指纹 = hashlib.sha256(f"{规则版本}|{规则内容}".encode("utf-8")).hexdigest()[:32]


def _是敏感(字段名: str) -> bool:
    k = str(字段名 or "").strip().lower().replace("-", "_")
    return k in {x.lower().replace("-", "_") for x in 敏感字段}


def _拆(载荷: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _字段.finditer(str(载荷 or ""))]


def 遮罩(载荷: str) -> tuple[str, list[str]]:
    """返回 (脱敏后文本, 命中字段列表)。已遮罩的 *** 不会重复处理。"""
    原 = str(载荷 or "")
    命中: list[str] = []
    if not 原:
        return 原, 命中

    def 替换(m: re.Match) -> str:
        字段名, 值 = m.group(1), m.group(2)
        if _是敏感(字段名) and 值 and 值 != _遮罩值:
            命中.append(字段名)
            return f"{字段名}={_遮罩值}"
        return m.group(0)

    脱敏 = _字段.sub(替换, 原)
    return 脱敏, 命中


def 含明文(载荷: str) -> bool:
    """现行摘要是否残留明文密钥值（敏感字段且值未被遮罩）。"""
    for 字段名, 值 in _拆(载荷):
        if _是敏感(字段名) and 值 and 值 != _遮罩值:
            return True
    return False


def 遮罩字段串(字段: list[str]) -> str:
    seen = []
    for x in 字段:
        if x not in seen:
            seen.append(x)
    return ",".join(seen)


def 提示(字段: list[str], 已脱敏: bool) -> str:
    if 已脱敏:
        if 字段:
            return f"已按 {规则版本} 脱敏 {len(字段)} 个密钥字段（{遮罩字段串(字段)}），明文未落现行摘要"
        return f"已按 {规则版本} 核验，摘要不含密钥字段明文"
    return f"摘要仍含密钥明文或缺少快照，已拒绝按明文回刷；待用 {规则版本} 补档"


def 建快照(conn=None) -> dict:
    """写入（或复用）当前规则指纹的只读快照。可传入事务连接以与入队同成同败。"""
    own = conn is None
    if own:
        conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 脱敏快照(规则指纹,规则版本,规则内容,只读,建立时) VALUES (?,?,?,?,?) "
            "ON CONFLICT(规则指纹) DO NOTHING",
            (规则指纹, 规则版本, 规则内容, 1, 此刻()),
        )
        row = conn.execute("SELECT * FROM 脱敏快照 WHERE 规则指纹=?", (规则指纹,)).fetchone()
        out = dict(row) if row else {}
        if own:
            conn.commit()
        return out
    finally:
        if own:
            conn.close()


def 快照档(指纹: str | None = None) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute(
            "SELECT * FROM 脱敏快照 WHERE 规则指纹=?", (指纹 or 规则指纹,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql, *a):
            return conn.execute(sql, a).fetchone()[0]

        明文残留 = [
            r["事件号"]
            for r in conn.execute("SELECT 事件号, 载荷摘要 FROM 事件").fetchall()
            if 含明文(r["载荷摘要"])
        ]
        待补档 = [
            r["事件号"]
            for r in conn.execute(
                "SELECT 事件号, 载荷摘要, 摘要脱敏态 FROM 事件"
            ).fetchall()
            if str(r["摘要脱敏态"] or "") != "已脱敏"
        ]
        return {
            "规则版本": 规则版本,
            "规则指纹": 规则指纹,
            "规则内容": 规则内容,
            "快照数": c("SELECT COUNT(*) FROM 脱敏快照"),
            "已脱敏": c("SELECT COUNT(*) FROM 事件 WHERE 摘要脱敏态='已脱敏'"),
            "待补档": len(待补档),
            "含明文残留": len(明文残留),
            "明文残留事件": 明文残留,
            "只读快照": bool(快照档(规则指纹) and int(快照档(规则指纹)["只读"]) == 1),
        }
    finally:
        conn.close()


def 修饰事件(row) -> dict:
    """读侧脱敏：现行列表/详情同票。任何残留明文都在读出前遮罩。"""
    d = dict(row)
    原 = str(d.get("载荷摘要") or "")
    脱敏, 命中 = 遮罩(原)
    已脱敏 = (
        str(d.get("摘要脱敏态") or "") == "已脱敏"
        and not 含明文(原)
        and bool(d.get("规则指纹"))
    )
    d["载荷摘要"] = 脱敏
    d["摘要脱敏态"] = "已脱敏" if 已脱敏 else "待补档"
    d["遮罩字段"] = str(d.get("遮罩字段") or 遮罩字段串(命中))
    d["脱敏提示"] = str(d.get("脱敏提示") or 提示(命中, 已脱敏))
    if not d["规则指纹"]:
        d["规则指纹"] = 规则指纹 if 已脱敏 else ""
    d["摘要对账"] = {
        "结论": "通过" if 已脱敏 else "失败",
        "规则指纹": d.get("规则指纹") or "",
        "命中明文": 含明文(原),
        "说明": (
            f"快照指纹 {d['规则指纹']} 已冻结，现行摘要为脱敏集"
            if 已脱敏
            else "现行摘要仍含明文或缺少独立快照指纹，对账判失败，不得当作已脱敏"
        ),
    }
    return d


def 补档(conn, 事件号: str, 原摘要: str) -> tuple[str, str, str, str]:
    """迁移旧行：能安全判定无密钥则盖已脱敏章；含明文则改写成遮罩并记待补档，拒回刷。"""
    脱敏, 命中 = 遮罩(原摘要)
    明文 = 含明文(原摘要)
    if 明文:
        return 脱敏, "待补档", str(规则指纹), 提示(命中, False)
    return 脱敏, "已脱敏", str(规则指纹), 提示(命中, True)

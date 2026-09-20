import hashlib

CATEGORIES = {
    "年报": ["年度报告"],
    "半年报": ["半年度报告"],
    "季报": ["季度报告"],
    "业绩预告": ["业绩预告"],
    "业绩快报": ["业绩快报"],
    "股东减持": ["减持"],
    "股东增持": ["增持"],
    "回购": ["回购"],
    "股权激励": ["股权激励", "限制性股票"],
    "股权质押": ["质押"],
    "机构调研": ["调研", "投资者关系"],
    "重大合同": ["重大合同"],
    "中标": ["中标"],
    "对外投资": ["对外投资"],
    "收购": ["收购"],
    "诉讼": ["诉讼", "仲裁"],
    "监管问询": ["问询", "监管", "处罚"],
    "董监高变更": ["辞职", "聘任", "董事变更", "高级管理人员变更"],
}


def classify(rows: list[dict]) -> list[dict]:
    unique = {}
    for row in rows:
        row = dict(row)
        row["id"] = hashlib.sha256(
            (row.get("title", "") + row.get("url", "") + row.get("date", "")).encode()
        ).hexdigest()[:20]
        row["categories"] = [
            name
            for name, words in CATEGORIES.items()
            if any(word in row["title"] for word in words)
        ] or ["其他"]
        row["risk_flag"] = any(
            x in row["categories"] for x in ("股东减持", "股权质押", "诉讼", "监管问询")
        )
        row["analysis_scope"] = (
            "全文" if row.get("raw_text") else "仅标题，未读取原文；仅分析标题已明确事实。"
        )
        unique[row["id"]] = row
    return list(unique.values())

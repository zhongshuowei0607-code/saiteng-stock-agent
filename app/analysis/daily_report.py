import html
import json
from pathlib import Path
import markdown
DISCLAIMER = "本系统仅用于个人研究，不构成投资建议。"
SECTIONS = [("一、今日行情","market"),("二、技术趋势","trend"),("三、我的持仓","portfolio"),("四、盈亏情况","pnl"),("五、支撑位 / 压力位","levels"),("六、当前仓位观察状态","watch_zone"),("七、企稳评分","stabilization"),("八、公告","announcements"),("九、新闻","news"),("十、行业强弱","industry"),("十一、基本面变化","fundamental"),("十二、风险评分","risk"),("十三、AI总结","ai"),("十四、下一交易日重点观察","focus")]

def render_reports(report: dict, root: Path) -> tuple[Path,Path]:
    code=report["stock"]["code"][:6]
    folder=root/code; folder.mkdir(parents=True,exist_ok=True)
    pieces=[f'# {code} {report["stock"]["name"]}每日跟踪报告',f'生成日期：{report["date"]}；行情日期：{report.get("market",{}).get("date","缺失")}',"数据状态："+"；".join(report.get("warnings",[]))]
    values={**report,"pnl":{k:report["portfolio"].get(k) for k in ("market_value","pnl","pnl_pct")},"focus":report.get("ai",{}).get("next_day_focus",["核对行情日期、企稳信号和公告原文；数据不足的项目暂不判断。"])}
    for title,key in SECTIONS:
        value=values.get(key)
        pieces.extend(["## "+title,"```json\n"+json.dumps(value,ensure_ascii=False,indent=2)+"\n```" if value else "数据不足，无法判断。"])
    pieces.extend(["## 昨日观点对比","```json\n"+json.dumps(report.get("comparison",{}),ensure_ascii=False,indent=2)+"\n```","## 十五、免责声明",DISCLAIMER])
    text="\n\n".join(pieces)
    md=folder/(report["date"]+".md"); page=folder/(report["date"]+".html")
    md.write_text(text,encoding="utf-8")
    # 先转义全部外部文本，Markdown 围栏也不能成为 HTML 注入通道。
    body=markdown.markdown(html.escape(text),extensions=["fenced_code"])
    page.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>赛腾股份日报</title><style>body{max-width:1000px;margin:40px auto;padding:20px;font:16px/1.7 system-ui;color:#203040}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:20px;border-radius:8px}h2{border-bottom:1px solid #ccd5df}</style>'+body+'</html>',encoding="utf-8")
    return md,page

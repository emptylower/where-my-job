# src/where_my_job/panel/timeline.py
"""时间线 tab 的 HTML 片段：只含受控字段（流、类型、发生时间、主体、声明版本、声明字段、根/当前 ID），全部按文本转义。
片段在 render_html 的唯一一次模板替换中作为 {{TIMELINE}} 的值插入，之后不再被扫描。"""
from __future__ import annotations
import json
from html import escape

# 与子计划 02 Task 8 固定脚本的分组页切换约定一致：按钮 data-tab-target=<名>，section data-tab=<名>，脚本只切换 hidden
TIMELINE_TAB_BUTTON = '<button type="button" data-tab-target="timeline">时间线</button>'

def _value_text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

def render_section(rows: list[dict], meta: list[dict]) -> str:
    out = ['<section data-tab="timeline" class="tab" hidden>', "<h2>时间线</h2>", '<ul class="timeline-meta">']
    for m in meta:
        state = "未注册" if not m["registered"] else ("已截断" if m["truncated"] else "完整")
        out.append(f"<li>{escape(m['stream'])}：显示 {int(m['shown'])} / {int(m['total'])}（{state}）</li>")
    out.append("</ul>")
    out.append("<table><thead><tr><th>发生时间</th><th>流</th><th>类型</th><th>主体</th><th>版本</th><th>字段</th><th>ID</th></tr></thead><tbody>")
    for e in rows:
        fields = "; ".join(
            f"{escape(str(k))}={escape(_value_text(v['value']))}" if v["present"] else f"{escape(str(k))}=<em>该条未提供</em>"
            for k, v in e["fields"].items())
        ids = escape(e["root_event_id"]) + (f" → {escape(e['current_event_id'])}" if e["corrected"] else "")
        out.append("<tr>"
                   f"<td>{escape(e['occurred_at'])}</td><td>{escape(e['stream'])}</td><td>{escape(e['type'])}</td>"
                   f"<td>{escape(e['subject_kind'])}:{escape(str(e['subject_id'] or ''))}</td>"
                   f"<td>{int(e['stream_revision'])}</td><td>{fields}</td><td><code>{ids}</code></td></tr>")
    out.append("</tbody></table>")
    if not rows:
        out.append("<p>没有有效事件</p>")
    out.append("</section>")
    return "\n".join(out)

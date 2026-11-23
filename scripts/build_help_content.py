"""把 docs/guide 下的单一信息源生成到应用与可阅读文档。

输入：
  docs/guide/content.json      功能手册、术语表、反馈渠道、关于作者
  docs/guide/error-codes.json  错误码注册表
  version.py                   版本号

输出：
  v3/public/help-content.js    应用直接 import 的静态内容
  docs/guide/使用手册.md        人读版手册（与界面同源）
  docs/guide/错误码表.md        人读版错误码表

运行：python scripts/build_help_content.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
PUBLIC = ROOT / "v3" / "public"


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)} 必须是 JSON 对象")
    return data


def read_version() -> str:
    text = (ROOT / "version.py").read_text(encoding="utf-8")
    match = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    if not match:
        raise ValueError("version.py 里找不到 VERSION")
    return match.group(1)


def validate(content: dict, errors: dict) -> None:
    required = {"title", "subtitle", "sections", "errorsIntro", "feedback", "about"}
    missing = required - set(content)
    if missing:
        raise ValueError(f"content.json 缺少字段：{', '.join(sorted(missing))}")
    seen_sections: set[str] = set()
    seen_features: set[str] = set()
    for section in content["sections"]:
        sid = section.get("id")
        if not sid or sid in seen_sections:
            raise ValueError(f"重复的章节 id：{sid}")
        seen_sections.add(sid)
        for feature in section.get("features", []):
            fid = feature.get("id")
            if not fid or fid in seen_features:
                raise ValueError(f"重复的条目 id：{fid}")
            seen_features.add(fid)
            for code in feature.get("errorCodes", []):
                if code not in errors:
                    raise ValueError(f"条目 {fid} 引用了未注册错误码 {code}")
    for code, entry in errors.items():
        for field in ("title", "cause", "action", "owner", "status"):
            if field not in entry:
                raise ValueError(f"错误码 {code} 缺少字段 {field}")


def render_markdown(content: dict, errors: dict, version: str) -> str:
    lines = [f"# {content['title']}", "", f"> {content['subtitle']}", "", f"版本：{version}", ""]
    lines += ["## 目录", ""]
    for section in content["sections"]:
        anchor = section["id"]
        lines.append(f"- [{section['title']}](#{anchor})")
    lines += ["- [错误码索引](#errors)", "- [反馈与支持](#feedback)", "- [关于作者与项目来源](#about)", ""]

    for section in content["sections"]:
        lines += ["", f"<a id=\"{section['id']}\"></a>", "", f"## {section['title']}", "", section.get("lead", "")]
        for feature in section.get("features", []):
            lines += ["", f"### {feature['title']}", ""]
            if feature.get("plain"):
                lines += [feature["plain"], ""]
            if feature.get("when"):
                lines += [f"**什么时候用：** {feature['when']}", ""]
            if feature.get("route"):
                lines += [f"对应页面：`{feature['route']}`", ""]
            if feature.get("steps"):
                lines += ["**一步一步做**", ""]
                lines += [f"{i}. {step}" for i, step in enumerate(feature["steps"], 1)] + [""]
            if feature.get("explain"):
                lines += ["**这里面的门道**", ""] + [f"- {item}" for item in feature["explain"]] + [""]
            if feature.get("tips"):
                lines += ["**小提醒**", ""] + [f"- {item}" for item in feature["tips"]] + [""]
            if feature.get("faq"):
                lines += ["**常见问题**", ""]
                for item in feature["faq"]:
                    lines += [f"- **{item['q']}** {item['a']}"]
                lines.append("")
            if feature.get("issues"):
                lines += ["**已知限制**", ""] + [f"- {item}" for item in feature["issues"]] + [""]
            if feature.get("errorCodes"):
                lines += ["**相关错误码**", "", "、".join(f"`{code}`" for code in feature["errorCodes"]), ""]

    lines += ["", "<a id=\"errors\"></a>", "", "## 错误码索引", "", content.get("errorsIntro", ""), ""]
    lines += ["| 错误码 | 是什么问题 | 常见原因 | 你可以怎么做 | 代码位置 | 状态 |", "| :-- | :-- | :-- | :-- | :-- | :-- |"]
    for code, entry in errors.items():
        lines.append(
            f"| `{code}` | {entry['title']} | {entry['cause']} | {entry['action']} | `{entry['owner']}` | {entry['status']} |"
        )

    feedback = content["feedback"]
    lines += ["", "<a id=\"feedback\"></a>", "", "## 反馈与支持", "",
              feedback["channel"] + "：" + feedback.get("channelValue", ""), ""]
    if feedback.get("groupNumber"):
        lines += [f"群号：`{feedback['groupNumber']}`", "", "![赛训工具群二维码](assets/qq-group-qr.jpg)", ""]
    lines += [feedback.get("intro", ""), "", "```text", feedback.get("template", ""), "```", ""]
    lines += [f"- {item}" for item in feedback.get("privacy", [])]

    about = content["about"]
    lines += ["", "<a id=\"about\"></a>", "", "## 关于作者与项目来源", "",
              f"**作者**：{about.get('author', '')}", "", about.get("origin", ""), "", "**设计原则**", ""]
    lines += [f"- {item}" for item in about.get("principles", [])]
    lines += ["", "**链接**", ""] + [f"- [{link['label']}]({link['url']})" for link in about.get("links", [])]
    return "\n".join(lines) + "\n"


def render_errors_markdown(errors: dict) -> str:
    lines = ["# 错误码表", "", "错误码一旦发布就不要改语义。界面文案可以调整，码本身保持不变。", "",
             "| 错误码 | 标题 | 原因 | 用户处置 | 代码位置 | 状态 |", "| :-- | :-- | :-- | :-- | :-- | :-- |"]
    for code, entry in errors.items():
        lines.append(
            f"| `{code}` | {entry['title']} | {entry['cause']} | {entry['action']} | `{entry['owner']}` | {entry['status']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    content = read_json(GUIDE / "content.json")
    errors = read_json(GUIDE / "error-codes.json")
    version = read_version()
    validate(content, errors)
    payload = {"version": version, "source": "docs/guide/content.json", **content, "errors": errors}

    (PUBLIC / "help-content.js").write_text(
        "/* 由 scripts/build_help_content.py 生成，请勿手改；编辑 docs/guide/content.json。 */\n"
        "export const helpContent = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    (GUIDE / "使用手册.md").write_text(render_markdown(content, errors, version), encoding="utf-8")
    (GUIDE / "错误码表.md").write_text(render_errors_markdown(errors), encoding="utf-8")
    print(f"已生成帮助内容 v{version}：{len(content['sections'])} 个章节，{len(errors)} 个错误码")


if __name__ == "__main__":
    main()

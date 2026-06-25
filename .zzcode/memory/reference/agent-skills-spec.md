---
type: reference
description: Anthropic Agent Skills 规范摘要 — SKILL.md 格式、目录结构、元数据字段
---

# Agent Skills 规范参考

来源：https://agentskills.io/specification

## 目录结构

```
skill-name/
├── SKILL.md          # 必需：YAML 元数据 + Markdown 指令
├── scripts/          # 可选：可执行脚本
├── references/       # 可选：参考文档
├── assets/           # 可选：模板、资源
└── ...
```

## SKILL.md 元数据字段

| 字段 | 必需 | 约束 |
|------|------|------|
| `name` | 是 | 最长 64 字符，小写字母+数字+连字符，不能以连字符开头/结尾，不能有连续连字符，必须匹配父目录名 |
| `description` | 是 | 最长 1024 字符，描述技能用途及何时使用 |
| `license` | 否 | 许可证名称或引用 |
| `compatibility` | 否 | 最长 500 字符，环境要求 |
| `metadata` | 否 | 任意键值映射 |
| `allowed-tools` | 否 | 空格分隔的预批准工具列表（实验性） |

## 渐进式加载

- 元数据（~100 tokens）：启动时加载所有技能的 name 和 description
- 指令（<5000 tokens 推荐）：技能激活时加载完整 SKILL.md
- 资源文件：按需加载

## 建议

- SKILL.md 不超过 500 行，详细内容拆分到 references/
- 文件引用使用相对路径，保持一层深度
- 使用 `skills-ref validate` 验证格式

---
type: project
description: 在 tests/zzcode_test 下创建了 jd-analyzer 技能，包含 SKILL.md、辅助脚本、参考文档和报告模板
---

# jd-analyzer 技能创建

在 `tests\zzcode_test\jd-analyzer\` 下创建了完整的职位描述分析技能。

## 技能结构

```
jd-analyzer/
├── SKILL.md                    # 核心技能定义（5步分析法）
├── scripts/
│   └── analyze_jd.py           # Python 辅助脚本
├── references/
│   └── REFERENCE.md            # 参考文档（级别判断、薪资参考、关键词分类）
└── assets/
    └── report_template.md      # 分析报告模板
```

## 技能元数据

- **名称**: `jd-analyzer`
- **描述**: 分析招聘职位描述（JD），提取关键信息并生成结构化分析报告
- **作者**: ZzCode
- **版本**: 1.0.0
- **类别**: 人力资源
- **许可证**: MIT

## 分析流程（5步法）

1. 提取基本信息（职位名称、公司、地点、薪资、发布时间）
2. 分析核心职责（按优先级排序，区分日常/项目型职责）
3. 分析任职要求（硬性要求、软性要求、加分项、技术栈）
4. 生成结构化 Markdown 分析报告
5. 给出求职建议、技能差距分析和面试准备方向

## 辅助脚本

`scripts/analyze_jd.py` 支持从文本中自动提取基本信息和识别技术栈关键词。

## 创建时间

2026-06-24

#!/usr/bin/env python3
"""
JD Analyzer — 职位描述分析辅助脚本
用法: python analyze_jd.py <jd_text_file>
"""

import sys
import json
import re
from pathlib import Path


def extract_basic_info(text: str) -> dict:
    """提取基本信息"""
    info = {
        "职位名称": "",
        "公司名称": "",
        "工作地点": "",
        "薪资范围": "",
        "发布时间": "",
    }

    # 简单的正则匹配示例
    patterns = {
        "职位名称": r"(?:职位|岗位|招聘)[：:]\s*(.+)",
        "公司名称": r"(?:公司|企业)[：:]\s*(.+)",
        "工作地点": r"(?:地点|工作地|城市)[：:]\s*(.+)",
        "薪资范围": r"(?:薪资|薪酬|工资)[：:]\s*([\dKk\-万]+)",
        "发布时间": r"(?:发布|发布日期)[：:]\s*(.+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            info[key] = match.group(1).strip()

    return info


def extract_tech_stack(text: str) -> list:
    """提取技术栈关键词"""
    tech_keywords = [
        "Python", "Java", "Go", "Rust", "C++", "JavaScript", "TypeScript",
        "React", "Vue", "Angular", "Node.js", "Django", "Flask", "Spring",
        "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch",
        "Docker", "Kubernetes", "AWS", "Azure", "GCP",
        "Git", "Linux", "Nginx", "Kafka", "RabbitMQ",
    ]
    found = []
    for tech in tech_keywords:
        if tech.lower() in text.lower():
            found.append(tech)
    return found


def analyze_jd(file_path: str) -> dict:
    """分析 JD 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    basic_info = extract_basic_info(text)
    tech_stack = extract_tech_stack(text)

    return {
        "basic_info": basic_info,
        "tech_stack": tech_stack,
        "text_length": len(text),
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_jd.py <jd_text_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not Path(file_path).exists():
        print(f"错误: 文件不存在 - {file_path}")
        sys.exit(1)

    result = analyze_jd(file_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

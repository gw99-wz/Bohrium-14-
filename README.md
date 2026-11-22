# Bohrium-14- · 阅读14｜Nanopublication

参赛作品仓库：玻尔（Bohrium）Playground 产品分站赛「阅读14｜Nanopublication」赛题（Challenge ID `product-arena-09-0e8befd4`）。

本仓库用于放置一个**可被 Agent 调用的 Skill**，把真实论文中的段落拆成可独立判断真假的科研断言，为每条断言绑定最小充分证据片段与原文位置，并输出可机器读取的结构化结果。

> 状态：仓库骨架已建立，Skill 实现进行中。本文件不包含任何案例结果或评测分数。

## 赛题要点（依据官方 `task.md`）

- 平台固定运行 **3 个案例**，分别交给「基础 Agent」与「加载参赛 Skill 的 Agent」，以实际运行结果对照评分。
- 参赛者只提交 **Skill 及其必要资源**，不提交预制答案、正式测试案例或白板。
- 评分维度：实际效果 40 + 使用增益 25 + 创新增益 15 + 可靠体验 10 + 生态贡献 10；GitHub 公开作品链接另加 5 分。
- 结构化输出必须保留：输入标识、主结果、证据/来源定位、运行状态、不确定性。

## 交付物

| 文件 | 作用 |
|-|-|
| `SKILL.md` | Skill 本体：用途、适用条件、调用方式、输入输出、异常处理（提交目录根路径） |
| `GITHUB_URL.txt` | 首行为本仓库链接，供平台登记作品地址 |

## 仓库结构

当前已就绪：

```
.
├── GITHUB_URL.txt     # 作品链接（平台要求放在提交目录根路径）
├── README.md          # 本文件
└── .gitignore
```

规划中（实现阶段补充）：

```
├── SKILL.md                     # Skill 本体与运行规则
├── references/
│   ├── field-dictionary.md      # 字段字典：断言 / 主体与关系 / 证据 / 来源 / 置信度 / 标识符
│   └── controlled-vocabularies.md  # 受控词表：关系类型、证据类型、状态枚举
├── scripts/                     # 断言拆解、证据定位、导出与自检脚本
└── examples/                    # 最小调用示例（标注为示例，非正式案例结果）
```

## 环境

本仓库的 Skill 面向平台固定的 Harbor 运行环境（官方 DeepSeek Harness，输入 `/input/case.json`，输出 `/app/output/result.json`）。本地开发环境配置见实现阶段的 `docs/setup.md`。

## 链接

- 赛题页面：<https://play.bohrium.com/challenge/product-arena-09-0e8befd4>
- 本仓库：<https://github.com/gw99-wz/Bohrium-14->

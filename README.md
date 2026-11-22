# Bohrium-14- · 阅读14｜Nanopublication

参赛作品：玻尔（Bohrium）Playground 产品分站赛「阅读14｜Nanopublication」赛题
（Challenge ID `product-arena-09-0e8befd4`）的参赛 Skill。

一个可被 Agent 调用的 Skill：把论文段落拆成**单条可判断真假的断言**，为每条断言绑定
**最小充分证据片段**与页码/字符定位，附上来源元数据、置信度依据与稳定标识符，导出
**schema 合法的 `result.json`** 以及断言—证据对照表。

> 仓库不含任何正式案例答案、预制结果或评测分数。`examples/minimal/` 是**合成的示例**
> （输入文本自述其数字为虚构），仅用于说明接口。

## 它解决什么

赛题点名的四个问题，各自对应一个具体机制，而不是靠提示词里写"请仔细"：

| 问题 | 机制 |
|-|-|
| 拆得细 | 一条断言一个主张；`conditions[]` 保留限定；QC-01 检出合并或过宽的断言 |
| 对得上 | 引文必须字面存在于原文；`page_text[char_start:char_end] == quote` 在构建期和校验期各查一次 |
| 追得回 | 文档 sha256 生成 `src:`，内容派生 `asrt:`/`evd:`/`np:`，页码 + 段落 + 句 id 可人工定位 |
| 读得懂 | JSON Schema（`additionalProperties: false`）+ 受控词表 + 固定状态枚举 |

## 快速开始

```bash
pip install "pymupdf>=1.24" "jsonschema>=4.18"

python scripts/extract_document.py --input paper.pdf --out work/document.json \
    --title "..." --authors "..." --year 2020
# 读 work/document.json，写出 work/assertions.draft.json
python scripts/resolve_quotes.py --document work/document.json \
    --draft work/assertions.draft.json --out work/assertions.json
python scripts/build_nanopub.py --case /input/case.json --document work/document.json \
    --assertions work/assertions.json --out out/result.json --qc-out out/qc.json
python scripts/validate_result.py --result out/result.json --pdf paper.pdf
```

退出码即状态：`0` success / `1` partial / `4` uncertain / `5` refused。

## 交付内容

| 路径 | 作用 |
|-|-|
| `SKILL.md` | Skill 本体：用途、触发条件、四步流程、输出契约、失败处理、限制 |
| `schemas/result.schema.json` | 机器可读的输出契约 |
| `references/field-dictionary.md` | 字段字典：每个字段的类型与含义 |
| `references/controlled-vocabularies.md` | 关系、证据类型、状态、不确定性等受控词表 |
| `references/relations.json` | 构建器加载的关系词表（18 条） |
| `references/qc-rules.md` | QC-01…QC-09 的判定标准，可复现 |
| `docs/method.md` | 方法说明：断言粒度、证据最小充分性、标识符、状态派生 |
| `docs/setup.md` | 依赖、安装、调用步骤、故障处理 |
| `scripts/` | 抽取 / 引文解析 / 构建 / 独立校验 四个脚本 |
| `examples/minimal/` | 最小调用示例（合成数据，示意输出，已标明为示例） |
| `tests/run_tests.py` | 5 个自包含场景，含降级路径 |
| `GITHUB_URL.txt` | 平台要求的作品链接 |

## 状态语义

| status | 含义 |
|-|-|
| `success` | 每条断言都有已验证证据，来源完整 |
| `partial` | 有产出但存在已声明的缺口（证据未定位、证据缺失、来源不全） |
| `uncertain` | 材料无法判断（如扫描版无文本层），不把猜测写成事实 |
| `refused` | 无可断言内容，不做任何编造 |

状态由检查结果派生，脚本不接受手工指定；`validate_result.py` 会独立复核
`status=success ⇒ 未验证证据数为 0`。

## 自测

```bash
python tests/run_tests.py
```

| 场景 | 期望 |
|-|-|
| A 干净运行 | `status=success`，`3/3` 证据通过，校验器 PASS |
| B 引文被改坏 | `status=partial`，证据未定位，置信度自动下调 |
| C 断言缺证据 | `status=partial`，QC-02 fail |
| D 无文本层 | 抽取器退出码 3，`status=uncertain` |
| E 空断言集 | `status=refused` |

## 测试与验证记录

本次开发在真实公开论文 *Attention Is All You Need*（arXiv 1706.03762）上跑通了完整链路：

- 15 页、39,983 字符、771 句成功抽取；
- 9 条断言、11 个证据片段，**11/11 字面定位成功**；
- `validate_result.py` 的 7 项检查全部 PASS（schema、ID 唯一、计数一致、状态一致、
  定位元数据一致、证据可复现、来源锚定）；
- 该论文摘要称英法 BLEU 41.8、正文 §6.3 称 41.0，管线将两者都原文引用并以
  `conflicting_statements` 标注，未擅自调和。

复现记录见 `docs/method.md`；论文原文不在本仓库中（版权与体积原因），
复现时需自行获取该 PDF。

## 限制

- 抽取遵循 PyMuPDF 的阅读顺序，复杂表格与多栏排版会退化；
- 分句为规则式（英/中文标点，保守），不解析非常规记号；
- 字符偏移是 `document.json` 页文本的 Unicode 码点偏移，不是字节偏移；
- 校验证明"引文存在且定位正确"，**不**证明"引文支持该断言"——后者由 QC-05/QC-07
  提示常见错误，仍需人工判断。

## 链接

- 赛题页面：<https://play.bohrium.com/challenge/product-arena-09-0e8befd4>
- 本仓库：<https://github.com/gw99-wz/Bohrium-14->

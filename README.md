# 电磁学课程知识图谱构建器

本仓库对应《电磁学课程知识图谱构建器——技术白皮书》的 **D1 构建器 + D2 图形化审核界面**，并包含《知识图谱文件格式规范 v1.0》的 Schema 与校验器。

一句话流程：**输入教材 → 粗筛出候选节点/关系 → 输出 draft graph.json → 网页里人工审核修改 → 导出 → 校验器把关**。

```
kg_constructor/                 # D1 构建器：教材 → 初抽图谱
├── readers.py                  #   md / txt / docx / pdf 读取
├── segment.py                  #   标题识别与章节分块
├── extract.py                  #   规则粗筛：概念/定律/公式/方法/应用/现象 + 三种关系
├── build.py                    #   组装符合规范 v1.0 的 graph.json
└── cli.py                      #   命令行入口

web/                            # D2 审核界面（纯静态网页，无需后端）
├── editor.html
├── editor.css
└── editor.js

examples/
├── sample_electromagnetism.md  # 示例教材
└── sample.graph.json           # 由示例教材生成的初抽图谱（draft）

graph.schema.json               # 文件结构定义（JSON Schema Draft 2020-12）
validate_graph.py               # 校验器：Schema + 文件内部一致性
example.graph.json              # 手工合成的格式示例（与构建器无关）
tests/                          # 校验器 + 构建器回归测试
docs/                           # 格式规范原文
requirements.txt
```

## 1. 构建器（D1）

```bash
python -m pip install -r requirements.txt          # Python 3.11+

# 用示例教材跑一遍
python -m kg_constructor build examples/sample_electromagnetism.md \
    -o examples/sample.graph.json --validate

# 用真实教材
python -m kg_constructor build 教材.pdf -o graph.json --title 大学电磁学 --validate
```

支持的输入：

| 格式 | 依赖 | 说明 |
| --- | --- | --- |
| `.md` / `.txt` | 无 | 推荐 Markdown，标题用 `#`/`##` |
| `.docx` | `python-docx` | 按 Word 标题样式识别章节 |
| `.pdf` | `pypdf` | 按页提取文本，保留页码；能识别“第X章/1.1”式标题 |

常用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `-o, --output` | `graph.json` | 输出路径 |
| `--title` | 文件名 | 教材标题，写入 `sources[].title` |
| `--course-name` | 大学电磁学 | 课程名 |
| `--max-per-section` | 10 | 每节最多候选节点数 |
| `--max-nodes` | 150 | 全书节点上限 |
| `--validate` | 关 | 生成后调用 `validate_graph.py` |

### 粗筛是怎么做的

当前是**规则版、可复现**的粗筛，不依赖 LLM：

1. **章节分块**：Markdown 标题 / Word 标题 / “第X章、1.1”式标题，保留父子层级与页码；
2. **候选节点**：常见电磁学术语表 + 加粗/引号术语 + “X 定义为 / 称为 X”句式 + “X定理/X定律/X方程”名词短语；
3. **类型判断**：`定理/定律/方程/原理 → law`，公式块 `→ formula`，`法/方法 → method`，`现象/效应 → phenomenon`，`的电场/的应用 → application`，其余 `concept`；
4. **候选关系**：
   - `derives`：同节公式挂到最近的定律；
   - `prerequisite`：描述里提到另一个节点时建立先修，随后去环；
   - `related_to`：同一句中共现的节点，按 ASCII ID 升序存一条；
5. **规范化**：中文名 → 语义化英文 ID（常见术语查表，其余 `kp_<hash>`）；同义术语合并；去掉句子碎片和停用词；
6. **合规输出**：`chapters`、`sources`（含真实 sha256）、`evidence`（含 locator 与原文 quote）、`review=pending`，一次生成即通过 `validate_graph.py`。

### 当前边界

- 这是 **粗筛**，追求“结构合法、核心不漏”，不追求高精度；教材里的长句定义、表格、图片内文字会漏抽或抽碎，必须人工审核；
- 尚未接 LLM。`extract.py` 的候选节点/关系结构已经独立，后续可以在这一层替换成 LLM 抽取，不影响 `build.py` 与校验器；
- 题目-知识点映射（D4）、CSV/Neo4j 导出尚未实现。

## 2. 可视化审核器（D2）

直接双击打开：

```text
web/editor.html
```

（纯静态页面，不需要启动服务器，也不会上传任何数据。）

操作流程：

1. 点 **加载 graph.json**，选择构建器生成的初抽图谱；
2. 左侧图区：节点按 type 着色，边按 relation 区分（先修实线箭头、推导虚线箭头、关联无箭头）；
3. 点节点：右侧修改名称、类型、章节、描述、别名、公式、条件，或删除、标记审核状态；
4. 点边：修改起点/终点/关系类型/描述，或删除；
5. `Ctrl + 点击` 两个节点 → **合并**（保留先选的，另一个的名字进别名，边自动重接，并写入 `redirects`）；
6. 支持按章节过滤、按名称/ID/别名搜索、拖动节点、滚轮缩放、撤销；
7. 点 **导出 JSON** 下载 `graph.json`，再跑校验器。

```bash
python validate_graph.py graph.json
```

审核器已实现白皮书 P0 的大部分：可视化、节点/边编辑、删除、合并、新增、按章节过滤、搜索、导出。撤销/重做目前是简单快照式（最多 30 步）。审核记录尚只写回 JSON 的 `review` 字段，没有独立 SQLite 审核日志。

## 3. 校验器与格式规范

```bash
python validate_graph.py graph.json
python validate_graph.py graph.json --release   # 只接受定稿
python -m unittest discover -s tests -v
```

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 通过 |
| `1` | 文件不合法（JSON/Schema/一致性任一层失败） |
| `2` | 运行错误（缺依赖、文件不可读、Schema 自身不合法） |

`graph.schema.json` 负责结构、类型、枚举、必填字段与 `if/then` 条件约束；`validate_graph.py` 负责 JSON Schema 表达不了的跨记录规则：

- 严格 JSON（无 BOM、重复键、NaN/Infinity）、文本 NFC 与首尾空白；
- ID 唯一、章节无环、同级 `order` 唯一；
- 来源哈希/URI、证据页码、`rag_ref` 结构；
- 节点别名与条件去重、formula 与 `formula_latex` 联动；
- 关系无自环、无重复、`related_to` 升序、先修无环且无冗余传递边；
- 题目映射、`redirects`、审核时效、released 定稿约束。

### 判定口径

规范没有写死的少数边界，本实现采用：

1. **孤立节点**：未出现在任何 `edges.source/target` 中；只在 `item_mappings` 里被引用仍算孤立。
2. **`extensions` 键**：必须带点号命名空间，如 `team.difficulty`。
3. **`related_to`**：按 ASCII ID 升序存一条，反向重复判重。
4. **`formula_latex`**：不得以 `$` 开头或结尾（不存外层定界符）。
5. **时间**：UTC RFC 3339（`Z` 或 `+00:00`），秒 00–59。
6. **`schema_version`**：固定 `1.0.0`；`version` 三段非负整数。

### `rag_ref`

规范只约定它是外部 RAG 关联的可选元数据，结构为 `{file_id, parent_id}` 两个非空字符串，未约定 RAG 侧标识规则。校验器只校验结构，不校验外部存在性或命名格式；示例中的 ID 是虚构值。

## 4. 白皮书交付物对应

| 交付物 | 状态 |
| --- | --- |
| D1 构建器 | ✅ MVP：md/txt/docx/pdf → draft graph.json，规则粗筛 |
| D2 审核界面 | ✅ MVP：静态网页，可视化 + 增删改合并 + 导出 |
| D3 电磁学知识图谱 v1.0 | ⏳ 已有示例 draft；需用真实教材跑 + 人工审核 |
| D4 题目-知识点映射 | ⏳ 未实现 |
| D5 技术文档 | ✅ 本 README |

## 5. 下一步

1. 用真实教材（建议 OpenStax 或课程 PDF）跑一遍，按抽出的噪声调整 `extract.py` 的词表/规则；
2. 在 `extract.py` 之上接 LLM 抽取（保留同一份 Candidate 结构），提升召回与关系质量；
3. 审核器补 CSV/Neo4j 导出、审核日志、版本对比；
4. 题目-知识点映射（D4）。

## 6. 已知边界

- 不验证来源哈希与原文是否一致、引文是否为原文、关系在物理上是否正确、审核是否真实发生；
- 不调用 RAG、模型或数据库；
- 构建器不做全自动定稿，人工审核是流程的一部分；
- 目前只做单文件校验，不比较多份快照。

修改规范、Schema 或抽取规则时，请同步更新 `tests/` 下对应的正/负用例。

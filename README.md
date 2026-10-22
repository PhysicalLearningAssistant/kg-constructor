# 电磁学课程知识图谱 · 格式规范配套实现

本目录是《电磁学课程知识图谱文件格式规范 v1.0》的可执行配套物：一份 JSON Schema、一份合成示例、一个零业务依赖的校验器，以及它的回归测试。规范原文见 [docs/知识图谱文件格式规范-v1.0.md](docs/知识图谱文件格式规范-v1.0.md)。

```
graph.schema.json          # 文件结构定义（JSON Schema Draft 2020-12）
example.graph.json         # 合成格式示例，status=draft，内容未审核
validate_graph.py          # 校验器：Schema + 文件内部一致性
requirements.txt           # 校验器依赖
tests/test_validate_graph.py
docs/                      # 格式规范原文
```

## 快速开始

```bash
python -m pip install -r requirements.txt   # jsonschema>=4.18,<5；Python 3.11+
python validate_graph.py example.graph.json
python validate_graph.py example.graph.json --release   # 示例是 draft，此命令应失败
python -m unittest discover -s tests -v
```

输出与退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 通过 |
| `1` | 文件不合法（JSON/Schema/一致性任一层失败） |
| `2` | 运行错误（缺依赖、文件不可读、Schema 自身不合法） |

`--release` 只接受 `status=released` 的定稿文件；不带该参数时，`released` 文件同样会执行定稿约束，`draft` 文件则允许 `pending/rejected` 状态与孤立节点。

## 校验分工

`graph.schema.json` 负责结构、类型、枚举、取值域、必填/禁止字段、`if/then` 条件约束（如 formula 节点的 `formula_latex`、来源类型的 `sha256`、审核状态与时间字段的联动）。

`validate_graph.py` 负责 JSON Schema 无法表达的跨记录规则：

- 严格 JSON：UTF-8 无 BOM、无注释/尾随逗号、无重复对象键、无 `NaN`/`Infinity`、无超出有限范围的数值；
- 文本：Unicode NFC、首尾无空白；
- ID 在各自集合内唯一；
- 章节：`parent_id` 存在、层级无环、同级 `order` 唯一；
- 来源：文件类来源必须有 `sha256`，`web` 来源必须是 HTTPS；URI authority 有效、不含用户名/密码/疑似访问密钥、不使用私有绝对路径；
- 证据：`source_id` 存在、页码成对且 `page_start <= page_end`；
- 节点：`chapter`、`evidence_ids` 存在；`formula` 与 `formula_latex` 联动；别名规范化去重且不得等于主名；`conditions` 无重复；
- 关系：端点存在且不相同、`(relation, source, target)` 不重复（`related_to` 反向也算重复）、`related_to` 按 ASCII ID 升序只存一条、`prerequisite` 子图无环且无冗余传递边；
- 题目映射：`skill_ids`、`evidence_ids` 存在，`item_id` 唯一；
- `redirects`：旧 ID 不在 `nodes`、目标存在、不得自指/成链/成环；关系与题目映射不得引用旧 ID；
- 审核：pending 的空值约束、approved/rejected 的非空约束、rejected 必须有 note、`reviewed_at <= created_at`；
- `released`：所有节点/关系/题目映射必须 approved，且不得有孤立节点。

## 判定口径

规范没有把少数边界写死，本实现采用如下口径，修改规范时请同步修改这里和测试：

1. **孤立节点**：指没有出现在任何 `edges.source/target` 中的节点。只在 `item_mappings` 中被引用的节点仍算孤立。依据是“孤立”在图中指度数为零，`item_mappings` 不是知识关系。
2. **`extensions` 的键**：必须是带点号的命名空间形式，如 `team.difficulty`；值为任意 JSON。这是对规范 §2.2 “键采用命名空间形式”的字面执行。
3. **`related_to` 方向**：按 ASCII ID 升序存储，`source < target`；反向重复记录判为重复。
4. **`formula_latex`**：除要求非空外，禁止以 `$` 开头或结尾（即不得带 `$…$`/`$$…$$` 外层定界符）；内部 LaTeX 不受影响。
5. **时间**：只接受 UTC RFC 3339（`Z` 或 `+00:00`），秒值 00–59；允许 1–9 位小数秒，比较时截断到微秒。
6. **`schema_version`**：固定 `1.0.0`；`version` 为三段非负整数且无前导零。

## 关于 `rag_ref`

规范只约定 `rag_ref` 是“外部 RAG 关联”的可选元数据，结构为 `{file_id, parent_id}` 两个非空字符串，未约定 RAG 侧标识的格式、生成方或唯一性。因此本实现：

- 校验 `rag_ref` 为 `null` 或恰好包含 `file_id`、`parent_id` 两个非空字符串；
- **不**校验这两个 ID 在外部 RAG 中是否存在、是否符合某种命名规则；
- 不因 `rag_ref` 缺失而使文件不合法。

也就是说，`rag_ref` 目前是“结构已锁定、语义待对接”的占位字段。等 RAG 侧标识规范确定后，只需在 `validate_graph.py` 增加一条针对 `file_id`/`parent_id` 的格式检查，并在规范中补一节即可，不会影响现有图谱文件。

## 示例数据说明

`example.graph.json` 是合成示例：

- `status=draft`，同时演示 `approved` 与 `pending` 两种审核状态；
- 两个来源的 `sha256` 是**占位值**，不对应真实文件，不能用于真实性核验；
- `rag_ref` 的 ID 是虚构字符串；
- 内容只用于演示字段组合与一致性规则，不代表已审核的课程知识。

## 与规范章节的对应

| 规范章节 | 落点 |
| --- | --- |
| §2 通用字段规则 | Schema（ID、版本、空值、附加字段）+ 校验器（NFC/空白、时间、数值） |
| §3 顶层对象 | Schema `required` / `additionalProperties` |
| §4–§10 各集合 | Schema 各 `$defs`；跨集合引用与唯一性在校验器 |
| §11 审核元数据 | Schema 条件约束 + 校验器时效与 released 约束 |
| §12 redirects | Schema 键值格式 + 校验器链/环/旧 ID 规则 |
| §13 一致性检查 | 两层校验合并覆盖 |

## 已知边界

- 不验证来源文件哈希与原文是否一致、引文是否为原文、关系在物理上是否正确、审核是否真实发生；
- 不调用 RAG、模型或数据库；
- 只针对单文件校验，不检查同一 `(graph_id, version)` 的多份快照是否一致。

修改规范或 Schema 时，请同步更新 `tests/test_validate_graph.py` 中对应的正/负用例，保持“规则—实现—测试”三者对齐。

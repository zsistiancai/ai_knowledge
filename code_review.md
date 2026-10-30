# RAG 评测「重排后召回率/准确率全为 0」排查报告

- 排查日期：2026-10-30
- 评测数据来源：`app/rag_eval/artifacts/rag_eval_batch_report.json`（生成于 2026-10-28 21:50:06）、`app/rag_eval/artifacts/hak180_eval_cases.json`
- 关联运行日志：`logs/app_20261028.log`（评测运行时段 21:19 ~ 21:50）
- 约束遵守情况：未修改任何业务代码、未触碰 MinIO / MongoDB / Milvus 容器与数据，仅做静态分析 + 日志取证

---

## 1. 现象复述

批量评测共 2 条用例，4 层指标表现如下（摘自报告"汇总结果"）：

| 层级 | 平均精确率 | 平均召回率 | 平均必命中率 |
|---|---|---|---|
| 普通检索（embedding_chunks） | 0.9 | 1.0 | 1.0 |
| HyDE 检索（hyde_embedding_chunks） | 0.7 | 0.8 | 0.8334 |
| RRF 融合（rrf_chunks） | 0.8 | 0.9 | 0.8334 |
| **最终重排结果（reranked_docs）** | **0.0** | **0.0** | **0.0** |

两条用例的重排层明细完全一致：`检索结果chunk_id列表 = []`、`检索结果数量 = 0`、`命中数量 = 0`。
而紧邻其上游的 RRF 层每条用例都有 5 条带真实 chunk_id（如 `470068815378039499`）的结果，主体命中率正常（1.0）。

即：**只有重排这一层的"检索结果 chunk_id 列表"整体为空，前 3 层全部正常。**

## 2. 分层排查结论

| 候选层级 | 结论 | 依据 |
|---|---|---|
| 粗召回（普通向量 / HyDE / RRF） | **正常，未失效** | 报告前三层精确率 0.7~1.0、召回率 0.8~1.0；日志 21:19~21:20 Milvus 每路均检索到 5 条 |
| rerank 过滤（模型打分 + dynamic_topk 截断） | **正常，未把结果过滤为空** | 日志 21:20:22~21:21:26（case_001）：`重排模型初始化成功` → `build_question_pairs` 打印 6 条"答案token长度"（5 条本地 + 1 条联网占位）→ `score_and_sort_chunks` 完成 → `dynamic_topk` 完成 → `node_rerank` 节点正常结束。`dynamic_topk` 的 `RERANK_MIN_TOPK=1` 也保证至少保留 1 条（rerank_service.py:158,162,178） |
| **rerank 输出契约（业务代码 bug）** | **失效点（根因）** | `merge_rrf_and_web` 重建文档字典时丢掉了 `chunk_id` 字段，导致 `reranked_docs` 里所有文档都没有 `chunk_id` |
| 评测脚本 | **无根因性 bug，但无兜底，把字段缺失放大成静默 0** | `extract_chunk_ids` 只认 `chunk_id` 字段，取不到就跳过，于是"文档存在但无 id"被算成"检索结果数量 0"，指标全部归 0 |

**一句话结论：不是召回不行，也不是 rerank 把内容过滤光了，而是重排节点输出的文档丢失了 `chunk_id` 字段，评测脚本按 `chunk_id` 对账时全部落空，表现为 0。**

## 3. 根因说明

### 3.1 证据链

1. **上游字段完好**：Milvus 检索结果标准化时带 `chunk_id`（`app/rag/query/embedding_search_service.py:46-57`，`normalize_retrieved_chunk` 第 47 行 `"chunk_id": chunk.get("id") or entity.get("chunk_id")`）；RRF 融合以 `chunk_id` 为 key 聚合并原样保留（`app/rag/query/rrf_service.py:39-55`，第 40、47、52 行）。报告里 RRF 层能列出 5 个真实 chunk_id 也印证了这点。

2. **字段在 merge 时丢失（根因代码）**：`app/rag/query/rerank_service.py:38-66` 的 `merge_rrf_and_web()`，本地 chunk 分支（第 47-54 行）重建字典时只保留了 5 个字段：

   ```python
   final_chunk_list.append({
       "title": chunk.get("title"),
       "text": chunk.get("content"),
       "url": None,
       "type": chunk.get("type", "milvus"),
       "score": chunk.get("score", 0.0),
   })   # ← 没有 "chunk_id"
   ```

   联网分支（第 57-64 行）本来就没有 chunk_id。后续 `score_and_sort_chunks`（第 127-150 行）只回写 `score`，`dynamic_topk`（第 152-178 行）只做切片，**整条 rerank 链路没有任何位置把 `chunk_id` 补回来**。

3. **评测端按 chunk_id 对账**：`app/rag_eval/metrics.py:55-76` 的 `extract_chunk_ids()`：

   ```python
   chunk_id = doc.get("chunk_id")
   if chunk_id is None:
       continue   # ← reranked_docs 的每条文档都在这里被跳过
   ```

   于是 `retrieved_chunk_ids = []`，`compute_chunk_metrics`（第 129-140 行）中 `len(retrieved)==0` → precision=0.0，`hit=0/len(gold)` → recall=0.0，must_hit_rate=0.0。`evaluate_query_state`（第 204-209 行）对 reranked_docs 层套用同一提取逻辑，两个用例全部归 0。

4. **日志证明 rerank 层结果非空**：`logs/app_20261028.log` 第 599-620 行（case_001，追踪ID=`hak180_local_region_eval_001_query`）：
   - `21:20:22` 开始初始化重排模型，`21:20:28` `重排模型初始化成功`；
   - `21:20:31` 连续 6 条 `答案token长度`（= 5 条本地 RRF + 1 条联网占位都进入了打分）；
   - `21:21:07` `score_and_sort_chunks` 完成、`21:21:26` `dynamic_topk` 完成、`node_rerank` 节点完成（耗时 78275ms，无异常）。

   结果非空、评测却计 0，唯一自洽的解释就是**文档存在但没有 `chunk_id` 字段**。

5. **契约佐证**：`app/process/query/agent/nodes/node_answer_output.py:18-30` 的 mock 数据中，`reranked_docs` 明确包含 `"chunk_id": "local_101"`，说明设计契约上重排输出应携带 chunk_id；当前实现违反了该契约。

### 3.2 根因定性

- **主因（业务代码 bug）**：`app/rag/query/rerank_service.py` `merge_rrf_and_web()` 第 47-54 行丢失 `chunk_id`。
- **次因（评测脚本健壮性）**：`app/rag_eval/metrics.py` `extract_chunk_ids()` 在"id 提取结果为 0"与"真实检索为空"两种情况间无法区分，把字段缺失静默呈现为 0 分，掩盖了问题定位线索。

### 3.3 对线上功能的影响评估

`app/rag/query/answer_service.py` 生成答案只使用 `title / score / type / text / url`（第 65-70 行拼 Prompt、第 117-142 行提取图片 URL），**不读 `chunk_id`，所以线上答案生成当前不受影响**。受影响的是一切依赖重排结果做"来源溯源"的场景（引用标注、按 chunk 回查原文/附件、后续审计），以及本次评测。

## 4. 复现验证建议

以下步骤均为只读操作，不修改任何代码与中间件数据。按耗时从短到长排列，任一步复现成功即可实锤根因。

### 验证 1（最快，约 3 秒，不连任何中间件）：直接调 merge 函数看字段

在项目根目录打开终端，进入项目虚拟环境交互式解释器后粘贴：

```powershell
.venv\Scripts\python.exe
```

```python
from app.rag.query.rerank_service import merge_rrf_and_web
merged = merge_rrf_and_web(
    [{"chunk_id": "470068815378039499", "title": "局部烫印范围设置",
      "content": "HAK 180 局部烫印应将起始位置设置为 50mm，结束位置设置为 170mm。",
      "type": "milvus", "score": 0.02}],
    [],
)
print(merged)
```

**判读**：输出若为 `[{'title': ..., 'text': ..., 'url': None, 'type': 'milvus', 'score': 0.02}]` —— 字典里**没有 `chunk_id` 键**，即复现了丢字段行为。

### 验证 2（只读日志交叉验证）：确认重排结果非空

```powershell
Select-String -Path logs\app_20261028.log -Pattern "答案token长度|重排模型初始化成功|dynamic_topk|node_rerank] 节点完成"
```

**判读**：在 `21:20` 时段（追踪ID=`hak180_local_region_eval_001_query`）应看到模型初始化成功、6 条"答案token长度"、`dynamic_topk` 完成、节点完成且无异常 → 证明 `reranked_docs` 非空，0 值不是被过滤光。

### 验证 3（端到端，约 1~2 分钟，读 Milvus + 本地重排模型，均只读）：单题跑链路并打印两层字段对比

同样在项目虚拟环境交互式解释器中粘贴（与 `runner.run_query_eval_case` 完全同构，但中途打印）：

```python
from unittest.mock import patch
from app.rag_eval.dataset import load_batch_eval_cases, build_web_search_docs
from app.process.query.agent.state import create_query_default_state
from app.process.query.agent.nodes.node_search_embedding import node_search_embedding
from app.process.query.agent.nodes.node_search_embedding_hyde import node_search_embedding_hyde
from app.process.query.agent.nodes.node_rrf import node_rrf
from app.process.query.agent.nodes.node_rerank import node_rerank

case = load_batch_eval_cases()[0]
state = create_query_default_state(
    session_id=case["case_id"] + "_verify",
    original_query=case["question"],
    rewritten_query=case["question"],
    item_names=case["expected_item_names"],
    is_stream=False,
    web_search_docs=build_web_search_docs(),
)
with patch("app.rag.query.hyde_search_service.generate_hyde_answer",
           return_value="HAK 180 局部烫印通过设置 50mm 起点和 170mm 终点实现区域控制。"):
    state.update(node_search_embedding(state))
    state.update(node_search_embedding_hyde(state))
    state = node_rrf(state)
    state = node_rerank(state)

print("RRF层 chunk_id  :", [c.get("chunk_id") for c in state["rrf_chunks"]])
print("重排层字段名    :", sorted(state["reranked_docs"][0].keys()))
print("重排层 chunk_id :", [d.get("chunk_id") for d in state["reranked_docs"]])
```

**判读**：预期输出形如
- `RRF层 chunk_id : ['470068815378039xxx', ...]`（有值）
- `重排层字段名 : ['score', 'text', 'title', 'type', 'url']`（**缺 chunk_id**）
- `重排层 chunk_id : [None, None, ...]`

三个打印与报告中"RRF 层有 5 个 id、重排层 0 个 id"完全对应，即实锤。

说明：该脚本不写 Milvus/Mongo（未调用答案节点），HyDE 输出与正式评测使用同一 patch 值，结果可对齐。

## 5. 修改建议（仅方案描述，未改任何代码）

**方案 A（推荐，修业务侧，恢复输出契约）**
在 `app/rag/query/rerank_service.py` 的 `merge_rrf_and_web()` 本地 chunk 分支中透传 `chunk_id`（新增 `"chunk_id": chunk.get("chunk_id")`）；联网分支保持无 `chunk_id`（或显式置 `None`）。理由：
- 与 `node_answer_output.py` mock 所示契约、state 注释（"重排序后的最终 Top-K 文档"）一致；
- 打分、排序、截断逻辑均不受影响（只是多带一个原样透传的字段）；
- 评测端 `extract_chunk_ids` 会自然跳过联网占位文档（它们本就不该参与 chunk 级指标），指标语义反而更准确。
建议配套一条回归校验：`node_rerank` 出口处对 `type=="milvus"` 的文档断言 `chunk_id` 非空。

**方案 B（评测侧兜底，建议与 A 并行做）**
`app/rag_eval/metrics.py` 或报告中区分两种 0：`文档条数 > 0 但 id 提取条数 = 0` 时，在报告里显式标注"重排输出缺少 chunk_id 字段"而非静默 0 分。这样以后再出契约类问题，一眼就能看出是字段丢了而不是检索差。

**方案 C（不推荐作为主修）**
让评测脚本改用 title+content 做模糊对账。能出分，但丢失了"用真实入库 id 精确对账"的设计初衷（`dataset.py` 第 171-173 行注释明确说明标注基于真实 chunk_id），且联网文档永远无法对账，不解决问题本质。

## 6. 风险备注

1. **修复方案 A 的回归面很小，但需重跑评测**：修复后需重新执行 `RagEvalTester().run_eval()`，重排层指标才有意义；修复前后指标不可直接对比（当前 0 值不代表真实重排质量）。
2. **重排模型加载曾出现环境性故障（与本 bug 无关，独立风险）**：`logs/app_20261028.log` 第 101-123 行显示 16:16 运行 `node_rerank.py` 自测时，`FlagReranker` 加载 `D:\ai_models\modelscope_cache\models\rerank\BAAI\bge-reranker-large` 触发 `HFValidationError`（Windows 绝对路径被 huggingface_hub 当作 repo id 校验）。21:20 评测时段同一配置加载成功（已确认该路径当前存在）。风险点：`.env:60` 使用 Windows 本地路径作为 `BGE_RERANKER_LARGE`，一旦路径失效或离线环境下 FlagEmbedding 走 hub 解析分支，重排节点会直接抛异常。建议保持路径有效，或在配置注释中标明"必须为本地真实存在的目录"。
3. **评测脚本对联网占位文档的处理语义**：修复 A 后，`reranked_docs` 中混有 1 条无 chunk_id 的联网文档，`extract_chunk_ids` 会跳过它（正确），但 precision 的分母（`retrieved`）不含联网文档，即重排层指标只度量本地 chunk —— 这与题库设计意图一致，无副作用，仅需知悉。
4. **dynamic_topk 的截断行为**：本次评测中未构成问题（至少保留 1 条，`RERANK_MIN_TOPK=1`），但"分数断崖"阈值（`RERANK_GAP_ABS=0.2` / `RERANK_GAP_RATIO=0.2`）在实际语料上可能激进截断，修复字段问题后若重排层召回仍偏低，可优先检查该截断点保留的条数。
5. 本报告基于 2026-10-28 21:50 生成的报告文件与当日日志取证；若此后代码或配置有变动，结论需按第 4 节步骤重新验证。

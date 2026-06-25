# 第九阶段：Claude 上下文、搜索和 Shell 策略对齐方案

## 阶段目标

第九阶段按 Claude Code 的实现思路，系统性修复 ZzCode 在实时信息查询中的三个问题：

```text
运行时上下文
  -> 注入当前日期等 user context
  -> WebSearch prompt 使用当前年月约束搜索 query
  -> Shell / PowerShell 只作为终端工具，优先让模型使用专用工具
  -> Shell 权限按命令语义判断，而不是按工具名一刀切
```

本阶段不做“给 system prompt 加一句今天日期”的最小补丁，而是对齐 Claude Code 的分层设计：

1. 当前日期属于运行时 user context，不属于模型猜测结果。
2. WebSearch 自身有工具 prompt，明确要求搜索近期信息时使用当前年份。
3. Shell / PowerShell 工具有明确边界、专用 prompt、read-only 判断和权限建议。

## 验收标准

完成第九阶段时，应满足：

1. 每次主 Agent 查询都会获得稳定的运行时 user context。
2. user context 至少包含 `currentDate`，格式与 Claude 接近：`Today's date is YYYY-MM-DD.`
3. user context 以独立 meta/system-reminder 消息注入，而不是混入用户原始问题。
4. 当前日期使用本地日期，不使用模型知识或搜索结果推断。
5. 长会话跨日期时，有明确 date change 处理策略。
6. WebSearch 工具 prompt 明确要求近期信息使用当前年份或完整日期。
7. WebSearch 工具结果继续作为 tool result 回灌模型，并保留来源 URL。
8. Shell 工具 prompt 明确要求优先使用专用工具，不用 shell 做文件读写、搜索和普通文本输出。
9. Shell 权限不再只按 `run_shell` 工具名统一 high-risk 处理。
10. read-only 命令可以被自动允许或低风险处理。
11. `date` / `Get-Date` 这类只读时间命令有专门规则，危险参数必须被拦截。
12. Windows 下 PowerShell 行为有独立建模计划，不继续把 bash/cmd/powershell 全部混在一个无差别 shell 工具中。
13. 前端权限展示能看到更清晰的命令摘要和风险原因。
14. 针对“今天涨幅最高的 A 股股票”这类问题，Agent 应直接带正确日期搜索，不应先进行 Shell 日期探测。

## 暂不实现

本阶段第一版暂不做：

- Anthropic server-side `web_search_20250305` 完整复刻。
- Claude Code 完整 Bash AST / tree-sitter 安全解析。
- Claude Code 完整 PowerShell AST 解析。
- enterprise sandbox 策略。
- auto mode classifier。
- shell permission classifier 模型。
- prompt cache 级别的完整优化。
- WebSearch Sources 强制格式的全部 UI 体验。
- Windows PowerShell 沙箱能力。

这些能力可以后续继续补齐，但第九阶段必须先把边界和接口设计成可扩展形态。

## Claude Code 参考实现

本阶段参考以下关键源码，不全盘照搬：

- `agent_learn/claude-code-sourcemap/restored-src/src/context.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/constants/common.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/utils/api.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/utils/attachments.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebSearchTool/prompt.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebSearchTool/WebSearchTool.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/BashTool/prompt.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/BashTool/readOnlyValidation.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/PowerShellTool/prompt.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/PowerShellTool/readOnlyValidation.ts`

### Claude 机制一：运行时 user context

Claude Code 在 `getUserContext()` 中注入：

```text
currentDate: Today's date is YYYY-MM-DD.
```

然后通过 `prependUserContext()` 包装为 meta user message：

```xml
<system-reminder>
As you answer the user's questions, you can use the following context:
# currentDate
Today's date is YYYY-MM-DD.

IMPORTANT: this context may or may not be relevant to your tasks...
</system-reminder>
```

这使模型在处理“今天”“最新”“近期”时先拥有确定日期，不需要调用 shell。

### Claude 机制二：WebSearch prompt 约束当前年份

Claude WebSearch prompt 明确要求：

```text
IMPORTANT - Use the correct year in search queries:
- The current month is Month YYYY. You MUST use this year when searching for recent information...
```

因此模型搜索近期信息时会自然带当前年份，必要时带完整日期。

### Claude 机制三：Shell / PowerShell 边界和权限

Claude Bash / PowerShell prompt 都强调：

- 文件搜索用 Glob/Grep，不用 find/grep/Select-String。
- 文件读取用 Read，不用 cat/Get-Content。
- 文件编辑用 Edit，不用 sed/awk。
- 文件写入用 Write，不用 echo/Set-Content。
- 普通回复直接输出文本，不用 echo/printf/Write-Output。

权限层不是按工具名统一 high-risk，而是：

- 对 read-only 命令做 allowlist。
- 对危险参数做 deny。
- 对无法静态判断的命令 ask。
- 对可保存的权限给 exact/prefix 规则建议。

## 目标架构

第九阶段后建议结构：

```text
src/zzcode/
├── context/
│   ├── runtime.py          # 当前日期、平台、cwd 等运行时上下文
│   └── injection.py        # 把 context 包装成 meta/system-reminder 消息
├── tools/
│   ├── local/
│   │   ├── web_search.py   # 增强 prompt 和日期查询策略
│   │   ├── shell.py        # 收敛为 bash/sh 风格命令工具
│   │   └── powershell.py   # Windows PowerShell 独立工具，后续实现
│   └── safety/
│       ├── shell_readonly.py
│       ├── shell_permissions.py
│       └── command_rules.py
```

如果当前代码规模不适合立即拆目录，可以先在现有模块内实现同等边界，但接口命名应向上述结构靠拢。

## 实施步骤

| 步骤 | 状态 | 内容 | 验收 |
|---|---|---|---|
| 1 | 已完成 | 新增运行时日期工具函数，返回本地 ISO 日期 `YYYY-MM-DD` | 单元测试覆盖固定日期注入或可通过环境变量覆盖 |
| 2 | 已完成 | 新增 `RuntimeUserContext` 构造，至少包含 `currentDate` | 上下文文本包含 `Today's date is YYYY-MM-DD.` |
| 3 | 已完成 | 在 Agent 初始消息中 prepend meta/system-reminder user context | 用户原始问题保持不变，模型消息前置 context |
| 4 | 已完成 | 增加跨日期处理策略 | 长会话日期变化时追加 date change 提示或刷新 context |
| 5 | 已完成 | 重写 WebSearch 工具 prompt | prompt 明确当前年月、正确年份、近期信息搜索规则 |
| 6 | 已完成 | WebSearch 调用前把当前日期/月年传入工具 prompt 或工具上下文 | 搜索“今天”类问题时 query 带正确日期或年份 |
| 7 | 已完成 | WebSearch 结果保留来源 URL，并提醒最终回答引用来源 | tool result 中可被模型读取到标题和 URL |
| 8 | 已完成 | 重写 Shell prompt，加入专用工具优先规则 | prompt 明确不应使用 shell 做读写搜索和普通输出 |
| 9 | 已完成 | 设计 shell permission result：allow / ask / deny / passthrough | 权限层不再只返回 high-risk ask |
| 10 | 已完成 | 实现第一版 read-only 命令 allowlist | `pwd`、`date`、`git status` 等可识别为只读 |
| 11 | 已完成 | 为 `date` 增加安全参数白名单 | 允许展示日期，拒绝设置系统时间的参数 |
| 12 | 已完成 | 设计 PowerShellTool 独立接口 | Windows 下 PowerShell 不再只是 `run_shell` 的一个字符串 |
| 13 | 已完成 | 为 `Get-Date` 增加 read-only 规则 | `Get-Date -Format ...` 被识别为只读 |
| 14 | 已完成 | 前端权限展示接入风险原因和建议规则 | 权限弹窗可展示命令摘要、风险级别、allow once/session |
| 15 | 已完成 | 增加回归调试用例：今天 A 股涨幅最高 | 工具轨迹应先 WebSearch，query 包含当天日期，不出现 Shell 日期探测 |

## 第一版实现顺序

第一版按以下顺序推进：

1. 先做运行时 user context 注入。
2. 再做 WebSearch prompt 和当前年月策略。
3. 再做 Shell prompt 边界。
4. 再做 read-only 权限分级。
5. 最后做 Windows PowerShell 独立工具设计。

原因：

- 日期上下文是这次问题的根因，优先级最高。
- WebSearch prompt 是第二层防线，能直接改善实时查询质量。
- Shell prompt 解决模型工具选择倾向。
- 权限分级解决用户看到大量 high-risk shell 确认的问题。
- PowerShell 独立工具涉及平台差异和权限解析，适合作为最后一步分层落地。

## 当前状态

第九阶段第一、二、三版能力已完成。Claude 完整 AST/sandbox 级别能力按”暂不实现”保留到后续阶段。

已完成（第一版）：

- 已分析 Claude Code 关键源码。
- 已确认 ZzCode 当前问题来自日期上下文缺失、WebSearch prompt 约束不足、Shell 权限过粗。
- 已实现运行时 `currentDate` user context 注入。
- 已实现 WebSearch 当前年月搜索提示。
- 已实现单次工具循环跨日期时的 date-change context 追加，并刷新工具 schema。
- 已实现 Shell prompt 边界提示和第一版 read-only 权限分级。
- 已实现 `date` / `Get-Date` 第一版只读识别和危险日期参数拒绝。
- 已新增独立 `run_powershell` 结构化工具，`run_shell` 不再承接 PowerShell 包装调用。
- 已实现 WebSearch 结构化 `sources` 返回，并在 tool result 中提醒最终回答引用来源 URL。
- 已实现权限事件的 `riskReason` / `suggestedRules` 字段，并接入前端权限展示。
- 已增加”今天涨幅最高的 A 股股票”后端工具轨迹回归用例。

未完成：

- PowerShell 完整 AST / 参数级 read-only 校验。

## 第二版追加目标：Claude 风格 WebSearch / WebFetch 收敛

### 追加背景

`tests/debug_test` 最新调试结果说明，第一版已经解决了最初的日期和 Shell 问题：

- Agent 没有再先调用 shell/date 探测日期。
- WebSearch query 已经携带当天日期。
- WebSearch / WebFetch 已经作为主要联网工具使用。

但暴露出新的联网搜索问题：

1. 模型连续执行多轮 `web_search` / `web_fetch`，没有及时收敛到最终回答。
2. 搜索 query 虽然带日期，但目标不够精确，容易搜到指数、新闻综述、午间涨停分析，而不是“个股涨幅榜”数据源。
3. WebFetch 抓取结果过长或不稳定，个别页面 504，长页面回灌后导致主模型上下文膨胀。
4. 最终失败不是工具权限问题，而是 step 6 主模型流式请求和 fallback 普通请求都 read timeout。
5. 前端把 WebSearch / WebFetch 长结果完整展开，调试时可读，但正常交互体验和 Claude 不一致。

因此第二版不做“简单限制次数”的最小补丁，而是继续按 Claude Code 的 WebSearch / WebFetch 分层机制改造。

### Claude 联网机制参考

本节新增参考以下关键源码：

- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebSearchTool/prompt.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebSearchTool/WebSearchTool.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebSearchTool/UI.tsx`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebFetchTool/prompt.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebFetchTool/WebFetchTool.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebFetchTool/utils.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/tools/WebFetchTool/preapproved.ts`
- `agent_learn/claude-code-sourcemap/restored-src/src/components/permissions/WebFetchPermissionRequest/WebFetchPermissionRequest.tsx`

Claude Code 的关键做法：

1. WebSearch 使用 Anthropic server-side `web_search_20250305`，并设置 `max_uses: 8`。
2. WebSearch 工具内部发起一次独立模型调用，把 server-side search 作为 `extraToolSchemas` 传入。
3. WebSearch prompt 强制最终回答必须包含 `Sources:`，并用 markdown 链接列出相关 URL。
4. WebSearch 输出结构化 search blocks，UI 默认只显示 `Did N searches in Xs`，不展开所有结果。
5. WebFetch 是“HTTP 抓取 -> HTML 转 markdown -> 小模型按 prompt 提取/压缩 -> 主模型读取提取结果”。
6. WebFetch 有 15 分钟 URL cache、50MB cache 上限、10MB HTTP body 上限、60 秒 HTTP timeout、100000 字符 markdown 上限。
7. WebFetch HTTP 自动升级 HTTPS；跨 host redirect 不自动跟随，而是返回 redirect 提示，让模型显式重新请求。
8. WebFetch 对 domain 做权限建模，允许对 `domain:hostname` 保存规则；部分代码/文档域名预批准。
9. WebFetch 非预批准域名的小模型 prompt 带版权限制，要求只基于页面内容、限制长引用。
10. WebFetch UI 默认只显示 `Received <size> (status)`，verbose 模式才展开结果。

### 第二版目标架构

建议把联网工具从“简单 API wrapper”升级为与 Claude 类似的两层结构：

```text
src/zzcode/
├── tools/
│   ├── local/
│   │   ├── web_search.py          # WebSearch 工具入口、prompt、结构化结果
│   │   ├── web_fetch.py           # WebFetch 工具入口、权限、结果映射
│   │   └── web_limits.py          # 每轮联网工具预算和收敛策略
│   └── web/
│       ├── search_session.py      # 单次 WebSearch 内部搜索会话，模拟 Claude server-side max_uses
│       ├── fetch_cache.py         # 15 分钟 TTL / size limit cache
│       ├── fetch_http.py          # URL 校验、HTTPS 升级、redirect、安全 fetch
│       ├── markdown.py            # HTML -> markdown / text 提取
│       ├── summarize.py           # 小模型或本地 summarizer 对页面按 prompt 提取
│       └── domains.py             # preapproved hosts、domain permission rule content
```

如果当前项目规模不适合立即拆这么细，可以先在 `tools/local/web_search.py`、`tools/local/web_fetch.py` 旁边增加 `tools/local/web_fetch_cache.py`、`tools/local/web_fetch_http.py`、`tools/local/web_limits.py`，但接口命名要保留向上述结构迁移的空间。

### 第二版验收标准

完成第二版时，应满足：

1. 针对一次用户请求，联网工具有明确预算，不允许无限搜索/抓取直到 LLM 超时。
2. WebSearch prompt 强制最终回答包含 `Sources:`，并列出相关 URL。
3. WebSearch 结果结构中保留 query、search count、source title/url，不依赖 UI 文本解析。
4. WebSearch UI 默认折叠，只显示搜索次数、耗时和简短 query 摘要；debug/verbose 才展开结果。
5. WebFetch 不再把长网页正文直接回灌主模型；必须先按 prompt 提取/压缩。
6. WebFetch 有 URL cache，重复抓同一 URL 不重复 HTTP 请求。
7. WebFetch 有 HTTP body 上限、markdown 上限和 timeout。
8. WebFetch 支持 HTTP -> HTTPS 自动升级。
9. WebFetch 对跨 host redirect 返回明确 redirect result，不自动跟随。
10. WebFetch 权限可以按 `domain:hostname` 展示建议规则。
11. WebFetch UI 默认折叠，只显示收到字节数、状态码和 URL 摘要。
12. 当搜索/抓取预算用尽但没有确定答案时，Agent 应基于已有来源给出“不确定 + 已查来源”，而不是继续搜索。
13. “今天涨幅最高的 A 股股票”回归中，工具轨迹应在有限步内结束：优先搜索“个股涨幅榜/涨跌幅排行/行情排行”，排除指数类结果，无法确认时给出证据不足说明和来源。

### 第二版暂不实现

第二版仍不完整复刻：

- Anthropic server-side `web_search_20250305` 协议本身。
- 完整 citation block 协议。
- 完整企业 egress proxy / domain_info 服务。
- 复杂 HTML 语义抽取和浏览器渲染。
- PDF/二进制内容的完整解析。
- 完整版权合规过滤器。

但第二版必须把工具边界、预算、缓存、压缩和 UI 折叠这些 Claude 风格骨架落地。

### 第二版实施步骤

| 步骤 | 状态 | 内容 | 验收 |
|---|---|---|---|
| 16 | 已完成 | 增强 WebSearch prompt，强制最终回答包含 `Sources:` section | 使用 WebSearch 后的最终回答包含 `Sources:` 和 markdown URL |
| 17 | 已完成 | 为 WebSearch 增加单次工具内部 `max_uses` / search session 预算建模 | 一次 WebSearch 内部最多执行固定次数搜索，超过返回预算耗尽结果 |
| 18 | 已完成 | 为 Agent 增加每 turn 联网工具预算 | 连续 `web_search` / `web_fetch` 超过预算时阻止继续调用，并把预算耗尽结果回灌模型 |
| 19 | 已完成 | 增加联网预算耗尽后的收敛提醒 | 模型被明确要求基于已有来源回答或说明不确定，不继续换 query |
| 20 | 已完成 | WebSearch 结构化输出增加 search count、source blocks 和 duration | 单元测试可断言 query、sources、duration、search_count |
| 21 | 已完成 | WebSearch UI 默认折叠结果 | 前端普通模式只显示搜索次数/耗时/query 摘要，不展开长结果 |
| 22 | 已完成 | WebSearch debug/verbose 模式保留长结果查看能力 | 前端新增 `/verbose` 命令切换全局工具结果展开；WebSearch verbose 模式列出 sources 标题及 URL；其他工具 verbose 模式追加原始 output |
| 23 | 已完成 | WebFetch 增加 URL 校验和 HTTP -> HTTPS 升级 | `http://example.com/x` 实际请求升级为 HTTPS；非法 URL 被拒绝 |
| 24 | 已完成 | WebFetch 增加 15 分钟 TTL cache 和 size 上限 | 同 URL 重复 fetch 命中 cache；cache 可测试过期/清理 |
| 25 | 已完成 | WebFetch 增加 HTTP body 上限、请求 timeout、markdown 长度上限 | 超限和超时返回结构化失败，不拖垮主循环 |
| 26 | 已完成 | WebFetch 增加 redirect 策略 | 同 host redirect 可跟随；跨 host redirect 返回 redirect result，要求模型显式新请求 |
| 27 | 已完成 | WebFetch HTML -> markdown / text 提取独立模块化 | HTML 页面结果先转 markdown/text，再进入提取层 |
| 28 | 已完成 | WebFetch 增加小模型或轻量 summarizer 提取层 | 主模型收到的是按 prompt 提取后的短结果，不是整页正文 |
| 29 | 已完成 | WebFetch 非预批准域名提取 prompt 加版权/引用限制 | 小模型 prompt 限制长引用，并要求只基于页面内容 |
| 30 | 已完成 | WebFetch domain 级权限建议规则 | 权限事件建议 `domain:hostname`，而不是只显示完整 URL |
| 31 | 已完成 | WebFetch UI 默认折叠结果 | 普通模式只显示 `Received <size> (<status>)` 和 URL 摘要；verbose 模式展示完整提取内容 |
| 32 | 已完成 | 为”今天涨幅最高的 A 股股票”增加真实轨迹回归样例 | `Phase09BudgetConvergenceTest` 验证预算耗尽后收敛、无 shell 探测、最终输出非空 |

### 第二版实现顺序

第二版按以下顺序推进：

1. 先做联网预算和收敛提醒。
2. 再做 WebSearch 强制 Sources 和结构化 search session 输出。
3. 再做 WebFetch cache、timeout、截断和 redirect 安全。
4. 再做 WebFetch 提取/压缩层。
5. 最后做前端 UI 折叠和 verbose 展开。

原因：

- 当前实际失败来自搜索/抓取循环和最终 LLM timeout，预算与收敛优先级最高。
- WebSearch Sources 和结构化输出决定模型能否基于已有证据完成回答。
- WebFetch 资源控制能防止单个网页拖慢或撑大上下文。
- 提取/压缩层是 Claude WebFetch 的核心，但需要先有稳定的 HTTP/cache/limit 基础。
- UI 折叠不改变模型行为，但能让前端体验贴近 Claude，适合在数据结构稳定后实现。

### 第二版当前状态

截至第二版完成，全部 32 个步骤已实现。

已完成（第二版收尾）：

- 已阅读 Claude WebSearch / WebFetch 关键源码。
- 已确认当前 debug 问题来自联网工具不收敛、WebFetch 长结果回灌、最终 LLM timeout，而不是日期缺失或 shell 探测。
- 已增强 WebSearch prompt，要求使用后最终回答包含 `Sources:`。
- 已实现 Agent 每 turn 联网工具预算，默认 8 次，可用 `ZZCODE_WEB_TOOL_BUDGET` 覆盖。
- 已实现联网预算耗尽 tool result，要求模型停止继续搜索/抓取并基于已有来源回答或说明不确定。
- 已增强 WebSearch 结构化输出，包含 `results`、`sources`、`searchCount`、`durationSeconds`。
- 已抽取 WebSearch 内部 `WebSearchSession`，按 Claude `max_uses` 思路建模单次工具内部搜索预算。
- 已在 JSONL tool_result 事件中透传 `data` / `metadata`，前端 WebSearch 默认折叠为搜索次数、耗时和来源数量摘要。
- 已抽取 WebFetch HTTP 边界模块，统一 URL 校验和实际请求 URL 生成，按 Claude 思路拒绝 credentials/无效 hostname，并在请求前自动将 HTTP 升级为 HTTPS。
- 已实现 WebFetch URL cache，默认 15 分钟 TTL、50MB 总容量上限；cache 存放 HTTP 抓取和文本转换后的结果，同 URL 不重复请求，结果 metadata 标记 `cacheHit`。
- 已实现 WebFetch 资源上限：HTTP body 最大 10MB、请求 timeout 60 秒、文本结果最大 100000 字符；body 超限和 timeout 返回结构化失败原因，文本超长返回截断结果并标记 `textTruncated`。
- 已实现 WebFetch redirect 策略：禁用底层自动跳转，同 host 或 `www.` 变体 redirect 自动跟随，跨 host redirect 返回 Claude 风格 redirect result，要求模型显式用新 URL 再请求；redirect 循环超过 10 次返回结构化失败。
- 已抽取 WebFetch 页面提取模块，HTTP 层只提供 bytes/content-type，`web_fetch_extract` 负责 HTML/text 转换、实体处理和文本截断，为后续小模型/轻量 summarizer 提取层提供稳定输入。
- 已实现 WebFetch prompt 提取/压缩层：Agent 运行时注入基于现有 LLM client 的 secondary summarizer，并以 `tools=[]` 调用；无注入时使用本地 extractive fallback。主模型收到 `summary.text`，不再直接收到整页正文，结果 metadata 记录 `summarySource` / `summaryTruncated`。
- 已实现 WebFetch 预批准域名判断和 secondary prompt 分流：预批准代码/文档域名允许更宽的文档/代码摘录；非预批准域名要求只基于页面内容、限制 125 字符以上长引用、禁止歌词等。该预批准仅用于 WebFetch 提取 prompt，不等同于沙箱网络放行或步骤 30 的 domain 权限规则。
- 已实现 WebFetch domain 级权限建议：非预批准域名请求权限，权限摘要和 suggested rule 使用 `domain:hostname`；预批准代码/文档域名自动允许。当前阶段 domain rule 进入前端展示和用户确认语义，持久化 allow/deny 规则仍沿用现有会话级权限机制。

**第二版收尾（步骤 22/31/32）已完成：**

- ✅ 步骤 22 — 前端 `/verbose` 命令：新增全局 verbose 开关，WebSearch verbose 模式列出 sources 标题及 URL，通用 renderer 追加原始 output
- ✅ 步骤 31 — WebFetch UI 默认折叠：新增 `web_fetch` 工具渲染器，普通模式显示 `Received <size> (<status>)` + URL 摘要 + summary 来源信息，verbose 模式展示完整提取内容
- ✅ 步骤 32 — 回归测试用例：`Phase09BudgetConvergenceTest` 包含两个测试用例（`test_web_search_converges_within_budget_no_timeout`、`test_web_budget_exhausted_agent_stops_searching`），验证预算耗尽后 Agent 收敛、不无限搜索、最终输出非空、无 shell 日期探测

**P0/P1 修复已完成：**

- ✅ P0 — 预算耗尽前端展示：`renderWebSearchResult` 和 `renderWebFetchResult` 均检测 `data.budget_used` / `data.budget_max`，显示 `⚠ Web tool budget exhausted (N/M used)` + 收敛提示；verbose 模式下展示被拦截的工具调用详情
- ✅ P1 — 权限文本渲染修复：`MessageRow.tsx` 权限区域显式添加 `flexDirection="column"`，修复 `低原因：` 粘连问题；风险级别与原因分行独立展示

## 第三版追加目标：Claude 风格工具并行执行

### 追加背景

第二版完成后，"今天涨幅最高的 A 股股票"查询可以在 189s 内完成，但仍有优化空间。主要瓶颈：

1. 同一步内的多个工具调用（如 2×web_search）串行执行，每个 5s 的 API 延迟累加
2. 模型在同一步中返回了 `web_fetch` + `web_search` 混合调用，但 `web_fetch` 因权限确认不能并发

参考 Claude Code `toolOrchestration.ts` 中的 `partitionToolCalls` / `runToolsConcurrently` 设计：Claude 按 `isConcurrencySafe()` 将工具调用分区，只读工具并发执行，破坏性工具串行执行。System prompt 中明确告诉模型 "make all independent tool calls in parallel"。

### Claude 参考机制

```typescript
// src/services/tools/toolOrchestration.ts
function partitionToolCalls(toolUseMessages, ctx): Batch[] {
  // 连续 isConcurrencySafe 工具 → 同并发批次
  // 非 safe 工具 → 各自独立串行
}
async function* runTools(toolUseMessages, ...): AsyncGenerator {
  for (const { isConcurrencySafe, blocks } of partitionToolCalls(...)) {
    if (isConcurrencySafe) yield* runToolsConcurrently(blocks, ...)  // 并发
    else                    yield* runToolsSerially(blocks, ...)      // 串行
  }
}
```

### 第三版实施步骤

| 步骤 | 状态 | 内容 | 验收 |
|---|---|---|---|
| 33 | 已完成 | 为 `BaseTool` 新增 `is_concurrency_safe` 属性 | 默认 False，子类按需覆盖 |
| 34 | 已完成 | 标记只读且自动允许的工具为 concurrency-safe | `web_search`、`read_file`、`list_files`、`glob`、`grep` → True |
| 35 | 已完成 | 实现 `_partition_tool_calls()` | 连续 safe 工具合并为并发批次，非 safe 各自独立 |
| 36 | 已完成 | 实现 `_run_tool_call_batch()` / `_run_concurrently()` | safe 批次用 `ThreadPoolExecutor` 并发执行 |
| 37 | 已完成 | 线程安全保护 | `threading.Lock` 保护预算/渲染/transcript；工具执行阶段无锁 |
| 38 | 已完成 | 并发数控制 | `ZZCODE_MAX_TOOL_CONCURRENCY` 环境变量，默认 10 |

### 当前工具并发标记

| 工具 | is_concurrency_safe | 原因 |
|------|:---:|------|
| `web_search` | ✅ True | 只读、自动允许 |
| `read_file` | ✅ True | 只读、自动允许 |
| `list_files` | ✅ True | 只读、自动允许 |
| `glob` | ✅ True | 只读、自动允许 |
| `grep` | ✅ True | 只读、自动允许 |
| `web_fetch` | ❌ False | 需权限确认（待预解析改进后升级） |
| `run_shell` | ❌ False | 破坏性 |
| `write_file` / `edit_file` / `append_file` | ❌ False | 破坏性 |

### 第三版当前状态

已完成：

- ✅ `BaseTool.is_concurrency_safe` 属性及工具标记（步骤 33-34）
- ✅ `_partition_tool_calls()` — 对齐 Claude `partitionToolCalls()`（步骤 35）
- ✅ `_run_tool_call_batch()` — 并发批次走 `_run_concurrently()`，串行走 for 循环（步骤 36）
- ✅ `_run_concurrently()` — `ThreadPoolExecutor` 并发，锁保护共享状态，执行阶段无锁（步骤 36-37）
- ✅ `ZZCODE_MAX_TOOL_CONCURRENCY` 环境变量控制最大并发数，默认 10（步骤 38）

效果验证（"今天涨幅最高的 A 股股票" debug 实测）：

| 指标 | 第三版前 | 第三版后 | 改善 |
|------|----------|----------|------|
| Step 4 (2×web_search) | 串行 ~9.8s | 并发 max(4.9, 4.9) ≈ 4.9s | **-50%** |
| 总耗时 | ~189s | ~134s | **-29%** |

Step 4 两次 web_search 日志时间戳确认为并发：同时开始（`15:09:31`），同时结束（`15:09:36`）。

暂不并发（后续改进）：

- `web_fetch` 需要权限确认，当前 `is_concurrency_safe=False`。解决权限预解析（先收集所有权限需求 → 用户一次性确认 → 并发执行）后，Step 3/5 的 web_fetch+web_search 混合调用可进一步缩短 ~20s

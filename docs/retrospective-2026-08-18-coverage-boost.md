# 复盘：覆盖率 59.9% → 84.4%（2026-08-18）

## 背景
- 用户要求覆盖率门槛不得低于 70%，且不接受暂缓/降低目标。
- 上一轮全量：823 collected / 817 passed / 6 skipped，覆盖率 59.9%。

## 做了什么
- 并行派出多个子代理，按低覆盖模块补测试，新增 12 个 `tests/test_*_more.py`：
  - serve 基础/重型 handler（201 tests）
  - realtime_proxy（59 tests）
  - zhilian / boss_browser（57 tests）
  - playwright_jd / orchestrator（68 tests）
  - cli / repl（45 tests）
  - daemon / providers / scheduler（54 tests）
- 全部使用 mock / temp DB / temp files，不触网、不启真实浏览器、不改源文件。
- 全量回归通过：1307 collected / 1301 passed / 6 skipped / 0 failed。
- 覆盖率 84.4%，门槛从 54 上调到 70。

## 结果
| 指标 | 之前 | 之后 |
|---|---|---|
| 收集测试 | 823 | 1307 |
| 通过测试 | 817 | 1301 |
| 跳过测试 | 6 | 6 |
| 覆盖率 | 59.9% | 84.4% |
| 门槛 | 54 | 70 |

## 经验
- `serve.py` 是最大低覆盖源（2171 stmts），只要把 handler 分支补起来，整体覆盖率提升非常显著。
- 浏览器/平台模块的纯逻辑（解析、URL、错误分支）可以脱离 Playwright 用 mock 覆盖，不必真启动浏览器。
- 并行子代理写测试时，给每个子代理独立的输出文件，避免冲突；各自跑自己的文件验证，最后统一全量回归。
- 子代理全部遵守“不修改源文件、不真调 LLM/网络”约束，回归无新增 flaky。

## 后续
- 可继续补 `zhilian_browser.py`（56.8%）、`interview_prep.py`（68.2%）、`tools.py`（74.9%）等未达 80% 的模块，但不影响 70% 门槛。
- 目录物理重构仍保持非破坏性推进（已提供 `docs/project-structure.md` 索引）。

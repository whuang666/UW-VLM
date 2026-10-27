# UW-VLM 每日提交与变更记录提示词

将下面的提示词交给负责每日执行的 agent。执行时间由它的调度任务配置；本文件本身不会创建定时任务。

```text
你负责 UW-VLM 项目的每日检查、Git 提交、推送与变更记录。每次收到定时唤醒就实际完成一轮，不停在给出建议或命令。

项目根目录：E:\code\UW-VLM
GitHub：https://github.com/whuang666/UW-VLM
主远端：origin
默认分支：main
日期和时间：Asia/Shanghai

授权范围：检查并保存这个项目当天已有的代码、文档及可纳入 Git 的实验产物；补齐维护文档；运行必要的本地检查；正常 commit 和 push。以上操作无需每次询问确认。项目功能开发、付费 API 实验、训练、数据重建和删除不属于本维护任务，不要为凑每日进度自行开展。

1. 从根目录读取 AGENTS.md、README.md、CHANGELOG.md、最近的 docs/daily/ 记录及相关实验执行记录。以当前代码、manifest、预测和 report 为准，区分计划、进行中和实际完成，不把历史 README 的状态直接复制成最新进展。

2. 检查 git status --short、当前分支、git log 和 git remote -v，确认 origin 指向指定仓库。先 git fetch origin；在 main 上如仅落后且工作区干净，可 git merge --ff-only origin/main。分叉、未解决冲突、其他分支或活跃写入导致无法安全提交时，保留所有工作，记录具体情况；不要强制切换分支、reset --hard、clean、自动覆盖冲突、amend 他人提交或 force-push。

3. 检查最近提交之后的变更及未跟踪文件，阅读 diff 和新增实验摘要。将代码、配置、文档、标签／题集版本、实验结果与问题写清楚。对于仍在写入的实验文件只纳入稳定快照，保留未完成状态；不要把半个 run 当成完整成绩，也不要为了提交删掉其他 agent 的修改。

4. 尊重 .gitignore。提交代码、必要配置模板、文档、紧凑题集、输入哈希、原响应／预测、评分和已形成的复核记录。不要提交 API key、token、密码、.env、Authorization 头、原始 USIM 视频／Parquet、模型权重、环境、缓存、临时裁剪拼图或大文件。检查拟提交内容与大小，不使用 git add -f 绕过规则；发现疑似凭据时不要在回复或日志中展示其值。

5. 根据变化运行必要检查。下载／核验工具的现有回归命令是：
   python -m unittest discover -s tools -p 'test_*.py' -v
   USIM 评分链路的现有命令是从 ENACT/ 执行：
   python scripts/usim/check_scoring_contract.py
   评分契约检查会写证据文件；优先在临时独立 checkout 中运行，避免把验证环境路径写回冻结证据。只改文档时检查 Markdown 链接与格式即可；新增或修改程序时执行相关检查。环境缺依赖时如实记为未验证，不把未运行写成通过，不调用付费 API 来做每日例行检查。

6. 在 docs/daily/YYYY-MM-DD.md 中追加带时间的中文记录，遵循 docs/daily/README.md；有实质变化时同步更新 CHANGELOG.md。记录变化原因、涉及路径、实际验证结果、实验版本／结果／限制及下一步。无业务变化时也记录“无实质变化”和当天检查结果，提交本次记录；不要改无关文件制造变化。

7. 按逻辑批次显式 git add 拟提交路径，检查 git diff --cached --stat 和实际 diff。不要笼统暂存不明来源文件。使用准确简短的提交标题，例如 feat: ...、fix: ...、docs: ...，仅每日检查可用 chore: daily project record YYYY-MM-DD。提交前检查文件是否仍在变化，避免纳入不一致的实验产物。不要提前在记录中声称本次 commit／push 已成功，因为日志本身也在本次提交内。

8. 执行普通 git commit 和 git push origin main。若远端在期间前进，重新 fetch 并检查差异；仅在没有冲突且能保留本地工作的情况下整合后重试。若凭据不可用、网络失败、分支保护或冲突阻止推送，保留本地提交并如实报告，不循环重试、不强推。

9. 推送后核对 git rev-parse HEAD 与 git ls-remote origin refs/heads/main 的 SHA 一致，并检查 git status。只有本地和远端 SHA 一致时才报告“已推送”。最后用中文给出：主要变化、记录文件路径、验证结果、提交 SHA、GitHub 提交链接、是否已推送，以及仍未提交／进行中的内容。当天无业务变化时保持简短；需要用户处理的阻塞要明确说明。
```

# UW-VLM workspace guidance

- Git root: this directory (`E:\code\UW-VLM` on the current Windows machine).
- Primary remote: `origin`, `https://github.com/whuang666/UW-VLM.git`; primary branch: `main`.
- `ENACT/` is a tracked subtree, not a separate working repository. Run workspace Git commands from the root.
- Read the root README and current artifacts before relying on historical plans. Keep development evaluation distinct from final test results.
- Preserve frozen dataset versions, predictions, original responses, provenance and source licenses. New labels, prompts, inputs or scoring contracts need explicit versions and separate runs.
- Do not commit credentials, original USIM recordings, model weights, environments or temporary review crops. Respect `.gitignore`; do not force-add excluded data.
- On Windows, `VLM_API_KEY` is persisted in the current user's environment. If an already-open app has no process value, read `[Environment]::GetEnvironmentVariable('VLM_API_KEY', 'User')` into the process environment before running inference. Never print the value or copy it into workspace files.
- For the daily maintenance task, follow [the daily prompt](docs/workbuddyRead/daily_commit_prompt_zh.md), append evidence to `docs/daily/YYYY-MM-DD.md` using Asia/Shanghai dates, and update `CHANGELOG.md` for substantive changes.
- Existing checks: `python -m unittest discover -s tools -p 'test_*.py' -v`; from `ENACT/`, `python scripts/usim/check_scoring_contract.py`. Prefer an isolated checkout for checks that rewrite evidence.
- User-authorized ordinary commits and pushes do not require repeated confirmation. Do not force-push, discard concurrent work, or resolve another contributor's conflicts by overwriting their files.

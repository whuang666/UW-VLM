# USIM 下载与完整性核验

数据目录：`E:\code\UW-VLM\usim`。这套工具只使用 Python 标准库和系统 curl，不需要改动 Conda 环境。

**2026-10-23 补下载已完成。** 6,840 个远端文件全部通过内容哈希核验，缺失与不一致均为 0。train 为 1,750 个 Parquet、3,500 个视频；test 为 525 个 Parquet、1,050 个视频。全部 Parquet footer 的总帧数与元数据一致；使用隔离的 PyArrow 23.0.1 全表抽读 6 个 Parquet，并抽查 12 个视频的首、中、末帧，36/36 帧解码成功。详见 [下载记录](../usim/_download_manifest.json)、[哈希报告](_hfcache/verification.json) 和 [读取检查](_hfcache/readability.json)。

## 为什么之前没下全

Hugging Face 的递归 tree API 仍然分页，每页最多 1,000 条，文件夹也占条数。原脚本只读取 `test`、`train` 的第一页，并把这个不完整清单当作全集，导致本地缺少训练视频、训练元数据及部分其他文件。旧 `_download_manifest.json` 中关于“上游缺失”的结论不成立。

2026-10-23 实查，提交 `88c3612bf99d10652f19ec531052a38c04f0202e` 共 6,840 个文件、4,219,493,970 字节，完整清单需要 7 页。原本地已有 1,984 个远端文件，缺 4,856 个、3,550,670,971 字节。

## 补下载

在 PowerShell 中运行：

```powershell
Set-Location E:\code\UW-VLM
python tools/hf_snapshot_download.py Vincent2025hello/usim usim --endpoint https://huggingface.co --revision 88c3612bf99d10652f19ec531052a38c04f0202e
curl.exe -K tools/_hfcache/curl_all.cfg
python tools/hf_verify.py tools/_hfcache/expected.json usim --promote-partials
```

第一步获取全部分页，并与同一提交的仓库文件全集交叉检查；验证已有文件内容后，只计划缺失或损坏的文件。下载链接固定到提交，不会在下载中途随 `main` 改变。

大文件对照远端 LFS SHA-256，普通 Git 文件对照 Git blob SHA-1；不是只比较文件大小。curl 写入 `.incomplete`，校验通过才改为正式文件名。中断后可重跑上述三步：已经完整的文件会复用，单个未完成文件会重新下载。已有的旧版 expected 清单没有哈希，须先运行第一步重新生成。

规划器会把系统 HTTPS 代理加入 curl 配置，以兼容 Windows 上 Python 能联网、curl 却超时的情况。也可用 `--proxy http://127.0.0.1:7897` 明确指定；端口以本机实际设置为准。当前实测官网可用，镜像站连接超时。

## 核验记录

- `tools/_hfcache/initial_audit.json`：补下载前的缺失数量与分类。
- `tools/_hfcache/remote_snapshot.json`：固定提交的完整远端清单与分页来源。
- `tools/_hfcache/expected.json`：每个文件的预期大小及内容哈希。
- `tools/_hfcache/verification.json`：最近一次完整性核验结果；`complete=true` 表示远端发布文件全部通过。
- `usim/_download_manifest.json`：已更新的完整下载记录，含固定提交、补下载数量与核验报告位置。

Python 读取兼容性是另一项检查。旧的 PyArrow 19 曾报 `Repetition level histogram size mismatch`；已有隔离的 PyArrow 23.0.1 可以读取同一文件。不要据此直接重编码原始 Parquet。

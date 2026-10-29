# Test reserve六条初标交付与独立复核入口

日期：2026-10-28（Asia/Shanghai）。批次：`test-reserve-initial-20261028-v1`。

本轮完成剩余6条的逐帧初标与结构／源帧检查，新增API调用0。加上原4条，当前是 **10/10已形成初标候选、10/10结构／源帧通过**；不代表10条已完成独立质量验收。

## 初标文件与范围

新文件位于：

`ENACT/data/usim_enact/_expansion/annotation_work/test_reserve/initial_20261028_v1/`

每条包含 `spec_XXXXXX.json`、`usim_train_episode_XXXXXX.json`、`checks_XXXXXX.json`、`notes_XXXXXX.md`。批次清单为 `batch_manifest.json`。这是独立版本的工作目录，没有向已冻结的v0.2 dev/val数据根写入新标签。

| episode | 任务 | 关键帧：start / approach / grasp / lift候选 | close主锚 | 保持段长度 |
|---|---|---|---:|---|
| 1734 | pipe | 150 / 274 / 312 / 359 | 294 | 20 / 18 / 20 / 22 |
| 1259 | blue cylinder | 57 / 170 / 203 / 238 | **190** | 26 / 16 / 14 / 16 |
| 1273 | blue cylinder | 179 / 261 / 288 / 348 | 271 | 14 / 12 / 12 / 16 |
| 1145 | red cylinder | 88 / 128 / 161 / 192 | 141 | 20 / 20 / 16 / 16 |
| 1497 | red cylinder | 42 / 111 / 145 / 183 | 129 | 12 / 14 / 18 / 18 |
| 1549 | red cylinder | 75 / 183 / 219 / 277 | 199 | 22 / 22 / 20 / 18 |

先目检ego候选及相邻姿态，再选择同一稳定渲染段的中间帧，并限制在既有角色窗口；没有按模型答案选帧。最短保持段12帧，关键帧间至少27帧且至少2个渲染更新。蓝圆柱在ego中呈紫色；红／蓝干扰物没有混入目标事实。

所有新增文件使用 `annotation_status=initial_review_pending_independent`；批次和逐条检查均标明 `release_eligible=false`。布尔事实是初标者的候选解释，不能当作已经确认的最终test真值。没有声称InBox或为这些普通pick任务构造L5。

## 必须保留的争议

1. **1259的多次尝试**：close159 → open186 → close190。start57早于第一次尝试，主线以最后close190定位。approach170位于第一次闭合信号高位，但渲染图中的手指仍张开、目标未明显被携带；初标为未持有而已接近。必须由独立复核者判断该帧的实际持有关系，以及203帧是否仍有地面支撑，不能从信号反推。
2. **抓住不等于离底**：6条的grasp均将物理支撑作为单独判断；几乎无纹理的沙面使部分支撑证据不够强，已逐条记录，不能仅因DVL接近最低就证明OnSeabed=true。
3. **lift阈值没有被结构检查证明**：候选帧都可看到目标随夹爪保持，部分背景／目标姿态变化与上升一致；但“离底间隙至少半物体宽”没有逐帧量测或独立确认。1497为重点弱例，原1378的f250争议也继续保留。
4. **DVL锚点只是提议**：本轮沿用已有初标中常用的“局部最低点后40–60帧”候选窗口，并显式记录该最低点代理；它不能自动证明规范中的真实ascent onset。逐条报告 `normative_ascent_onset_independently_confirmed=false`，须在最终验收中裁决，不为凑4状态改阈值。

因此当前完成的是六条可复核初标，而非六条已获最终视觉准入的test样本。无法确认时，应回退题长或保留不适用裁决，不根据之后的test模型成绩修标签。

## 检查结果

新增6条各4帧、3个非空标签转移，共24帧／18转移；原4条加在一起为42帧／32转移。对10条重新读取JSON，并用现有 `annotation_report` 与 `verify_frames` 检查；新增6条又逐一运行原 `annotate_episode.py --annotation ... --check --verify-frames`。

这里的“可见转移”来自标签／可见性编译结果，**不是独立的人眼可判性通过**。原主冻结13组和副指标冻结均核验通过，原评分契约通过。测试结果另见本批 `unit_test_receipt.json`，不把单元测试当作视觉验收。

机器证据：`ENACT/docs/WBW/evidence/test_reserve_initial_20261028_v1/` 下的批次清单、6份逐条检查、10条inventory及冻结保存证据。初标工作文件按原 `.gitignore` 留在本地，不force-add；临时PNG同样不入库。

## 给独立复核者的盲核包

目录：

`ENACT/data/usim_enact/_review/test_reserve/round_20261028/independent_packets/`

包含10个episode子目录，每条提供原生ego图、辅助wrist图、按slot编号的对照网格、空的 `review_worksheet.json`。`blind_inventory.json` 给出源帧号与哈希，不含初标谓词答案。

复核顺序：

1. 先读既有v0.2标注规范；查看ego图，自行填写各slot谓词、物体可见性和每个转移的ego可判性。
2. 重点检查grasp的物理支撑、lift的半物体宽间隙与ascent onset；腕相机和DVL只能作辅助。
3. 填写真实的复核者身份及是否独立于初标者；本轮这些字段均留空，`review_complete=false`，不代填通过。
4. 先形成自己的意见，再打开初标spec对照分歧并记录裁决；任何降级／拒绝都保留原因。
5. 只有独立裁决和最终运行协议／test输入都冻结后，才允许这些样本进入正式test。

同一初标者重读一次不能算独立双标。本轮没有新增独立复核者，也没有把任何初标候选写为最终accepted。

## 可复跑的只读检查

在仓库根目录：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$testInitial = 'ENACT/data/usim_enact/_expansion/annotation_work/test_reserve/initial_20261028_v1'

Get-ChildItem -LiteralPath $testInitial -Filter 'usim_train_episode_*.json' | ForEach-Object {
    & $py ENACT/scripts/usim/annotate_episode.py --annotation $_.FullName --check --verify-frames
}

# 重建候选证据，不自动赋标签，也不改变初标spec
& $py ENACT/scripts/usim/prepare_test_annotation_evidence.py --episodes 1734,1259,1273,1145,1497,1549
```

不要直接对工作目录所有JSON用 `--annotations`，因为其中还包括spec、checks和batch清单；应按上述annotation文件名筛选。

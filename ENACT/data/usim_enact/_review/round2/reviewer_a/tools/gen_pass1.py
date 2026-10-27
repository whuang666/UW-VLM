"""Generate Pass-1 blind review JSON for reviewer_a (A group: episodes 200/201/552).

The judgement payload below was produced from ego-only material:
  * the 4 key-frame raw images of each packet (identical to the QA images outside
    the burned top-left overlay, verified numerically),
  * +/-20 frame contact sheets (2x, fixed image-only crop),
  * unique-render contact sheets of the whole episode (the videos hold each
    rendered image for ~8-14 frames),
  * numeric colour-blob boxes of the target object (no gt involved).
No annotation file, no action text and no wrist video was opened before this file
was written.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("E:/code/UW-VLM/ENACT/data/usim_enact/_review/round2/reviewer_a")
PASS1 = BASE / "pass1"
PACKETS = BASE.parent / "packets" / "reviewer_a"
TOOLS_OUT = BASE / "tools_out"

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- frame facts
# value: "true" | "false" | "undecidable"  (three-valued, docs/04 §3)
# ego_only: can the relation be decided from the QA images the model received?
#   "yes"     = clear pixel evidence in a single frame
#   "partial" = needs cross-frame comparison of the L/R images or a metric
#               threshold that ego cannot calibrate
#   "no"      = not determinable from ego input alone
FRAMES = {
    "usim_train_episode_000200": {
        "blue_cylinder": {
            140: {
                "hold_run": [138, 149], "neighbor_runs": {"prev": [128, 137], "next": [150, 150]},
                "object_bbox": [116, 112, 13, 18],
                "gripper_bbox_approx": [86, 100, 120, 128],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂从画面上缘进入，双指夹爪位于 x≈86–120, y≈100–128，浅灰色、与沙底对比明显；完整可辨。"},
                    "blue_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[116,112,13,18]（紫色/蓝色细圆柱），整条轮廓压在亮色沙底上，无遮挡。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 12,
                    "action_in_progress": True,
                    "semantic_phase": "接近-接触起始（夹爪已抵到物体顶端，尚未闭合）",
                    "better_frame_within_20": {"frame": 130,
                        "why": "若关键帧意图是『目标物静止在海床上、尚未被碰』的干净状态，run 128–137 更合适；f140 已处于接触瞬间，物体被夹爪顶得倾斜。"},
                },
                "relations": {
                    "OnSeabed": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "圆柱底端约在 (118,128) 与亮色沙底相接，底端以下没有缝隙/阴影分离；物体整体立在沙面上，无其它支撑。"},
                    "InGripper": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "双指明显张开（左指 x≈86–107，右指 x≈111–119，y≈100–128），物体仅与右指尖相邻、未被两指包夹；从单张 ego 图无法排除远端手指被物体或自身挡住，故 medium。"},
                    "Lifted": {"value": "false", "confidence": "medium-high", "ego_only": "partial",
                        "evidence": "物体底端仍压在沙面上，没有可见的离底间隙或其投射阴影与本体分离；画面中沙底占满下半幅，符合贴底姿态。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "末端夹爪与物体在图像上相距约一个指长（≈10–20 px），机械臂已处于可接触范围；但 NextTo 若有明确距离阈值/三维位姿定义，ego 无法标定，故仅 partial。"},
                },
            },
            213: {
                "hold_run": [210, 231], "neighbor_runs": {"prev": [209, 209], "next": [232, 255]},
                "object_bbox": [100, 118, 16, 17],
                "gripper_bbox_approx": [93, 100, 122, 142],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "夹爪/机械臂清晰位于画面上部（x≈93–122, y≈100–142），两指形状可辨。"},
                    "blue_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[100,118,16,17]，已由竖直转为近水平、位于两指之间偏下，主体可见。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 22,
                    "action_in_progress": True,
                    "semantic_phase": "抓取进行中：物体被夹爪拨倒/进入指间，夹爪尚未闭合",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "undecidable", "confidence": "low", "ego_only": "no",
                        "evidence": "圆柱已近水平，下端约在 (100,135) 附近贴近亮色沙面；单张 ego 图上该端与沙底之间既看不到明确空隙也看不到明确接触阴影，无法区分『仍以一端搭在沙上』与『已被抬起 1–2 cm』。"},
                    "InGripper": {"value": "false", "confidence": "medium", "ego_only": "yes",
                        "evidence": "两指仍有可见间隙（指间开度约 10–20 px），物体靠在右指一侧而非被夹紧；夹爪尚未闭合（视觉可见的张开形态，未用关节信号）。"},
                    "Lifted": {"value": "false", "confidence": "medium-high", "ego_only": "partial",
                        "evidence": "物体仍停留在沙面高度、附近无离底间隙；画面下缘全为沙底，未见抬升后的背景变化。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体已进入夹爪指间/接触范围，机器人末端与物体相邻；阈值语义同 f140 的说明。"},
                },
            },
            248: {
                "hold_run": [232, 255], "neighbor_runs": {"prev": [210, 231], "next": [256, 256]},
                "object_bbox": [98, 120, 23, 24],
                "gripper_bbox_approx": [92, 95, 122, 152],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂与双指夹爪清晰（x≈92–122, y≈95–152），指形可辨。"},
                    "blue_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[98,120,23,24]，斜挂于夹爪下、与右指重叠约 1/4，但圆柱轮廓与两端仍可辨认。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 24,
                    "action_in_progress": True,
                    "semantic_phase": "已夹住、尚未升起（夹爪闭合后的保持段）",
                    "better_frame_within_20": {"frame": 256,
                        "why": "f232–255 为同一个渲染保持帧；f248 已在该段后 16 帧，语义上仍是『刚夹住』状态，无需换帧，但若要『夹住』最干净的画面可用 f256–267 段（物体姿态更稳定）。"},
                },
                "relations": {
                    "OnSeabed": {"value": "undecidable", "confidence": "low", "ego_only": "no",
                        "evidence": "物体被夹爪夹住上端、斜向下垂，下端约在 (98,143) 贴近沙面；图中该端与沙底之间没有可分辨的间隙，但也看不到明确的接触压痕/阴影，ego 单帧无法判定是否仍触底。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指已收拢（左指 x≈95–104、右指 x≈110–121，y≈100–150），圆柱 bbox [98,120,23,24] 的两端分别落在两指前后，形成包夹；物体随指形改变姿态，不再独立立在沙上。"},
                    "Lifted": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体仍在画面下部、贴近沙面；沙底仍占满画面下半，未见抬升造成的背景变化或离底阴影分离。若按『夹住即算离底』的定义则应判 true，故标注定义需明确（见 pass2/3）。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "夹爪正夹持物体，机器人与物体在几何上最近（接触）；若 NextTo 定义为『尚未接触的接近阶段』则应为 false——本项判定依赖定义，见语义备注。"},
                },
            },
            328: {
                "hold_run": [306, 331], "neighbor_runs": {"prev": [290, 305], "next": [332, 341]},
                "object_bbox": [100, 110, 14, 14],
                "gripper_bbox_approx": [95, 100, 122, 140],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂/夹爪清晰（x≈95–122, y≈100–140）。"},
                    "blue_cylinder": {"value": "partial", "confidence": "high",
                                      "evidence": "目标物 bbox≈[100,110,14,14]，被右指压住约 30–40%，颜色块变小；但圆柱外形与夹持关系仍可辨认，故 partial 而非 not_visible。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 26,
                    "action_in_progress": False,
                    "semantic_phase": "终态：夹持并已随载具上浮（episode 末段）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体被夹爪悬持，物体下方与沙面之间可见亮色沙底与分离的暗色阴影，没有接触点；与 f248 相比物体与沙面的相对高度增加。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指分列物体两侧（左指尖 x≈100,y≈115；右指 x≈112–118,y≈105–135），圆柱横夹于指间。"},
                    "Lifted": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体离底悬持：物体下缘与沙面之间可见间隙/阴影分离。单帧证据偏弱，需与同题其它关键帧（如 f248）比较相对高度；本复核同时参考了 episode 末段整体趋势，故 medium。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "几何上机器人末端正夹持物体；定义依赖项（同 f248）。"},
                },
            },
        },
    },
    "usim_train_episode_000201": {
        "blue_cylinder": {
            199: {
                "hold_run": [190, 213], "neighbor_runs": {"prev": [164, 189], "next": [214, 233]},
                "object_bbox": [184, 166, 17, 43],
                "gripper_bbox_approx": [88, 55, 122, 118],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "双指夹爪张口朝下位于画面上部（x≈88–122, y≈55–118），浅灰色、与蓝色水体对比清晰。"},
                    "blue_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[184,166,17,43]，竖立在画面右下亮色沙面上，完整可见。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 24,
                    "action_in_progress": True,
                    "semantic_phase": "远距接近（机器人尚未贴近物体）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "圆柱底端约在 (192,208) 落在亮色沙面上，周围沙面连续、无缝隙；物体静止竖立，无夹持。"},
                    "InGripper": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "夹爪位于画面上部（y≈55–118），物体在右下（y≈166–209），两者图像间距 >90 px，中间无接触；夹爪张口朝下、明显未抓取。"},
                    "Lifted": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "物体底端与沙面接触，无离底间隙阴影；仍处于初始静止状态。"},
                    "NextTo(robot,blue_cylinder)": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "夹爪与物体图像距离约 90–130 px（数十厘米量级），明显不在接触范围；若 NextTo 阈值较宽则可能为 true，ego 无法标定阈值，故 medium。"},
                },
            },
            244: {
                "hold_run": [236, 253], "neighbor_runs": {"prev": [235, 235], "next": [254, 254]},
                "object_bbox": [88, 126, 24, 28],
                "gripper_bbox_approx": [92, 78, 120, 122],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂+双指夹爪位于画面上部（x≈92–120, y≈78–122）。"},
                    "blue_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[88,126,24,28]，水平躺在沙面上，轮廓完整、无遮挡。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 18,
                    "action_in_progress": True,
                    "semantic_phase": "贴近-抓取前定位（夹爪悬在物体上方，未接触）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "圆柱整体平放在亮色沙面上，物体下缘与沙面贴合、周围可见接触阴影，无夹持。"},
                    "InGripper": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "两指张开且指尖最低点在 y≈120，物体上缘在 y≈126，图像上仍有约 6–10 px 间隙；物体未被包夹。"},
                    "Lifted": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "物体平贴沙面，无离底间隙。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "夹爪指尖与物体上缘仅相距约 6–10 px，处于可立即抓取的范围，机器人明显已『来到物体旁』。"},
                },
            },
            279: {
                "hold_run": [276, 293], "neighbor_runs": {"prev": [275, 275], "next": [294, 294]},
                "object_bbox": [100, 112, 12, 14],
                "gripper_bbox_approx": [92, 95, 118, 135],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂与夹爪位于画面上部（x≈92–118, y≈95–135）。"},
                    "blue_cylinder": {"value": "visible", "confidence": "medium",
                                      "evidence": "目标物 bbox≈[100,112,12,14]，上端被双指夹住、部分被指体遮挡；圆柱主体与下端可见，形状可辨。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 18,
                    "action_in_progress": True,
                    "semantic_phase": "刚夹住、尚未上浮（中间状态）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "undecidable", "confidence": "low", "ego_only": "no",
                        "evidence": "物体上端被夹住、斜垂向沙面，下端约在 (100,126) 贴近沙面；单帧内看不到下端与沙面的明确间隙或接触点，无法判定是否仍触底。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指合拢、分列物体上端两侧，物体与指体一起运动、随指形改变倾角；圆柱被夹持。"},
                    "Lifted": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体高度与沙面齐平，未见离底间隙；未上浮前不应记 lifted。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "几何上机器人末端正夹持物体；定义依赖项。"},
                },
            },
            357: {
                "hold_run": [356, 367], "neighbor_runs": {"prev": [336, 355], "next": None},
                "object_bbox": [100, 108, 10, 16],
                "gripper_bbox_approx": [95, 90, 118, 135],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂/夹爪位于画面上部（x≈95–118, y≈90–135）。"},
                    "blue_cylinder": {"value": "visible", "confidence": "medium",
                                      "evidence": "目标物 bbox≈[100,108,10,16]，被双指夹持且部分被右指遮挡；蓝色/紫色本体与圆柱形状仍可辨认（同帧左下方另有红色小鱼，不属 scope）。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 12,
                    "action_in_progress": False,
                    "semantic_phase": "终态：夹持并已上浮",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体悬在夹爪上、下方沙面与物体之间可见分离的阴影/空隙，无接触点。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指分列物体两侧并夹紧，物体横挂于指间。"},
                    "Lifted": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体离底：与沙面之间可见间隙/阴影分离，且与 key3(f279) 相比海床远缘在画面中更低（相对高度增加），符合上浮；单帧证据有限故 medium。"},
                    "NextTo(robot,blue_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "几何上夹爪正持物体；定义依赖项。"},
                },
            },
        },
    },
    "usim_train_episode_000552": {
        "red_cylinder": {
            120: {
                "hold_run": [116, 127], "neighbor_runs": {"prev": [115, 115], "next": [128, 128]},
                "object_bbox": [124, 96, 15, 22],
                "gripper_bbox_approx": [79, 95, 119, 121],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂与双指夹爪位于画面左上（x≈79–119, y≈95–121）。"},
                    "red_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[124,96,15,22]，红色/肉色细圆柱斜立在亮色沙面上、完整可见。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 12,
                    "action_in_progress": True,
                    "semantic_phase": "贴近-抓取前（夹爪在物体左上，未接触）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "圆柱底端约在 (133,118) 与亮色沙面相接，周围沙面连续；物体独立静止、无夹持。"},
                    "InGripper": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "两指张开、指尖位于 x≈100–119，物体左缘在 x≈124，图像上仍有约 5–10 px 的可见间隙，未接触。"},
                    "Lifted": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "物体立于沙面，无离底间隙。"},
                    "NextTo(robot,red_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "夹爪与物体图像间距约 5–10 px，机器人已来到物体旁；阈值语义依赖定义，故 medium。"},
                },
            },
            249: {
                "hold_run": [242, 267], "neighbor_runs": {"prev": [241, 241], "next": [268, 291]},
                "object_bbox": [101, 126, 17, 26],
                "gripper_bbox_approx": [95, 105, 120, 140],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂/夹爪位于画面上部（x≈95–120, y≈105–140）。"},
                    "red_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[101,126,17,26]，斜躺在沙面上，主体与两端可见（同帧左上另有蓝色条状干扰物，不属 scope）。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 26,
                    "action_in_progress": True,
                    "semantic_phase": "夹爪下降到物体上、接触/预夹紧（尚未闭合）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "圆柱下端约在 (108,152) 靠近亮色沙面，主体仍斜倚在沙面上、未见明显离底阴影；但下端与沙面的接触/微小间隙在 ego 上不够清晰，故 medium。"},
                    "InGripper": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "两指仍有开口、指尖抵在物体上端两侧（右指与物体上端有接触），但未合拢包夹；『接触但未夹住』。"},
                    "Lifted": {"value": "false", "confidence": "high", "ego_only": "yes",
                        "evidence": "物体仍在沙面高度、下端贴近沙面；画面下半全为沙底，无抬升迹象。"},
                    "NextTo(robot,red_cylinder)": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "夹爪指尖直接接触/覆于物体上端，机器人末端与物体已到最近距离。"},
                },
            },
            284: {
                "hold_run": [268, 291], "neighbor_runs": {"prev": [242, 267], "next": [292, 315]},
                "object_bbox": [102, 124, 14, 20],
                "gripper_bbox_approx": [95, 100, 118, 142],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂/夹爪位于画面上部（x≈95–118, y≈100–142）。"},
                    "red_cylinder": {"value": "visible", "confidence": "high",
                                      "evidence": "目标物 bbox≈[102,124,14,20]，斜挂于夹爪下方、部分与指体重叠，红色圆柱轮廓可辨。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 24,
                    "action_in_progress": True,
                    "semantic_phase": "刚夹住、尚未上浮（中间状态）",
                    "better_frame_within_20": None,
                },
                "relations": {
                    "OnSeabed": {"value": "undecidable", "confidence": "low", "ego_only": "no",
                        "evidence": "物体上端被夹住、斜垂向沙面，下端约在 (102,144) 贴近沙面；单帧看不到明确的接触点或间隙，无法判定是否仍触底。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指已合拢并夹住物体上端，物体随夹爪一起改变姿态；夹持关系清晰。"},
                    "Lifted": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体仍处沙面高度、未见离底间隙或背景变化，尚未上浮。"},
                    "NextTo(robot,red_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "几何上夹爪正持物体；定义依赖项。"},
                },
            },
            364: {
                "hold_run": [362, 373], "neighbor_runs": {"prev": [344, 361], "next": None},
                "object_bbox": [98, 116, 4, 4],
                "gripper_bbox_approx": [95, 105, 120, 145],
                "visibility": {
                    "robot": {"value": "visible", "confidence": "high",
                              "evidence": "机械臂/夹爪位于画面左上（x≈95–120, y≈105–145）。"},
                    "red_cylinder": {"value": "partial", "confidence": "medium",
                                      "evidence": "目标物被双指夹持、与指体重叠且红/肉色在亮沙上对比下降（颜色块检测只剩 ~16 px）；圆柱外形仍可辨，但可读性明显差于前三帧（同帧左侧另有蓝色条状干扰物）。"},
                },
                "stability": {
                    "image_static_in_hold_run": True, "hold_run_frames": 12,
                    "action_in_progress": False,
                    "semantic_phase": "终态：夹持并已上浮",
                    "better_frame_within_20": {"frame": 344,
                        "why": "若需要更清晰的『夹持中』画面，run 344–361 较早且物体未被前景结构压住；但 f364 是 episode 末态，语义正确。"},
                },
                "relations": {
                    "OnSeabed": {"value": "false", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体横夹在夹爪中、下方沙面与物体间可见分离阴影/空隙，无接触点。"},
                    "InGripper": {"value": "true", "confidence": "high", "ego_only": "yes",
                        "evidence": "双指分列物体两侧并夹紧，物体横挂于指间、随夹爪运动。"},
                    "Lifted": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "物体离底悬持：下方可见沙面与分离阴影；与 key3(f284) 相比物体不再贴近沙面，符合 episode 末段载具上浮（同题跨帧比较可得，单帧证据弱）。"},
                    "NextTo(robot,red_cylinder)": {"value": "true", "confidence": "medium", "ego_only": "partial",
                        "evidence": "几何上夹爪正持物体；定义依赖项。"},
                },
            },
        },
    },
}

NEXTTO_SEMANTIC_NOTE = (
    "NextTo 存在定义歧义：若按几何接近（robot 末端与 object 的距离小于阈值/接触），"
    "则抓住后仍为 true；若按『尚未接触的接近阶段』，则抓住后应为 false。"
    "本 pass1 按自然几何语义判定，并在 pass2 对照 v0.1 标注、pass3 给出裁决。"
)

TRANSITION_PREDICTIONS = {
    "usim_train_episode_000200": [
        {"from": 140, "to": 213,
         "predicted_net_change": ["OnSeabed true→undecidable（物体被拨倒；是否仍触底 ego 不可判）"],
         "risk": "若标注在 f213 仍为 OnSeabed=true，则该相邻转移在 relation_scope 内可能为空 → 与 manifest『21 个转移均非空』冲突。",
         "ego_only_judgeable": "partial"},
        {"from": 213, "to": 248,
         "predicted_net_change": ["InGripper false→true"],
         "risk": "仅在 g 闭合瞬间可区分；若标注对 f213 也记 InGripper=true 则空。",
         "ego_only_judgeable": "yes"},
        {"from": 248, "to": 328,
         "predicted_net_change": ["Lifted false→true", "OnSeabed undecidable→false"],
         "risk": "Lifted 的单帧 ego 证据弱，需跨帧比较；NextTo 若按几何语义两边同为 true（不构成变化）。",
         "ego_only_judgeable": "partial"},
    ],
    "usim_train_episode_000201": [
        {"from": 199, "to": 244,
         "predicted_net_change": ["NextTo false→true"],
         "risk": "该转移的唯一净变化是 NextTo（距离阈值语义），若阈值/定义不清则不可复核；ego 无法标定阈值。",
         "ego_only_judgeable": "partial"},
        {"from": 244, "to": 279,
         "predicted_net_change": ["InGripper false→true", "OnSeabed true→undecidable"],
         "risk": "抓取变化本身可见；OnSeabed 的翻转依赖定义（夹住即离底？）。",
         "ego_only_judgeable": "partial"},
        {"from": 279, "to": 357,
         "predicted_net_change": ["Lifted false→true"],
         "risk": "上浮幅度小（约 15 cm），ego 单帧难以判断，需跨帧比较。",
         "ego_only_judgeable": "partial"},
    ],
    "usim_train_episode_000552": [
        {"from": 120, "to": 249,
         "predicted_net_change": [],
         "risk": "按本 pass1 判定，f120 与 f249 在 4 个 scope 谓词上取值相同（OnSeabed=T, InGripper=F, Lifted=F, NextTo=T）→ 该相邻转移可能为空；可见变化只有『夹爪下降/贴近程度』，需 v0.2 明确定义 NextTo 阈值或引入接近阶段谓词。",
         "ego_only_judgeable": "no"},
        {"from": 249, "to": 284,
         "predicted_net_change": ["InGripper false→true"],
         "risk": "同 ep200 213→248。",
         "ego_only_judgeable": "partial"},
        {"from": 284, "to": 364,
         "predicted_net_change": ["Lifted false→true", "OnSeabed undecidable→false"],
         "risk": "上浮证据需跨帧比较；物体在 f364 的可读性下降（红色在亮沙上对比降低）。",
         "ego_only_judgeable": "partial"},
    ],
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qa_index(packet: dict) -> dict:
    """frame -> list of qa ids (sanitised: only type + id suffix, no question text)."""
    out = {}
    for k in packet["key_frames"]:
        f = k["frame_index"]
        items = []
        for q in packet["qa_usage"]:
            if str(f) in q["chronological_frame_ids"]:
                items.append(
                    {
                        "id": q["id"],
                        "type": q["type"],
                        "images": q["images"],
                        "chronological_frame_ids": q["chronological_frame_ids"],
                    }
                )
        out[f] = items
    return out


def main() -> int:
    PASS1.mkdir(parents=True, exist_ok=True)
    runs = json.loads((TOOLS_OUT / "runs.json").read_text(encoding="utf-8"))
    pix = json.loads((TOOLS_OUT / "pix_boxes.json").read_text(encoding="utf-8"))
    input_audit_common = {
        "material": "packet key_frames raw images + qa_usage.images (display order, question text withheld)",
        "qa_overlay": {
            "burned_labels": ["Current State", "Next State 1", "Next State 2", "Next State 3"],
            "changed_region_xyxy_max": [7, 9, 160, 29],
            "qa_equals_raw_outside_overlay": True,
            "overlay_occludes_subject_in_key_frames": False,
            "note": "96 张 QA 图与对应 raw 帧逐像素比较：差异仅出现在左上角 y≤29/x≤160 的标签条带；12 个关键帧的主体（夹爪+目标物）均在 y≥55 区域，未被标签覆盖。",
        },
        "frame_hold_structure": {
            "note": "ego 视频为渲染保持式：相邻帧大量完全重复，每个渲染画面保持约 8–14 帧；"
                    "因此 ±10 帧邻域内通常只有 1–2 个不同画面，±20 帧约 3–4 个。",
        },
    }

    per_episode_counts = {}
    totals = {"frames": 0, "relations": 0, "true": 0, "false": 0, "undecidable": 0,
              "ego_only_yes": 0, "ego_only_partial": 0, "ego_only_no": 0}
    predicate_counts = {}

    for ep_key, obj_frames in FRAMES.items():
        obj_id = next(iter(obj_frames))
        frames = obj_frames[obj_id]
        packet = json.loads((PACKETS / f"{ep_key}.json").read_text(encoding="utf-8"))
        qmap = qa_index(packet)
        run_rec = runs[str(int(ep_key.split("_")[-1]))]
        out_frames = []
        for f in sorted(frames):
            rec = frames[f]
            pred = rec["relations"]
            # merge OnSeabed / InGripper / Lifted / NextTo into stable list
            merged = []
            for name, payload in pred.items():
                if name.startswith("NextTo"):
                    predicate, args = "NextTo", ["robot", packet["objects"][1]["object_id"]]
                else:
                    predicate, args = name, [packet["objects"][1]["object_id"]]
                merged.append({"predicate": predicate, "arguments": args, **payload})
                key = predicate
                predicate_counts.setdefault(key, {"true": 0, "false": 0, "undecidable": 0})
                predicate_counts[key][payload["value"]] += 1
                totals[payload["value"]] += 1
                totals["relations"] += 1
                totals[f"ego_only_{payload['ego_only']}"] += 1
            assert len(merged) == 4, (ep_key, f)
            frame_payload = {
                "frame_index": f,
                "timestamp_seconds": next(k["timestamp_seconds"] for k in packet["key_frames"] if k["frame_index"] == f),
                "qa_items": [{"id": q["id"], "type": q["type"], "images": q["images"],
                              "chronological_frame_ids": q["chronological_frame_ids"]} for q in qmap[f]],
                "hold_run": rec["hold_run"],
                "neighbor_runs": rec["neighbor_runs"],
                "object_bbox_xywh": rec["object_bbox"],
                "gripper_bbox_approx_xyxy": rec["gripper_bbox_approx"],
                "visibility": rec["visibility"],
                "stability": rec["stability"],
                "relations": merged,
            }
            out_frames.append(frame_payload)
            totals["frames"] += 1
        episode_payload = {
            "packet_version": "blind-review-20261027",
            "episode_key": ep_key,
            "reviewer": "reviewer_a",
            "pass": 1,
            "blind": True,
            "protocol": "usim-enact-v0.1",
            "task_text": packet["task_text"],
            "objects": packet["objects"],
            "relation_scope": packet["relation_scope"],
            "input_audit": {
                **input_audit_common,
                "episode_frame_hold": {
                    "decoded_frames": int(run_rec["key_frames"][-1]) and None,
                    "unique_content_frames": len(run_rec["runs"]),
                    "runs": run_rec["runs"],
                },
            },
            "nextto_semantic_note": NEXTTO_SEMANTIC_NOTE,
            "frames": out_frames,
            "adjacent_transition_predictions": TRANSITION_PREDICTIONS[ep_key],
        }
        # fill decoded frame count from packet-independent runs info
        run_rec_all = json.loads((TOOLS_OUT / "runs.json").read_text(encoding="utf-8"))
        episode_payload["input_audit"]["episode_frame_hold"]["decoded_frames"] = (
            run_rec_all[str(int(ep_key.split("_")[-1]))]["runs"][-1][1] + 1
        )
        path = PASS1 / f"{ep_key}.json"
        path.write_text(json.dumps(episode_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        per_episode_counts[ep_key] = {
            "frames": len(out_frames),
            "relations": len(out_frames) * 4,
            "true": sum(1 for fr in out_frames for r in fr["relations"] if r["value"] == "true"),
            "false": sum(1 for fr in out_frames for r in fr["relations"] if r["value"] == "false"),
            "undecidable": sum(1 for fr in out_frames for r in fr["relations"] if r["value"] == "undecidable"),
            "file": str(path.relative_to(BASE)).replace("\\", "/"),
            "sha256": _sha256(path),
        }
        print("wrote", path, path.stat().st_size, "bytes")

    summary = {
        "reviewer": "reviewer_a",
        "pass": 1,
        "blind": True,
        "packet_version": "blind-review-20261027",
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "episodes": per_episode_counts,
        "totals": totals,
        "predicate_counts": predicate_counts,
        "key_findings": [
            "QA 图 = raw 帧 + 左上角烧录标签（Current State / Next State N，bbox 最大 [7,9,160,29]）；主体区域未被遮挡，因此 raw 帧可作为等价像素证据。",
            "ego 视频为保持式渲染：ep200 343 帧仅 42 个唯一画面、ep201 368→35、ep552 374→38；每个画面保持约 8–14 帧。±10~20 帧的『邻近帧』多数与关键帧同画面，不能提供额外时间信息。",
            "12 个关键帧全部落在保持段内部（非渲染更新帧），画面静态 12–26 帧，因此『稳定』成立；但 f140/f213/f244/f249 等处于接触/抓取进行中，属过渡语义状态。",
            "关键帧的 4 状态序列与『on seabed → next to → grasped → lifted』生命周期大体吻合；但 4 个谓词是否在两两之间都产生净变化，取决于 OnSeabed 与 NextTo 的定义。",
            "Lifted 在 ego 单帧上证据最弱：上浮仅约 15 cm（辅助信号 dvl_h 0.23→0.40，仅作旁证），单帧无法标定离底高度；需要同题跨帧比较或 wrist 视角。",
            "ep552 120→249：按自然几何 NextTo 语义，两帧四个谓词取值相同，相邻转移可能是空转移 —— 需在 pass2 与标注对照、pass3 用视频/信号裁决。",
        ],
        "nextto_semantic_note": NEXTTO_SEMANTIC_NOTE,
        "pass2_gate": "本 summary 写盘后才读取 annotations/episodes/*.json。",
    }
    spath = PASS1 / "summary.json"
    spath.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", spath)

    lock = {
        "reviewer": "reviewer_a",
        "pass": 1,
        "locked_at": datetime.now(CST).isoformat(timespec="seconds"),
        "note": "Pass-1 盲评文件先写盘并登记哈希；读取 annotations 是在此之后。",
        "files": {
            str(p.relative_to(BASE)).replace("\\", "/"): _sha256(p)
            for p in sorted(PASS1.glob("*.json"))
        },
    }
    lpath = PASS1 / "pass1_lock.json"
    lpath.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", lpath)
    print(json.dumps(lock, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

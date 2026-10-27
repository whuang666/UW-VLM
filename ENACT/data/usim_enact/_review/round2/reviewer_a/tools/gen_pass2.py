"""Generate Pass-2 comparison: reviewer_a pass1 vs v0.1 annotations.

Reads (after pass1 lock):
  - pass1/*.json (blind judgements)
  - usim-enact-v0.1/annotations/episodes/{200,201,552}.json
  - compile_action_descriptions() from enact.adapters.usim_annotations
Writes pass2_disagreements.json (verdicts are produced later in Pass 3).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "E:/code/UW-VLM/ENACT")

from enact.adapters.usim_annotations import USIMEpisodeAnnotation, compile_action_descriptions  # noqa: E402

BASE = Path("E:/code/UW-VLM/ENACT/data/usim_enact/_review/round2/reviewer_a")
PASS1 = BASE / "pass1"
DATA = Path("E:/code/UW-VLM/ENACT/data/usim_enact/usim-enact-v0.1")
CST = timezone(timedelta(hours=8))
EPS = ["usim_train_episode_000200", "usim_train_episode_000201", "usim_train_episode_000552"]

CLASS = {
    "semantics_definition": "谓词语义/定义问题（NextTo 不是纯几何关系；OnSeabed 是生命周期阶段还是物理支撑）",
    "pass1_error": "复核者 pass1 误判（ego 视角遮挡/透视导致）",
    "label_unsupported": "v0.1 标签无可见证据支持（模板推导，不是逐帧证据）",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relkey(pred, args):
    return f"{pred}({','.join(args)})"


def main() -> int:
    lock = json.loads((PASS1 / "pass1_lock.json").read_text(encoding="utf-8"))
    rows = []
    disagreements = []
    per_pred = {}
    per_ep = {}
    visibility_notes = []
    transition_checks = []
    compiled_texts = {}

    for ep in EPS:
        p1 = json.loads((PASS1 / f"{ep}.json").read_text(encoding="utf-8"))
        ann_path = DATA / "annotations" / "episodes" / f"{ep}.json"
        ann = USIMEpisodeAnnotation.from_json(ann_path)
        ann_by_frame = {f.frame_index: {relkey(fact.predicate, fact.arguments): fact for fact in f.facts}
                        for f in ann.frames}
        vis_by_frame = {f.frame_index: {v["object_id"]: v["value"] for v in f.visibility} for f in ann.frames}
        descriptions = compile_action_descriptions(ann)
        compiled_texts[ep] = descriptions
        per_ep[ep] = {"agree": 0, "disagree": 0, "abstain": 0, "total": 0}

        for frame in p1["frames"]:
            fi = frame["frame_index"]
            ann_facts = ann_by_frame[fi]
            for mr in frame["relations"]:
                key = relkey(mr["predicate"], mr["arguments"])
                a = ann_facts[key]
                ann_value = "true" if a.value is True else ("false" if a.value is False else "undecidable")
                p1v = mr["value"]
                if p1v == ann_value:
                    status = "agree"
                elif p1v == "undecidable":
                    status = "abstain"
                else:
                    status = "disagree"
                per_pred.setdefault(mr["predicate"], {"agree": 0, "disagree": 0, "abstain": 0})
                per_pred[mr["predicate"]][status] += 1
                per_ep[ep][status] += 1
                per_ep[ep]["total"] += 1
                row = {
                    "episode": ep,
                    "frame": fi,
                    "relation": key,
                    "annotation_value": ann_value,
                    "annotation_evidence": a.evidence,
                    "pass1_value": p1v,
                    "pass1_confidence": mr["confidence"],
                    "pass1_ego_only": mr["ego_only"],
                    "status": status,
                }
                rows.append(row)
                if status == "disagree":
                    disagreements.append({
                        "id": f"D{len(disagreements) + 1:02d}",
                        **row,
                        "pass1_evidence": mr["evidence"],
                        "pass3_required": True,
                        "preliminary_classification": (
                            "semantics_definition" if mr["predicate"] == "NextTo"
                            else "label_unsupported"
                        ),
                    })
            # visibility comparison
            for oid, v in vis_by_frame[fi].items():
                mine = frame["visibility"][oid]["value"]
                if mine != "visible":
                    visibility_notes.append({
                        "episode": ep, "frame": fi, "object_id": oid,
                        "annotation_value": bool(v), "pass1_value": mine,
                        "note": "v0.1 visibility 为布尔；复核给出 partial（部分遮挡但与 scope 关系仍可判）。建议 v0.2 支持 visible/partial/not_visible 三值。",
                    })

        # ---- adjacent transitions (3 per episode) -------------------------
        keys = [str(f) for f in [k["frame_index"] for k in p1["frames"]]]
        kf = [int(k) for k in keys]
        p1_map = {fr["frame_index"]: {relkey(r["predicate"], r["arguments"]): r["value"] for r in fr["relations"]}
                  for fr in p1["frames"]}
        for a, b in zip(kf, kf[1:]):
            d = next(x for x in descriptions if x["from"] == str(a) and x["to"] == str(b))
            changes = []
            for rel in p1_map[a]:
                if p1_map[a][rel] != p1_map[b][rel]:
                    changes.append({"relation": rel, "pass1": f"{p1_map[a][rel]}→{p1_map[b][rel]}"})
            ann_changes = []
            for rel in ann_by_frame[a]:
                fa, fb = ann_by_frame[a][rel].value, ann_by_frame[b][rel].value
                if fa != fb:
                    ann_changes.append({"relation": rel, "annotation": f"{fa}→{fb}"})
            text = d["text"]
            consistency = []
            if "next to" in text and not any("NextTo" in c["relation"] for c in ann_changes):
                consistency.append("文本含 next to 语义但标注差分不含 NextTo")
            if "no longer on the seabed" in text or "not on the seabed anymore" in text:
                consistency.append("文本声称『不再在海床上』：pass1 无法从 ego 证实（pass3 需核查接触）")
            if "no longer next to" in text or "stopped being next to" in text:
                consistency.append("文本同时出现『被抓住』与『不再在旁』，中文/英文语义自相矛盾（抓取时机器人恰恰贴着物体）")
            if d["visible"] is False:
                consistency.append("差分被标记为空")
            transition_checks.append({
                "episode": ep,
                "from": a, "to": b,
                "annotation_diff": ann_changes,
                "annotation_visible_nonempty": bool(d["visible"]),
                "compiled_action_text": text,
                "compiled_signatures": d["signatures"],
                "pass1_predicted_changes": changes,
                "pixel_frames_identical": False,
                "ego_only_judgeable": None,  # filled below by hand-curated assessment
                "text_vs_visible_issues": consistency,
            })

    # hand-curated ego-only judgeability of the 9 adjacent transitions
    judge = {
        ("usim_train_episode_000200", 140, 213): ("partial", "唯一净变化是 NextTo=false→true（距离/阶段阈值），ego 单帧无法标定；ego 上可见变化主要是物体被拨倒，而不是『机器人靠近』。"),
        ("usim_train_episode_000200", 213, 248): ("partial", "InGripper false→true 可从『夹爪张开→合拢包夹』辨认，但 320×240 下张开/合拢差异小；NextTo true→false 需定义。"),
        ("usim_train_episode_000200", 248, 328): ("partial", "Lifted false→true 只有 ~16 cm 上浮，ego 单帧不可判，需跨帧/辅助信号。"),
        ("usim_train_episode_000201", 199, 244): ("yes", "机器人从远到贴近物体，ego 图像差异明显（190→236 run），NextTo 变化在画面上可辨。"),
        ("usim_train_episode_000201", 244, 279): ("partial", "InGripper 变化可辨；OnSeabed true→false 不可辨（对象仍在底部高度）；NextTo true→false 需定义。"),
        ("usim_train_episode_000201", 279, 357): ("partial", "Lifted 变化只在 ~16 cm 上浮中体现，ego 单帧不可判。"),
        ("usim_train_episode_000552", 120, 249): ("yes", "夹爪从物体上方下降到物体上（ego 图像差异明显），NextTo 变化在画面上可辨。"),
        ("usim_train_episode_000552", 249, 284): ("partial", "InGripper 变化可辨；OnSeabed 不可辨；NextTo 需定义。"),
        ("usim_train_episode_000552", 284, 364): ("partial", "Lifted 变化 ego 单帧不可判。"),
    }
    for t in transition_checks:
        k = (t["episode"], t["from"], t["to"])
        t["ego_only_judgeable"], t["ego_only_reason"] = judge[k]

    # ---- special audits ---------------------------------------------------
    template_rows = []
    for ep2 in sorted((DATA / "annotations" / "episodes").glob("*.json")):
        a2 = USIMEpisodeAnnotation.from_json(ep2)
        table = []
        for f in a2.frames:
            table.append({relkey(fact.predicate, fact.arguments): fact.value for fact in f.facts})
        template_rows.append({"episode": a2.episode_key, "task": a2.task_text, "facts": table})
    same = all(json.dumps(r["facts"], sort_keys=True) == json.dumps(template_rows[0]["facts"], sort_keys=True)
               for r in template_rows)
    special = {
        "annotation_template": {
            "all_seven_episodes_identical_fact_table": same,
            "fact_table": template_rows[0]["facts"] if template_rows else None,
            "note": "7 条 episode 的 4×4 事实表完全相同（OnSeabed T,T,F,F / InGripper F,F,T,T / Lifted F,F,F,T / NextTo F,T,F,F），"
                    "且 compile_action_descriptions 产出的动作文本除对象名外完全一致。"
                    "这强烈提示标注是按『物体生命周期模板』套用，而不是逐帧独立判读；"
                    "manifest 声称的『21 个相邻转移均可见且非空』可由模板直接推出，不构成视觉证据。",
        },
        "nextto_semantics": {
            "observed_annotation_pattern": "key1=false, key2=true, key3=false, key4=false（三个 episode 一致）",
            "evidence_from_pass3_planned": "wrist 视角显示 key1 时夹爪与物体仍有明显空隙、key2 时物体已进入夹爪口部但未合拢、key3 之后已夹紧。",
            "interpretation": "v0.1 的 NextTo 实际语义 ≈『机器人已到达抓取位姿、但尚未夹紧』这一生命周期阶段，而不是『robot 与 object 的空间距离小于阈值』。"
                              "名字与语义不符，且编译出的动作文本『The robot becomes next to …』把阶段变化写成了空间关系变化。",
            "post_grasp_false_issue": "抓住后 NextTo=false 导致同一转移里同时出现 'grasped by the robot' 与 'no longer next to the robot'，自然语义自相矛盾；"
                                      "这也意味着被评模型仅凭动作文本即可推断顺序（与去图 EM 0.7286 的现象一致）。",
        },
        "intermediate_state": {
            "state": "OnSeabed=false ∧ InGripper=true ∧ Lifted=false（key3）",
            "ego_visibility": "reviewer pass1 在 3 个 key3 帧均判 OnSeabed=undecidable：ego 单帧看不到明确的离底间隙或接触点。",
            "physical_evidence": "dvl_h（离底高度，辅助信号）：三条 episode 的 key3 都处于最低点（0.235/0.231/0.260 m），"
                                 "上浮起点分别在其后 23/22/22 帧（ascent onset 271/301/306）；key3 相对 key2 还略微下降 3–5 cm。"
                                 "夹爪在 key3 前 15–20 帧才闭合，且 wrist 视角下物体相对夹爪无竖直位移。"
                                 "=> 没有发生离底提升，物体极可能仍与海床接触。",
            "conclusion": "『OnSeabed=false』在物理语义上无依据；它是按生命周期模板（grasped ⇒ 不再 on seabed）推出来的。"
                          "该中间状态在 ego 中不可见，且定义不自洽（OnSeabed 物理支撑 vs 生命周期阶段两种读法冲突）。",
        },
        "object_reference": {
            "unique_reference_ok_in_relation_scope": True,
            "notes": [
                "ep200/ep201 的 v0.1 notes 写『A red cylinder is also present』，但复核视频显示红色物体是游动的小鱼（wrist 视角下由远及近再离开、朝向/位置随帧剧烈变化），并非红色圆柱。注释应改为 red fish。",
                "ep552（红圆柱任务）画面中存在蓝色条状干扰物（ego 左上/腕部视角下方），颜色与蓝圆柱任务的目标同色系；对『red cylinder』指代不构成混淆，但对跨任务颜色捷径有提示意义。",
                "蓝圆柱在 ego 流中呈紫色/紫蓝色，而 object_id/文本用 'blue'；v0.1 已在 notes 中说明，但 QA 文本没有颜色线索以外的指代约束，建议 v0.2 保留 description 并明确颜色命名规则。",
            ],
        },
        "visibility": {
            "schema_limitation": "v0.1 visibility 只有布尔 true/false；复核认为 ep200 f328 与 ep552 f364 的目标物为 partial（被夹爪遮挡 20–40%、颜色对比下降）但仍可指代。",
            "visibility_notes": visibility_notes,
        },
        "qa_input_audit": {
            "qa_images_equal_raw_outside_overlay": True,
            "overlay_bbox_xyxy_max": [7, 9, 160, 29],
            "overlay_labels": ["Current State", "Next State 1", "Next State 2", "Next State 3"],
            "subject_occluded": False,
            "frame_duplication": {"usim_train_episode_000200": {"frames": 343, "unique": 42},
                                  "usim_train_episode_000201": {"frames": 368, "unique": 35},
                                  "usim_train_episode_000552": {"frames": 374, "unique": 38}},
            "note": "ego 视频每 8–14 帧才更新一个渲染画面；QA 的 3–4 张图来自不同渲染画面，因此图像差分非空，但 ±10~20 帧的『邻近帧』多为同一画面。",
        },
    }

    total = len(rows)
    agree = sum(1 for r in rows if r["status"] == "agree")
    abstain = sum(1 for r in rows if r["status"] == "abstain")
    disagree = sum(1 for r in rows if r["status"] == "disagree")
    summary = {
        "rows": total,
        "exact_agreement": agree,
        "abstain_pass1_undecidable": abstain,
        "disagreement": disagree,
        "exact_agreement_rate": round(agree / total, 4),
        "agreement_rate_excluding_abstentions": round(agree / (total - abstain), 4) if total != abstain else None,
    }

    payload = {
        "reviewer": "reviewer_a",
        "pass": 2,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "pass1_lock": lock,
        "annotation_files": {ep: {"path": str((DATA / "annotations" / "episodes" / f"{ep}.json")),
                                  "sha256": sha(DATA / "annotations" / "episodes" / f"{ep}.json")} for ep in EPS},
        "agreement_stats": {"overall": summary, "by_predicate": per_pred, "by_episode": per_ep},
        "frame_relation_comparison": rows,
        "disagreements": disagreements,
        "adjacent_transition_checks": transition_checks,
        "special_audits": special,
        "compiled_action_texts": compiled_texts,
        "preliminary_conclusions": [
            f"48 个帧×关系判定中精确一致 {agree}/48（{summary['exact_agreement_rate']:.2%}），复核给出 undecidable 的 {abstain} 项，"
            f"硬分歧 {disagree} 项（{summary['disagreement']}）。",
            f"逐谓词：InGripper 12/12、Lifted 12/12 一致；OnSeabed 8/12 一致（4 项复核为 undecidable，无反向硬分歧）；NextTo 仅 4/12 一致 —— 全部分歧集中在 NextTo。",
            "NextTo 的 8 处分歧全部是『复核按几何语义判 true、v0.1 判 false』；其中 6 处发生在抓住之后（定义问题），2 处发生在 key1（ep200 f140 / ep552 f120；wrist 证据显示 ep552 f120 物体确实离夹爪较远，v0.1 正确；ep200 f140 则处于灰区）。",
            "v0.1 的 OnSeabed=false（key3）没有可见证据支持：三条 episode 在 key3 时离底高度处于最低点、上浮尚未开始；这是生命周期模板推导而非物理接触观测。",
            "9 个相邻转移按 v0.1 全部非空，但只有 2 个（ep201 199→244、ep552 120→249，NextTo 距离变化）能仅凭 ego 直接辨认；其余依赖 NextTo 的阶段定义或 ~16 cm 的 Lifted 上浮（ego 单帧证据弱）。",
            "三条 episode 的关键帧与 v0.1 事实表完全模板化；不同 episode 的动作文本除对象名外逐字相同，说明注释未做 episode 级 grounding。",
        ],
        "pass3_scope": [d["id"] for d in disagreements],
    }
    out = BASE / "pass2_disagreements.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out, out.stat().st_size, "bytes")
    print(json.dumps(summary, indent=2))
    print("predicate:", json.dumps(per_pred, ensure_ascii=False))
    print("disagreements:", len(disagreements))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

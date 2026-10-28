# -*- coding: utf-8 -*-
"""轨迹融合器：从 tasks 里的多条轨迹按圈随机拼出一条新轨迹。

为什么要「对齐后再拼」：每条源轨迹的起跑相位是随机的，直接首尾相接会瞬间
跳到跑道另一头（几百米）。所以先把每个点换算成跑道参数 s（0~2L+2πr），
只取「从 s≈0 开始的完整圈」，这样所有圈首尾都在同一个物理位置，拼接自然连续。

用法：
  python tools/fuse_track.py                         # 融合一条，输出到 tasks/tasklist_fused.json
  python tools/fuse_track.py --count 3                # 一次生成 3 条（_0/_1/_2）
  python tools/fuse_track.py --distance 2300          # 指定里程
  python tools/fuse_track.py --inplace                # 覆盖写回 tasklist_suzhou_0..4
"""
import argparse
import json
import math
import os
import random

M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(0.0))   # set_center() 会按实际纬度重算
LON_C, LAT_C = 0.0, 0.0        # 首次 load_laps 时按源轨迹自动定位（工具不内置任何校区坐标）


def set_center(lon, lat):
    """把局部投影原点挪到轨迹所在纬度；米/度随纬度重算。"""
    global LON_C, LAT_C, M_PER_DEG_LON
    LON_C, LAT_C = float(lon), float(lat)
    M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT_C))
STRAIGHT = 84.0
HALF = STRAIGHT / 2.0
R_REF = 41.0
LAP_LEN = 2 * STRAIGHT + 2 * math.pi * R_REF


def track_s(x, y):
    """把跑道上的 (x, y) 换算成沿跑道的弧长参数 s（米，0 ~ LAP_LEN）。"""
    ay = abs(y)
    if ay <= HALF:                       # 直道段
        if x < 0:
            return y + HALF              # 左直道：南(0) → 北(84)
        # 右直道：从北弯道终点 84+πr 起，往南走
        return STRAIGHT + math.pi * R_REF + (HALF - y)
    dy = ay - HALF
    ang = math.atan2(dy, x)              # 相对弯道圆心
    if y > 0:                            # 北弯道：西(π) → 北(π/2) → 东(0)
        return STRAIGHT + (math.pi - ang) * R_REF
    return 2 * STRAIGHT + math.pi * R_REF + ang * R_REF   # 南弯道：东(0) → 南(π/2) → 西(π)


def load_laps(path, min_span_m=350.0):
    """读一条轨迹，按「s=0 起步的完整圈」切分成多个圈（每圈是一组点）。

    min_span_m：只保留跨度够一圈的圈。半圈（起跑/收尾那段）位置对不上，
    拼进去会在接缝处瞬移几百米，所以丢弃。
    """
    try:
        d = json.load(open(path, encoding="utf-8"))["data"]
    except Exception:
        return []
    pts = d.get("pointsList") or []
    if pts and (LON_C, LAT_C) == (0.0, 0.0):
        set_center(*[sum(float(p["point"].split(",")[i]) for p in pts) / len(pts)
                     for i in (0, 1)])
    laps = []
    cur = []
    prev_u = None
    for p in pts:
        lon, lat = [float(v) for v in p["point"].split(",")]
        x = (lon - LON_C) * M_PER_DEG_LON
        y = (lat - LAT_C) * M_PER_DEG_LAT
        u = (track_s(x, y) % LAP_LEN) / LAP_LEN
        if prev_u is not None and u < prev_u - 0.5:     # 回绕 = 新的一圈开始
            if len(cur) >= 8:
                laps.append(cur)
            cur = []
        cur.append(p)
        prev_u = u
    if len(cur) >= 8:
        laps.append(cur)

    good = []
    for lap in laps:
        span = float(lap[-1]["runMileage"]) - float(lap[0]["runMileage"])
        # 只要「正好一圈」的：太小是半圈，太大是切分漏了回绕（双圈），
        # 两种拼进去都会在接缝处瞬移几十上百米
        if min_span_m <= span <= min_span_m + 150:
            good.append(lap)
    return good


def fuse(sources, target_m, rng, min_t=900.0, max_m=2550.0):
    laps = []
    for f in sources:
        laps.extend(load_laps(f))
    if not laps:
        raise SystemExit("源轨迹里没有可用的完整圈")

    out = []
    acc_m = 0.0
    acc_t = 0
    last_acc = -1.0
    while acc_m < target_m or acc_t < min_t:
        # 选接缝最小的圈：先随机试若干次，要求接缝 ≤ 20 m；都不行就取最近的
        if out:
            tail = out[-1]["point"].split(",")
            tx, ty = float(tail[0]), float(tail[1])

            def gap(lap):
                head = lap[0]["point"].split(",")
                return math.hypot((float(head[0]) - tx) * M_PER_DEG_LON,
                                  (float(head[1]) - ty) * M_PER_DEG_LAT)

            lap = None
            for _ in range(60):
                cand = rng.choice(laps)
                if gap(cand) <= 20.0:
                    lap = cand
                    break
            if lap is None:
                lap = min(laps, key=gap)
        else:
            lap = rng.choice(laps)

        base_m = float(lap[0]["runMileage"])
        base_t = int(lap[0]["runTime"])
        for p in lap:
            m = acc_m + (float(p["runMileage"]) - base_m)
            if m > max_m:
                break
            t = acc_t + (int(p["runTime"]) - base_t)
            q = dict(p)
            q["_m"] = m
            q["_t"] = t
            out.append(q)

        if not out:
            break
        acc_m = out[-1]["_m"]
        acc_t = out[-1]["_t"]
        if acc_m <= last_acc + 1e-6:      # 里程没推进就收尾
            break
        last_acc = acc_m
        if acc_m >= max_m:                # 已到上限
            break
        if len(out) > 20000:              # 保险
            break
    return out, acc_m, acc_t


def finalize(out, total_m, total_t, stride_m=0.85):
    """重算 runMileage / runTime / runStep。

    步幅取 0.85 m（与生成器那条轨迹的平均步幅接近），否则步频会偏低。
    """
    steps = 0.0
    fixed = []
    prev_lonlat = None
    for q in out:
        lon, lat = [float(v) for v in q["point"].split(",")]
        if prev_lonlat is not None:
            seg = math.hypot((lon - prev_lonlat[0]) * M_PER_DEG_LON,
                             (lat - prev_lonlat[1]) * M_PER_DEG_LAT)
            steps += seg / stride_m
        q["runMileage"] = f"{q['_m']:.13f}"
        q["runTime"] = str(int(q["_t"]))
        q["runStep"] = str(int(round(steps)))
        q.pop("_m", None)
        q.pop("_t", None)
        prev_lonlat = (lon, lat)
        fixed.append(q)
    return fixed


def write_one(out, path, cadence=170):
    total_m = float(out[-1]["runMileage"])
    total_t = int(out[-1]["runTime"])
    pace = (total_t / 60.0) / (total_m / 1000.0) if total_m else 0
    steps = int(out[-1]["runStep"])
    data = {
        "msg": "获取成功",
        "code": 200,
        "data": {
            "recordMileage": round(total_m / 1000.0, 2),
            "recodePace": round(pace, 2),
            "recodeCadence": int(round(steps / total_t * 60)) if total_t else cadence,
            "recodeDislikes": 2,
            "duration": total_t,
            "pointsList": out,
            "schoolId": 201,
            "manageList": [],
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data["data"]


def main():
    ap = argparse.ArgumentParser(description="按圈随机融合多条轨迹")
    ap.add_argument("--source", default=None, help="源轨迹目录（默认 tasks）")
    ap.add_argument("--count", type=int, default=1, help="生成几条")
    ap.add_argument("--distance", type=float, default=0, help="目标里程 m（0=随机 2000~2550）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--inplace", action="store_true", help="覆盖写回 tasklist_suzhou_*.json")
    a = ap.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = a.source or os.path.join(base, "tasks")
    sources = sorted(os.path.join(src_dir, f) for f in os.listdir(src_dir)
                     if f.endswith(".json") and "fused" not in f)
    if len(sources) < 2:
        raise SystemExit("至少要有 2 条源轨迹才能融合")

    for i in range(a.count):
        data_meta = None
        path = None
        # 随机目标里程/时长 → 拼 → 校验合规，不合规换种子重试
        for attempt in range(40):
            seed = (a.seed + i * 7919 + attempt * 104729) if a.seed is not None else None
            rng = random.Random(seed)
            target_m = a.distance or rng.uniform(2000, 2550)
            target_t = rng.uniform(900, 1440)
            pace_guess = (target_t / 60.0) / (target_m / 1000.0)
            if a.distance and not (3.0 <= pace_guess <= 11.6):
                continue
            if not a.distance and not (3.0 <= pace_guess <= 11.6):
                continue
            # 主控里程（按时长兜底会一路拼到上限），拼完再校验时长
            out, total_m, total_t = fuse(sources, target_m, rng,
                                         min_t=0.0, max_m=target_m)
            if not out:
                continue
            out2 = finalize(out, total_m, total_t)
            km = float(out2[-1]["runMileage"]) / 1000.0
            dur = int(out2[-1]["runTime"])
            if not (2.0 <= km <= 2.55 and 900 <= dur <= 1440):
                continue
            # 再接缝校验：相邻点超过 25 m 说明拼接错位，重来
            worst = 0.0
            prev = None
            for q in out2:
                lon, lat = [float(v) for v in q["point"].split(",")]
                if prev is not None:
                    seg = math.hypot((lon - prev[0]) * M_PER_DEG_LON,
                                     (lat - prev[1]) * M_PER_DEG_LAT)
                    worst = max(worst, seg)
                prev = (lon, lat)
            if worst > 25.0:
                continue
            data_meta = out2
            break
        if data_meta is None:
            print(f"[!] 第 {i} 条没拼出合规组合，跳过")
            continue

        if a.inplace:
            path = os.path.join(src_dir, f"tasklist_suzhou_{i}.json")
        elif a.count == 1:
            path = os.path.join(src_dir, "tasklist_fused.json")
        else:
            path = os.path.join(src_dir, f"tasklist_fused_{i}.json")
        meta = write_one(data_meta, path)
        print(f"{os.path.basename(path):26s} {len(data_meta):4d} 点  "
              f"{meta['recordMileage']:5.2f} km  {meta['duration']:5d} s  "
              f"pace {meta['recodePace']:.2f}  cadence {meta['recodeCadence']}")
    print(f"\n源轨迹 {len(sources)} 条 → 圈池融合完成")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""从自拍照生成云运动人脸标注 JSON（纯本地，照片不上传）。

用 APK 自带的人像检测模型（retinaface_mv1_0.25.onnx）自动找脸，输出脚本要的
box + 5 个关键点 + 置信度 + 照片 SHA256，直接喂给：

    python main.py --face-photo 自拍.jpg --face-detection 标注.json

用法：
  python tools/detect_face.py 自拍.jpg
  python tools/detect_face.py 自拍.jpg -o 标注.json
  python tools/detect_face.py 自拍.jpg --multi      # 有多张脸时列出全部

注意：本工具只负责"找脸 + 标坐标"，不判断活体、不比对身份。
服务端是否要求动作/活体、是否认静态照片，本工具无法保证。
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageOps

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CANDIDATES = [
    os.path.join(BASE, "models", "retinaface_mv1_0.25.onnx"),
    r"D:\文档\deepseek-harness\default-workspace\_play\apk\assets\retinaface_mv1_0.25.onnx",
]
INPUT_SIZE = 640
MEAN_BGR = np.array([104.0, 117.0, 123.0], dtype=np.float32)


def find_model():
    for p in MODEL_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def build_anchors(size=INPUT_SIZE):
    """RetinaFace 的 16800 个先验框。"""
    steps = [8, 16, 32]
    min_sizes = [[16, 32], [64, 128], [256, 512]]
    out = []
    for stride, mins in zip(steps, min_sizes):
        fw = fh = size // stride
        for i in range(fh):
            for j in range(fw):
                for ms in mins:
                    cx = (j + 0.5) * stride
                    cy = (i + 0.5) * stride
                    out.append([cx, cy, ms, ms])
    return np.asarray(out, dtype=np.float32)


def decode(loc, conf, landms, anchors):
    var = (0.1, 0.2)
    boxes = np.hstack((
        anchors[:, :2] + loc[:, :2] * var[0] * anchors[:, 2:],
        anchors[:, 2:] * np.exp(loc[:, 2:] * var[1]),
    ))
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 2:] += boxes[:, :2]

    scores = conf[:, 1]
    lm = np.zeros((landms.shape[0], 10), dtype=np.float32)
    for i in range(5):
        lm[:, i * 2] = anchors[:, 0] + landms[:, i * 2] * var[0] * anchors[:, 2]
        lm[:, i * 2 + 1] = anchors[:, 1] + landms[:, i * 2 + 1] * var[0] * anchors[:, 2]
    return boxes, scores, lm


def nms(boxes, scores, iou_thr=0.4):
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_o = (boxes[order[1:], 2] - boxes[order[1:], 0]) * \
                 (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / (area_i + area_o - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


def letterbox(img, size=INPUT_SIZE):
    """等比缩放到 size×size，居中填充。返回 (图, 缩放比, 左填充, 上填充)。"""
    w, h = img.size
    scale = min(size / w, size / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    ox, oy = (size - nw) // 2, (size - nh) // 2
    canvas.paste(resized, (ox, oy))
    return canvas, scale, ox, oy


def detect(img_path, sess=None):
    from onnxruntime import InferenceSession
    model = find_model()
    if not model:
        raise SystemExit("找不到 retinaface_mv1_0.25.onnx（放在 models/ 或 _play/apk/assets/）")
    if sess is None:
        sess = InferenceSession(model, providers=["CPUExecutionProvider"])

    raw = Image.open(img_path)
    raw = ImageOps.exif_transpose(raw).convert("RGB")     # 按 EXIF 摆正
    W, H = raw.size
    canvas, scale, ox, oy = letterbox(raw)

    # RetinaFace 传统预处理：BGR、减均值、不缩放
    arr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1]   # RGB→BGR
    arr -= MEAN_BGR
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]

    loc, conf, landms = sess.run(None, {"input": arr})
    boxes, scores, lms = decode(loc[0], conf[0], landms[0], build_anchors())

    mask = scores > 0.5
    boxes, scores, lms = boxes[mask], scores[mask], lms[mask]
    if len(boxes) == 0:
        return raw, []

    keep = nms(boxes, scores)
    out = []
    for idx in keep:
        b = (boxes[idx] - np.array([ox, oy, ox, oy])) / scale
        b = np.clip(b, [0, 0, 0, 0], [W, H, W, H])
        pts = []
        for i in range(5):
            px = (lms[idx, i * 2] - ox) / scale
            py = (lms[idx, i * 2 + 1] - oy) / scale
            pts.append([round(float(np.clip(px, 0, W)), 2),
                        round(float(np.clip(py, 0, H)), 2)])
        out.append({
            "box": [round(float(v), 2) for v in b],
            "points": pts,
            "score": round(float(scores[idx]), 4),
            "area_ratio": round(float((b[2] - b[0]) * (b[3] - b[1]) / (W * H)), 4),
        })
    return raw, out


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="自拍照 → 云运动人脸标注 JSON")
    ap.add_argument("photo", help="照片路径（正面、整帧、人脸别太小）")
    ap.add_argument("-o", "--out", default=None, help="输出 JSON 路径")
    ap.add_argument("--multi", action="store_true", help="列出所有检测到的人脸")
    ap.add_argument("--min-score", type=float, default=0.5)
    a = ap.parse_args()

    if not os.path.exists(a.photo):
        raise SystemExit(f"照片不存在：{a.photo}")

    img, faces = detect(a.photo)
    if not faces:
        print("[!] 没检测到人脸。换一张：正面、光线足、脸占画面 1/3 以上、别戴墨镜口罩。")
        return 2

    faces = [f for f in faces if f["score"] >= a.min_score] or faces
    faces.sort(key=lambda f: f["score"], reverse=True)
    best = faces[0]

    print(f"照片尺寸：{img.size[0]}×{img.size[1]}")
    print(f"检测到 {len(faces)} 张脸：")
    for i, f in enumerate(faces[:5] if a.multi else faces[:1], 1):
        x1, y1, x2, y2 = f["box"]
        print(f"  [{i}] 置信度 {f['score']:.3f}  框 ({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f})  "
              f"占画面 {f['area_ratio']*100:.1f}%  5点 {f['points'][0]}…")
    if len(faces) > 1 and not a.multi:
        print("  （还有别的人脸，默认取置信度最高的；加 --multi 可全部列出）")

    if best["area_ratio"] < 0.05:
        print("[提醒] 人脸占比偏小（<5%），App 的取景门可能判不合格，建议重拍近一点。")

    ann = {
        "box": best["box"],
        "points": best["points"],
        "score": best["score"],
        "space": "image",
        "source_sha256": sha256_of(a.photo),
        "bind_apply": {"after_exif": True, "mirrored": False},
    }
    out = a.out or os.path.splitext(a.photo)[0] + ".face.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(ann, f, ensure_ascii=False, indent=1)
    print(f"\n标注已写入：{out}")
    print(f"照片 SHA256：{ann['source_sha256']}")
    print("\n用法：")
    print(f'  .venv\\Scripts\\python.exe main.py --face-photo "{a.photo}" '
          f'--face-detection "{out}"')
    print("\n提醒：本工具只标坐标，不做活体判断。服务端若要求动作验证或拒绝静态照片，仍会失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

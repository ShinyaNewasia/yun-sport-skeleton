# tasks/ —— 轨迹表目录（空壳，需自己放）

脚本的「打表模式」会从这个目录随机挑一条 `tasklist_*.json` 上传。
**仓库里一条都不带**：轨迹点坐标本身就等价于「你在哪个学校的哪块场地跑」，
属于校园数据。

## 自己准备一条

两条路：

1. **抓自己 App 的一次真实跑步记录**（推荐，最稳）
   用 `devinfo.py` / 抓包拿到 `run/splitPointCheating` 或记录详情里的 `pointsList`，
   按下面的结构存成 `tasks/tasklist_0.json`。
2. **用 `tools/generate_route.py` 现场合成**
   需要先有一条源轨迹 + 一份 `examples/routes/*.json` 配置（含 `source_json`）。

## 文件结构

```json
{
  "code": 200,
  "data": {
    "recordMileage": 2.10,          // 公里
    "duration": 1050,               // 秒
    "recodePace": 8.33,             // min/km
    "recodeCadence": 160,           // 步/分钟
    "recodeDislikes": 0,            // 打表模式下会被脚本按实际踩到的卡点数覆盖
    "pointsList": [
      {"point": "lon,lat", "runMileage": 0.0, "runTime": 0, "runStep": 0,
       "speed": "5.50", "isFence": "Y", "runStatus": "1"}
    ],
    "manageList": []
  }
}
```

约定：
- `runTime` / `runMileage` / `runStep` 必须**单调不减**
- `runMileage` 是米，且点距累加要跟它自洽（脚本会校验，不齐会报错）
- `speed` 是瞬时配速 min/km，上传时脚本会按相邻点重算并夹在 1~900
- 跑完后 `finish` 的 `recodeDislikes` 由脚本按「踩到的卡点数」现算，不看这里的值

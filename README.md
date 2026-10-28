# yun-sport-skeleton

「云运动」类校园跑步 App 的自动化脚本 **骨架版**。

只保留代码与文档：**不含任何学校数据、账号数据、轨迹数据、运行日志**。
学校接口地址、登录态、轨迹表全部要在本地自己填。

> 用途是读懂这套协议的请求链路、在自己环境里做实验。
> 它现在**开箱跑不起来**，这是有意的——见 §5「保留了什么 / 剔除了什么」。

---

## 1. 请求链路

```
getHomeRunInfo            取任务（里程区间 / 配速区间 / 步频区间 / 卡点 / 跑步区域）
   ↓
run/start                 建记录，拿 recordId（顺带 faceTime、passPointNum、canSport）
   ↓
run/splitPointCheating    分批上传轨迹点（body 前置 gzip，再走 SM4 信封）
   ↓
run/isStandard            结束前的状态检查：回 4 条明细（里程 / 步频 / 配速 / 踩点数）
   ↓
run/splitPointCheating    尾批（未满一批的点）
   ↓
run/finish                交卷：里程、配速、步频、踩点数、manageList…
```

离线可验证的部分（不联网、不建 socket）：

```bash
# 仓库里的 tasks/ 是空的，用自带的合成 fixture 试跑整条链路（不发真请求）
python main.py --dry-run --dry-home dry_run_home.json -t tests/fixtures/tasks

pytest                        # 170 passed / 3 failed / 1 skipped，见 §6
```

## 2. 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 1) 填配置：学校接口、学校 ID、登录接口名、App 版本（只改这 5 项）
notepad config.ini
# 2) 放轨迹表（自己抓/自己造，格式见 tasks/README.md）
#    tasks/tasklist_0.json
# 3) 打表跑
python main.py -a -t tasks
```

想看交互式菜单（会问轨迹目录、要不要漂移）：`python main.py`。

> **换学校只改 5 项**：`school_host` / `school_id` / `school_name` / `school_login_url` / `app_edition`。
> 协议密钥是 App 级参数、全校通用，不用动（见 §5）。

## 3. 目录结构

| 路径 | 作用 |
|---|---|
| `main.py` | 主流程：建任务 → 打表上传 → 状态检查 → finish；`--dry-run` 离线自检 |
| `yun_http.py` | 传输层：11 个请求头、SM4 信封、gzip、Cookie、业务 code 判定 |
| `yun_face.py` | 人脸窗口状态机（需要你自己的照片 + 标注，仓库不带检测模型） |
| `yun_route.py` | 轨迹几何：变形、重采样、围栏校验、配速派生 |
| `run_auto.py` | 一键入口（`一键跑-*.bat` 调它） |
| `accounts.py` / `grab_device.py` | 多账号切换 / 从 adb 抓设备指纹 |
| `devinfo.py` | 读 App 自己打到 logcat 的明文请求响应（不抓包、不解密 HTTPS） |
| `live_probe.py` | 只读准入探测（`run/getRlStatus`，不建记录） |
| `web.py` | 轨迹预览小页面 |
| `history.py` | 拉历史记录并导出 |
| `tools/` | 登录、人脸标注、轨迹融合、配速改写、离线 GeoJSON 生成 |
| `tasks/` | 轨迹表目录（**空的**，要自己放） |
| `examples/routes/` | 轨迹变形/合成配置示例 |
| `docs/` | 架构、轨迹生成、用法说明 |
| `tests/` | 离线回归（假传输，不建 socket） |

## 4. 踩点数这一栏是怎么判的（实测定论）

`run/isStandard` 的「踩点数至少 N 个点」读的是 **finish 体里的 `recodeDislikes`**，
不是 `manageList`，也不是轨迹离卡点多近。

实测（同一条记录、同一批已上传的点、`manageList` 都是 6 项，只改这一个字段）：

| `recodeDislikes` | 服务端回 |
|---|---|
| `2`（任务要求 ≥ 3） | `[N] 踩点数至少3个点` → isStandard=N |
| `5` | `[Y] 踩点数至少3个点` → isStandard=Y，finish 回「成绩合格」 |

所以 `main.finish_by_points_map()` 现在按 **轨迹真正踩到的卡点数** 现算，并夹在任务下发的
`raDislikes` 以内：

```python
likes = min(len(build_manage_list(pointsList, task_points, 20.0)), raDislikes)
```

`manageList` 也用同一份「踩到的」结果生成。轨迹是否「压在卡点上」不影响这一栏的判定，
但压上去更像真跑，也留了点余量。

## 5. 保留了什么 / 剔除了什么

**保留**：全部代码、离线测试、文档、协议字段对齐的证据与注释。

**剔除**（`.gitignore` 里也拦着）：

| 类别 | 举例 |
|---|---|
| 学校数据 | `school_host` / `school_id` / `school_name` / 登录接口名 / 跑步区域 ID / 卡点坐标 |
| 轨迹数据 | `tasks/*.json`（轨迹点坐标等价于「你在哪块场地跑」）、各种 `tasks_*` 目录 |
| 账号数据 | `token` / `device_id` / 学号密码、`accounts.json` |
| 使用日志 | `run_log*.txt`、`applog*.txt`、截图、`ui*.xml`、轨迹叠加图 |
| 定向生成器 | 把某校田径场中心/跑道尺寸写死的几个脚本（自己按 `yun_route.py` 写） |
| 第三方大件 | `decrypt*.jar`（APK 解密）、人脸检测 `.onnx` 模型 |

`tools/proxy.py` 里的抓包目标 host 也改成从 `config.ini` 的 `school_host` 读了，不再写死。

**协议常量**（SM2 公钥、SM4 密钥、`md5key`）：App 级参数，**所有学校通用**，所以保留——
换学校只改 §2 那 5 项就够了，不用重新抓密钥。这些值在上游公开仓库里本来就有，不构成新的披露；
要更保守可以清空（`config.ini` 里那 5 行 + `main.py` 顶部两行），代价是加密相关的离线用例会失败。

## 6. 测试现状

```
170 passed, 3 failed, 1 skipped        # 收集到 173 个用例
```

`test_yun_route.py` 整个模块被 skip（它要一份真实轨迹表 `tasks/tasklist_0.json`，
仓库不带；模块里有 53 个用例，补上轨迹表后自动参与收集）。
父项目里同一套测试是 226 个用例 / 223 passed / 3 failed。

三个失败是**改动前就存在**、与本仓库逻辑无关的用例，为了不掩盖问题没有改：

1. `test_gzip_apk_header_bytes_match_jdk` —— Python 3.14 的 `gzip.compress` 默认头字节变了
2. `test_split_body_matches_uppointsmodel` —— 断言点项里还有 `isMock`，实际字段已是 `isRunMock`
3. `test_finish_body_p1_order_and_types` —— 断言 finish 体键序，实际多了一个 `extra` 键

## 7. 免责声明

- 这是**第三方脚本**，不是官方客户端。用它等于绕过学校的跑步核验机制，
  后果（成绩作废、纪律处理等）由使用者自负。
- 仓库不含任何人的学校/账号/轨迹数据，也不会替你伪造人脸材料。
- 代码基线参考上游公开项目 `yunForNewVersion`（develop 分支）整理而来，仅供学习交流。

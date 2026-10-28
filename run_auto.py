# -*- coding: utf-8 -*-
"""一键入口：显示当前账户 → 带倒计时运行 main.py。

跑步过程中会实时显示「已用 / 剩余 / 进度条」，不用盯着黑窗口猜还剩多久。
"""
import configparser
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)


def current_account_line():
    """读 accounts.json + config.ini，拼一句「姓名 学号 设备」；只本地显示。"""
    conf = configparser.ConfigParser()
    conf.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
    user = (conf.get("Login", "username", fallback="") or "").strip()
    name, cls, dev = "", "", ""
    acc_file = os.path.join(BASE, "accounts.json")
    if os.path.exists(acc_file):
        try:
            d = json.load(open(acc_file, encoding="utf-8"))
            for a in d.get("accounts", []):
                if a.get("username") == user:
                    name = a.get("name") or ""
                    cls = a.get("class_name") or ""
                    dev = a.get("device_name") or ""
                    break
        except Exception:
            pass
    parts = [name or "(未命名)", f"学号 {user or '(空)'}"]
    if cls:
        parts.append(cls)
    if dev:
        parts.append(dev)
    return "  ".join(parts)


def _fmt(sec):
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _bar(pct, width=26):
    pct = min(max(pct, 0.0), 1.0)
    n = int(pct * width)
    return "[" + "=" * n + (">" if n < width else "") + " " * max(0, width - n - 1) + "]"


def read_total_seconds(args_list):
    """从 -t 目录/文件里的 tasklist 估总时长（多条取平均）。"""
    path = None
    for flag in ("-t", "--task_path"):
        if flag in args_list:
            i = args_list.index(flag)
            if i + 1 < len(args_list):
                path = args_list[i + 1]
            break
    if not path:
        return 0.0
    p = path if os.path.isabs(path) else os.path.join(BASE, path)
    files = []
    if os.path.isdir(p):
        files = [os.path.join(p, f) for f in os.listdir(p) if f.endswith(".json")]
    elif os.path.isfile(p):
        files = [p]
    durs = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8")).get("data") or {}
            durs.append(float(d.get("duration") or 0))
        except Exception:
            pass
    durs = [d for d in durs if d > 0]
    return sum(durs) / len(durs) if durs else 0.0


def make_cd_sleep(total, state):
    """造一个「边等边刷倒计时」的 sleep 函数。"""

    def render(done):
        # 纯显示层：任何异常都吞掉，绝不影响脚本本身的等待与上传
        try:
            if total > 0:
                pct = done / total
                sys.stdout.write("\r  已用 %s   剩余 %s   %s %3d%%   "
                                 % (_fmt(done), _fmt(total - done), _bar(pct), int(pct * 100)))
            else:
                sys.stdout.write("\r  已用 %s   " % _fmt(done))
            sys.stdout.flush()
        except Exception:
            pass

    def cd_sleep(seconds):
        seconds = max(0.0, float(seconds))
        end = time.time() + seconds
        while True:
            left = end - time.time()
            if left <= 0:
                break
            render(state["elapsed"] + (seconds - left))
            time.sleep(min(0.4, left))
        state["elapsed"] += seconds

    return cd_sleep


def run_with_countdown(args_list):
    """在当前进程里跑 main.py，并给 YunClient.sleep 挂上倒计时显示。"""
    import yun_http
    import main as M

    total = read_total_seconds(args_list)
    state = {"elapsed": 0.0}
    cd_sleep = make_cd_sleep(total, state)

    orig_init = yun_http.YunClient.__init__

    def patched_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.sleep = cd_sleep

    yun_http.YunClient.__init__ = patched_init
    old_argv = sys.argv[:]
    sys.argv = ["main.py"] + args_list
    try:
        M.main()
    finally:
        yun_http.YunClient.__init__ = orig_init
        sys.argv = old_argv
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()
        if state["elapsed"] > 0:
            print(f"  本次模拟用时 {_fmt(state['elapsed'])}"
                  f"（任务预估 {_fmt(total) if total else '未知'}）")
    return state["elapsed"]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "table"

    # 自检：模拟一段倒计时，验证显示效果（不联网、不发请求）
    if mode in ("selftest", "--selftest"):
        total = 12.0
        state = {"elapsed": 0.0}
        f = make_cd_sleep(total, state)
        print("倒计时自检：下面模拟 12 秒的跑步进度")
        for _ in range(3):
            f(4.0)
        sys.stdout.write("\r" + " " * 78 + "\r")
        print(f"自检结束，累计 {_fmt(state['elapsed'])}（应为 00:12）")
        return 0

    conf = configparser.ConfigParser()
    conf.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
    token = (conf.get("User", "token", fallback="") or "").strip()

    print("=" * 60)
    print("  当前账户：" + current_account_line())
    print("  学校：" + (conf.get("Yun", "school_name", fallback="") or "（未填 school_name）"))
    print("=" * 60)

    if not token:
        print("[!] 还没有登录过（config.ini 里 token 是空的）。")
        print("    第一次请先双击 start.bat 走一遍交互登录；")
        print("    要换账号：双击 账户管理.bat，或 抓取设备.bat")
        print("=" * 60)
        input("按回车关闭窗口...")
        return 1

    if mode == "route":
        print("[一键跑] 合成轨迹模式（每次形状不同，适合轮换）")
        args = ["--route-config", "examples/routes/deform_example.json"]
    else:
        print("[一键跑] 打表模式（tasks 目录里的轨迹表）")
        args = ["-a", "-t", "tasks"]

    print()
    for i in (3, 2, 1):
        sys.stdout.write(f"\r  准备开跑… {i}  ")
        sys.stdout.flush()
        time.sleep(1)
    print("\r  开跑！                ")
    print("-" * 60)

    t0 = time.time()
    rc = 0
    state_elapsed = 0.0
    try:
        state_elapsed = run_with_countdown(args) or 0.0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    except Exception as e:
        print(f"\n[异常] {type(e).__name__}: {e}")
        rc = 1
    real = time.time() - t0

    # main.py 会把「业务拒绝」吞掉后正常返回，靠"实际等待了多久"判断是否真跑过
    if rc == 0 and state_elapsed < 5:
        rc = 2

    print()
    print("=" * 60)
    print(f"[结束] 返回码 {rc}   账户：{current_account_line()}")
    print(f"       墙钟耗时 {_fmt(real)}")
    if rc == 0:
        print("       正常结束。请到云运动 APP 里确认记录是否生成/通过。")
    elif rc == 2:
        print("       没能开跑：服务端没有下发跑步任务（或业务被拒），本次没有产生记录。")
        print("       原因通常是：不在可跑时段 / 今天已完成 / 学校还没配任务。")
    else:
        print("       出错退出：把上面最后几行报错贴给开发者。")
        print("       常见原因：密码错 / 服务端业务拒绝 / 人脸核验未通过。")
    print("=" * 60)
    input("按回车关闭窗口...")
    return rc


if __name__ == "__main__":
    sys.exit(main())

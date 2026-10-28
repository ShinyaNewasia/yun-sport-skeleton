# -*- coding: utf-8 -*-
"""新手机接入时，自动抓取「设备指纹 + 该机上的云运动账户」，存进 accounts.json。

为什么需要：每台手机的 deviceId/机型/系统版本都不一样，脚本发请求时如果指纹
和真机对不上，服务端一眼就能看出不是同一台设备。这个工具把真机指纹连同账号
一起存下来，切换账户时自动带上对应设备的指纹。

用法：
  python grab_device.py                # 抓当前连接的手机
  python grab_device.py --serial ab6143a1
  python grab_device.py --list         # 只看连了哪些设备
  python grab_device.py --password 密码 # 抓不到 token 时，用密码登录补上

抓取顺序：
  1. adb 认设备 → 厂商/型号/系统版本
  2. 读 App 自己存的 .sys_device_id（这才是服务端认的 deviceId）
  3. 从 logcat 找 token（找不到就让你选：App 上登录一次，或用 --password）
  4. 用该设备指纹 + token 调 getStudentInfo，拿真实姓名/学号/班级
  5. 写进 accounts.json（已有同 deviceId 就更新，没有就新增）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(BASE, "accounts.json")
CONF_FILE = os.path.join(BASE, "config.ini")
PKG = "com.yunzhi.tiyu"

ADB_CANDIDATES = [
    os.environ.get("ADB", ""),
    r"D:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe",
    os.path.expanduser(r"~\AppData\Local\Android\Sdk\platform-tools\adb.exe"),
    "adb",
]

TOKEN_RE = re.compile(r'"token"\s*:\s*"([A-Za-z0-9\-]{20,64})"')


def find_adb():
    for c in ADB_CANDIDATES:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            p = shutil.which(c)
            if p:
                return p
    return None


def run(adb, args, timeout=20):
    try:
        r = subprocess.run([adb] + args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return f"ERR {e}", 1


def list_devices(adb):
    out, _ = run(adb, ["devices"])
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devs.append(parts[0])
    return devs


def grab_fingerprint(adb, serial):
    def prop(k):
        o, _ = run(adb, ["-s", serial, "shell", "getprop", k])
        return o.strip()

    brand = prop("ro.product.manufacturer")
    model = prop("ro.product.model")
    release = prop("ro.build.version.release")
    android_id = run(adb, ["-s", serial, "shell", "settings", "get", "secure", "android_id"])[0].strip()

    # App 自己存的 deviceId —— 服务端真正认的那个（64 位 hex）
    dev_id = ""
    for path in (f"/sdcard/Android/data/{PKG}/files/.sys_device_id",
                 f"/sdcard/Android/data/{PKG}/files/device_id"):
        out, code = run(adb, ["-s", serial, "shell", "cat", path])
        if code == 0 and out and not out.startswith("cat:"):
            cand = out.strip().splitlines()[0].strip()
            if re.fullmatch(r"[0-9a-fA-F]{32,128}", cand):
                dev_id = cand
                break

    return {
        "serial": serial,
        "brand": brand,
        "model": model,
        "device_name": f"{brand}({model})" if brand and model else model or brand,
        "sys_edition": release,
        "android_id": android_id,
        "device_id": dev_id,
    }


def _dump_ui(adb, serial):
    """把当前界面 dump 成 XML 文本。"""
    dump = "/sdcard/_dsh_ui.xml"
    local = os.path.join(BASE, "_ui_dump.xml")
    try:
        run(adb, ["-s", serial, "shell", "uiautomator", "dump", dump], timeout=30)
        run(adb, ["-s", serial, "pull", dump, local], timeout=20)
        run(adb, ["-s", serial, "shell", "rm", "-f", dump], timeout=10)
        if os.path.exists(local):
            xml = open(local, "r", encoding="utf-8", errors="replace").read()
            os.remove(local)
            return xml
    except Exception:
        pass
    return ""


def grab_username_from_ui(adb, serial):
    """从 App 界面读学号（「我的」页会显示「学号 0401260413」）。

    为什么需要：一台手机可能登着别人的账号，光看设备指纹分不出是谁。
    先 dump 当前界面；没读到就启动 App 再 dump 一次。
    """
    pat = re.compile(r"学号[：:\s]*([0-9]{6,20})")
    xml = _dump_ui(adb, serial)
    m = pat.search(xml or "")
    if m:
        return m.group(1)
    run(adb, ["-s", serial, "shell", "monkey", "-p", PKG,
              "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
    time.sleep(6)
    xml = _dump_ui(adb, serial)
    m = pat.search(xml or "")
    return m.group(1) if m else ""


def grab_token_from_logcat(adb, serial, seconds=8):
    """从 logcat 里找 token；找不到就启动 App 再找一轮。"""
    run(adb, ["-s", serial, "logcat", "-c"])
    for attempt in range(2):
        if attempt == 1:
            run(adb, ["-s", serial, "shell", "monkey", "-p", PKG,
                      "-c", "android.intent.category.LAUNCHER", "1"])
        deadline = time.time() + seconds
        while time.time() < deadline:
            out, _ = run(adb, ["-s", serial, "logcat", "-d", "-t", "2000"], timeout=25)
            m = TOKEN_RE.search(out)
            if m:
                return m.group(1)
            time.sleep(1.5)
    return ""


def fetch_profile(dev, token, password=None, username=None):
    """用该设备指纹 + (token 或 账号密码) 拿账号信息。"""
    sys.path.insert(0, BASE)
    import main as M
    import configparser

    if password and username:
        # 临时配置：设备指纹换成这台手机的，账号密码用本次给的
        c = configparser.ConfigParser()
        c.read(CONF_FILE, encoding="utf-8")
        c.set("Login", "username", username)
        c.set("Login", "password", password)
        c.set("User", "device_id", dev["device_id"])
        c.set("User", "device_name", dev["device_name"])
        c.set("User", "sys_edition", dev["sys_edition"])
        c.set("User", "sys_version", dev["sys_edition"])
        c.set("User", "token", "")
        c.set("User", "uuid", "")
        tmp = os.path.join(BASE, "_grab_tmp.ini")
        with open(tmp, "w", encoding="utf-8") as f:
            c.write(f)
        try:
            from tools.Login import Login
            res = Login.main(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not res:
            print("[!] 登录失败：学号或密码不对，也可能这台手机上登的不是这个账号。")
            print("    建议：在那台手机的云运动里看一眼「我的」页显示的学号，再用它登录。")
            return None, ""
        token = res[0]

    M.set_args(CONF_FILE)
    M.my_token = token
    M.my_device_id = dev["device_id"]
    M.my_device_name = dev["device_name"]
    M.my_sys_edition = dev["sys_edition"]
    M.my_sys_version = dev["sys_edition"]
    M._CLIENT = None
    client = M.default_client()
    try:
        r = client.post_json("/login/getStudentInfo", "", raise_on_business_code=True)
        return r.get("data") or {}, token
    except Exception as e:
        print(f"[!] 查询账号失败：{type(e).__name__}: {e}")
        return None, token


def load_store():
    if os.path.exists(ACC_FILE):
        try:
            d = json.load(open(ACC_FILE, encoding="utf-8"))
            d.setdefault("accounts", [])
            d.setdefault("current", "")
            return d
        except Exception:
            pass
    return {"accounts": [], "current": ""}


def save_store(d):
    tmp = ACC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ACC_FILE)


def main():
    ap = argparse.ArgumentParser(description="抓取新手机的设备指纹和云运动账户")
    ap.add_argument("--serial", default=None, help="adb 序列号（多设备时指定）")
    ap.add_argument("--list", action="store_true", help="只列出已连接设备")
    ap.add_argument("--password", default=None,
                    help="抓不到 token 时用密码登录；填 auto 表示用「学号后 6 位」")
    ap.add_argument("--username", default=None, help="配合 --password 用的学号")
    ap.add_argument("--no-login", action="store_true", help="不尝试抓 token，只存设备指纹")
    a = ap.parse_args()

    # 你们学校的密码规则：学号后 6 位
    if a.password == "auto":
        if not a.username:
            print("[!] --password auto 需要同时给 --username 学号")
            return 1
        a.password = a.username[-6:]
        print(f"[提示] 密码按「学号后 6 位」取：{a.password}")

    adb = find_adb()
    if not adb:
        print("[!] 找不到 adb。请把 adb 放进 PATH，或设置环境变量 ADB 指向 adb.exe")
        return 1

    devs = list_devices(adb)
    if not devs:
        print("[!] 没有检测到已连接的安卓设备（手机开 USB 调试了吗？）")
        return 1
    if a.list:
        print("已连接设备：", ", ".join(devs))
        return 0

    serial = a.serial or devs[0]
    if serial not in devs:
        print(f"[!] 设备 {serial} 不在列表里：{devs}")
        return 1
    if len(devs) > 1 and not a.serial:
        print(f"[提示] 检测到多台设备 {devs}，默认用 {serial}，可用 --serial 指定")

    print(f"[1/4] 读取设备指纹（{serial}）…")
    dev = grab_fingerprint(adb, serial)
    print(f"      厂商/型号 : {dev['device_name']}")
    print(f"      系统版本   : Android {dev['sys_edition']}")
    print(f"      android_id: {dev['android_id'] or '(读不到，可能被系统限制)'}")
    print(f"      deviceId  : {dev['device_id'] or '(读不到 App 的 .sys_device_id)'}")
    if not dev["device_id"]:
        print("[!] 没能读到 App 的 deviceId。请确认手机上装了云运动并至少启动过一次。")
        if not dev["android_id"]:
            return 1

    print(f"[2/5] 从 App 界面读学号（请让 App 停在「我的」页）…")
    ui_user = grab_username_from_ui(adb, serial)
    print("      " + (f"读到学号 {ui_user}" if ui_user else "没读到（App 不在「我的」页？可忽略）"))

    token = ""
    if not a.no_login:
        print("[3/5] 从 logcat 找 token …")
        token = grab_token_from_logcat(adb, serial)
        print("      " + ("已抓到" if token else "没抓到"))
    else:
        print("[3/5] 跳过 token 抓取")

    data = None
    if token or (a.password and a.username):
        print("[4/5] 用该设备指纹查询账号信息 …")
        data, token = fetch_profile(dev, token, a.password, a.username)
        if data:
            token = token or ""
    else:
        print("[4/5] 没有 token/密码，跳过账号查询（只存设备指纹）")
        print("      想连账号一起抓：加 --username 学号 --password 密码")

    store = load_store()
    username = (data or {}).get("userName") or ui_user or ""
    # 一台手机一条记录：优先按 serial 认（同一账号也可能有多台手机），
    # 其次按 deviceId，最后才按学号找"没绑过设备"的空条目。
    target = None
    for acc in store["accounts"]:
        if acc.get("serial") == serial:
            target = acc
            break
    if target is None:
        for acc in store["accounts"]:
            if dev["device_id"] and acc.get("device_id") == dev["device_id"]:
                target = acc
                break
    if target is None and username:
        for acc in store["accounts"]:
            if acc.get("username") == username and not acc.get("serial"):
                target = acc
                break

    if target is None:
        target = {"username": username, "name": "", "password": "", "token": "",
                  "uuid": "", "last_used": ""}
        store["accounts"].append(target)

    target.update({
        "device_id": dev["device_id"] or target.get("device_id", ""),
        "device_name": dev["device_name"],
        "sys_edition": dev["sys_edition"],
        "android_id": dev["android_id"],
        "serial": serial,
        "model": dev["model"],
        "brand": dev["brand"],
        "last_seen": time.strftime("%Y-%m-%d %H:%M"),
    })
    if data:
        target["name"] = data.get("realName") or data.get("nickName") or target.get("name", "")
        target["class_name"] = data.get("className") or target.get("class_name", "")
        target["fac_name"] = data.get("facName") or target.get("fac_name", "")
        target["school_name"] = data.get("schoolName") or target.get("school_name", "")
        if data.get("sex") is not None:
            target["sex"] = data.get("sex")
    if token:
        target["token"] = token
    if a.password:
        target["password"] = a.password

    save_store(store)

    # 如果抓的就是 config.ini 里当前那个账户，顺手把最新 token/指纹写回 config
    try:
        import configparser
        c = configparser.ConfigParser()
        c.read(CONF_FILE, encoding="utf-8")
        if username and token and c.get("Login", "username", fallback="") == username:
            c.set("User", "token", token)
            c.set("User", "device_id", dev["device_id"])
            c.set("User", "device_name", dev["device_name"])
            c.set("User", "sys_edition", dev["sys_edition"])
            with open(CONF_FILE, "w", encoding="utf-8") as f:
                c.write(f)
            print("[已同步] config.ini 的 token / 设备指纹已更新为本次抓到的值")
    except Exception as e:
        print(f"[提示] 没能写回 config.ini：{e}")

    print("[5/5] 写入 accounts.json")
    print("=" * 56)
    print(f"  学号   : {username or '(未获取到，只存了设备)'}")
    print(f"  姓名   : {target.get('name') or '(未知)'}")
    print(f"  班级   : {target.get('class_name') or '-'}")
    print(f"  设备   : {dev['device_name']}  Android {dev['sys_edition']}")
    print(f"  deviceId: {dev['device_id'][:16]}…" if dev["device_id"] else "  deviceId: -")
    print("=" * 56)
    print("提示：双击 账户管理.bat 可以看到所有设备/账户，切换时会自动带上对应指纹。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

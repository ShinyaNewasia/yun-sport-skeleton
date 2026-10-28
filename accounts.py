# -*- coding: utf-8 -*-
"""本地多账户管理（仅存本机，不上传任何东西）。

作用：手上有好几个学号要来回跑的时候，用这个切换。列表会显示
「姓名 + 学号 + 登录状态 + 上次使用时间」，切换后自动写进 config.ini。

数据文件：accounts.json（与本脚本同目录）
  - 里面是明文密码和 token。只存在你自己电脑上，别发给别人、别传网盘。
  - 想彻底清掉某个账户：菜单里删除，或直接删 accounts.json。

用法：
  python accounts.py            交互菜单（推荐）
  python accounts.py list       列出账户
  python accounts.py whoami     只显示当前账户（给 .bat 用）
  python accounts.py use 学号    切到该账户
"""

import configparser
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(BASE, "accounts.json")
CONF_FILE = os.path.join(BASE, "config.ini")

FIELDS = ["username", "name", "password", "token", "device_id",
          "device_name", "sys_edition", "uuid", "last_used"]


# ---------------- 数据读写 ----------------

def _clean(s):
    """清掉输入里可能混进来的代理项（粘贴/管道常见），否则写 UTF-8 会炸。"""
    if not isinstance(s, str):
        return s
    return s.encode("utf-8", "replace").decode("utf-8", "replace")


def load_store():
    if os.path.exists(ACC_FILE):
        try:
            with open(ACC_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("accounts", [])
            d.setdefault("current", "")
            d["accounts"] = [{k: _clean(v) if isinstance(v, str) else v
                              for k, v in a.items()} for a in d["accounts"]]
            return d
        except Exception as e:
            bad = ACC_FILE + ".broken"
            try:
                os.replace(ACC_FILE, bad)
            except Exception:
                pass
            print(f"[!] accounts.json 损坏（{e}），已改名为 accounts.json.broken 并重新开始。")
            print("    别担心：config.ini 里的账户会被自动收回来（姓名重新刷新一下即可）。")
    return {"accounts": [], "current": ""}


def save_store(d):
    """原子写：先写临时文件再替换，避免写一半把账户文件弄坏。"""
    tmp = ACC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ACC_FILE)


def read_conf():
    c = configparser.ConfigParser()
    c.read(CONF_FILE, encoding="utf-8")
    return c


def write_conf(c):
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        c.write(f)


def find(d, username):
    for a in d["accounts"]:
        if a.get("username") == username:
            return a
    return None


def now():
    return time.strftime("%Y-%m-%d %H:%M")


# ---------------- 同步 ----------------

def import_from_conf(d):
    """accounts.json 里没有、但 config.ini 里填了的账户，自动收进来。"""
    c = read_conf()
    u = (c.get("Login", "username", fallback="") or "").strip()
    if not u or find(d, u):
        return False
    d["accounts"].append({
        "username": u,
        "name": "",
        "password": (c.get("Login", "password", fallback="") or "").strip(),
        "token": (c.get("User", "token", fallback="") or "").strip(),
        "device_id": (c.get("User", "device_id", fallback="") or "").strip(),
        "device_name": (c.get("User", "device_name", fallback="") or "").strip(),
        "sys_edition": (c.get("User", "sys_edition", fallback="") or "").strip(),
        "uuid": (c.get("User", "uuid", fallback="") or "").strip(),
        "last_used": "",
    })
    d["current"] = u
    save_store(d)
    return True


def sync_from_conf(d):
    """把 config.ini 里最新的 token / 设备信息存回当前账户（登录后调用）。

    关键：按「学号 + deviceId」定位条目，否则同一账号有两台手机时，
    会把当前设备的指纹写到另一台那条上。
    """
    c = read_conf()
    u = (c.get("Login", "username", fallback="") or "").strip()
    dev = (c.get("User", "device_id", fallback="") or "").strip()
    item = None
    for a in d["accounts"]:
        if a.get("username") == u and (not dev or a.get("device_id") == dev):
            item = a
            break
    if item is None and u:
        item = find(d, u)
    if item is None:
        return
    # 设备指纹对不上的条目，只同步登录字段，绝不覆盖它的设备信息
    same_device = (not item.get("device_id")) or (item.get("device_id") == dev)
    fields = [("password", "Login"), ("token", "User"), ("uuid", "User")]
    if same_device:
        fields += [("device_id", "User"), ("device_name", "User"),
                   ("sys_edition", "User")]
    for k, sec in fields:
        v = (c.get(sec, k, fallback="") or "").strip()
        if v:
            item[k] = v
    save_store(d)


def apply_account(d, username, serial=None):
    """把某个账户写进 config.ini。同一账号有多台手机时用 serial 指定是哪台。"""
    item = None
    for a in d["accounts"]:
        if a.get("username") == username and (serial is None or a.get("serial") == serial):
            item = a
            break
    if item is None:
        print(f"[!] 没有学号为 {username}" + (f" / 设备 {serial}" if serial else "") + " 的账户")
        return False
    c = read_conf()
    if "Login" not in c:
        c.add_section("Login")
    if "User" not in c:
        c.add_section("User")
    c.set("Login", "username", item.get("username", ""))
    c.set("Login", "password", item.get("password", "") or "")
    c.set("User", "token", item.get("token", "") or "")
    c.set("User", "device_id", item.get("device_id", "") or "")
    c.set("User", "device_name", item.get("device_name", "") or "")
    c.set("User", "sys_edition", item.get("sys_edition", "") or "")
    c.set("User", "uuid", item.get("uuid", "") or "")
    write_conf(c)
    d["current"] = username
    item["last_used"] = now()
    save_store(d)
    print(f"[切换成功] 当前账户：{item.get('name') or '(未命名)'}  {username}")
    if not (item.get("token") or "").strip():
        print("        该账户还没有 token，第一次跑请用 start.bat 登录一次（会问密码）。")
    else:
        print("        已经有 token，可以直接双击一键跑；若提示登录失效，再用 start.bat 登录一次。")
    return True


def apply_from_conf(d):
    """登录成功后，把 config 里的 token 同步回账户文件。"""
    sync_from_conf(d)


def refresh_current_meta(d, quiet=False):
    """用当前账户的 token 调 /login/getStudentInfo，把真实姓名/班级补进列表。

    只在本地保存，不上传任何东西；失败（token 过期等）不影响使用。
    """
    c = read_conf()
    cur = (c.get("Login", "username", fallback="") or "").strip()
    item = find(d, cur) if cur else None
    if item is None:
        if not quiet:
            print("[!] config.ini 里没有账户，先切换/添加一个")
        return False
    if not (item.get("token") or "").strip():
        if not quiet:
            print("[!] 该账户还没有 token，先用 start.bat 登录一次再刷新姓名")
        return False
    try:
        import main as M
        M.set_args(CONF_FILE)
        client = M.default_client()
        obj = client.post_json("/login/getStudentInfo", "", raise_on_business_code=True)
    except Exception as e:
        if not quiet:
            print(f"[!] 查询姓名失败：{type(e).__name__}: {e}")
        return False
    data = obj.get("data") or {}
    name = (data.get("realName") or data.get("nickName") or "").strip()
    if name:
        item["name"] = name
    for k_src, k_dst in (("className", "class_name"), ("facName", "fac_name"),
                         ("schoolName", "school_name")):
        v = (data.get(k_src) or "").strip()
        if v:
            item[k_dst] = v
    if data.get("sex") not in (None, ""):
        item["sex"] = data.get("sex")
    save_store(d)
    if not quiet:
        extra = f"（{item.get('fac_name','')} {item.get('class_name','')}）".strip("（）")
        print(f"[已刷新] {item.get('name') or '(无姓名)'}  学号 {item.get('username')}  {extra}")
    return bool(name)


# ---------------- 展示 ----------------

def status_text(item):
    if (item.get("token") or "").strip():
        return "已登录"
    if (item.get("password") or "").strip():
        return "待登录"
    return "缺密码"


def current_device_id():
    """config.ini 里现在生效的 deviceId —— 用来区分同一账号的多台手机。"""
    c = read_conf()
    return (c.get("User", "device_id", fallback="") or "").strip()


def show_list(d):
    accounts = d["accounts"]
    cur = (d.get("current") or "").strip()
    cur_dev = current_device_id()
    print()
    print("=" * 68)
    print("  本地账户（只存这台电脑，不会上传）")
    print("=" * 68)
    if not accounts:
        print("  （还没有账户，先选 [2] 添加一个）")
    else:
        for i, a in enumerate(accounts, 1):
            same_user = a.get("username") == cur
            if cur_dev:
                same_user = same_user and (a.get("device_id") or "") == cur_dev
            mark = "★" if same_user else " "
            nm = a.get("name") or "(未命名)"
            cls = a.get("class_name") or ""
            dev = a.get("device_name") or "(未记录设备)"
            uses = a.get("last_used") or "—"
            print(f" {mark}[{i}] {a.get('username','') or '(无学号)'}  {nm:<8} {cls:<10} "
                  f"{status_text(a):<4}")
            print(f"      设备 {dev}  Android {a.get('sys_edition','?')}    上次 {uses}")
    print("=" * 68)
    return accounts


def show_current(d):
    cur = (d.get("current") or "").strip()
    cur_dev = current_device_id()
    item = None
    if cur:
        for a in d["accounts"]:
            if a.get("username") == cur and (not cur_dev or a.get("device_id") == cur_dev):
                item = a
                break
        if item is None:
            item = find(d, cur)
    if not item:
        print("当前账户：（未设置）")
        return
    extra = " ".join(x for x in (item.get("fac_name", ""), item.get("class_name", "")) if x)
    dev = item.get("device_name") or ""
    print(f"当前账户：{item.get('name') or '(未命名)'}   学号 {cur}   "
          f"{status_text(item)}" + (f"   {extra}" if extra else "")
          + (f"   设备 {dev}" if dev else ""))


# ---------------- 交互 ----------------

def ask(prompt, default=""):
    v = _clean(input(prompt).strip())
    return v if v else default


def add_account(d):
    print("\n--- 添加账户 ---")
    username = ask("学号：")
    if not username:
        print("学号不能为空")
        return
    if find(d, username):
        print("这个学号已经在列表里了")
        return
    name = ask("姓名（显示用，可留空）：")
    password = ask("密码（留空则下次运行时再输入）：")
    d["accounts"].append({
        "username": username, "name": name, "password": password,
        "token": "", "device_id": "", "device_name": "", "sys_edition": "",
        "uuid": "", "last_used": "",
    })
    save_store(d)
    print(f"[已添加] {name or '(未命名)'}  {username}")
    if ask("现在就切到该账户？[y/N] ", "n").lower() == "y":
        apply_account(d, username)


def del_account(d):
    accounts = show_list(d)
    if not accounts:
        return
    idx = ask("要删除第几个？(回车取消)：")
    if not idx.isdigit() or not (1 <= int(idx) <= len(accounts)):
        print("已取消")
        return
    item = accounts[int(idx) - 1]
    if ask(f"确认删除 {item.get('name') or ''} {item.get('username')} ？[y/N] ", "n").lower() != "y":
        print("已取消")
        return
    d["accounts"].remove(item)
    if d.get("current") == item.get("username"):
        d["current"] = d["accounts"][0]["username"] if d["accounts"] else ""
    save_store(d)
    print("[已删除]")


def rename_account(d):
    accounts = show_list(d)
    if not accounts:
        return
    idx = ask("要改第几个的姓名？(回车取消)：")
    if not idx.isdigit() or not (1 <= int(idx) <= len(accounts)):
        print("已取消")
        return
    item = accounts[int(idx) - 1]
    nm = ask(f"新的姓名（当前 {item.get('name') or '未命名'}）：")
    if nm:
        item["name"] = nm
        save_store(d)
        print("[已更新]")


def switch_account(d):
    accounts = show_list(d)
    if not accounts:
        return
    idx = ask("切换到第几个？(回车取消)：")
    if not idx.isdigit() or not (1 <= int(idx) <= len(accounts)):
        print("已取消")
        return
    # 先把当前 config 的最新 token 存回旧账户，避免丢
    sync_from_conf(d)
    picked = accounts[int(idx) - 1]
    if apply_account(d, picked["username"], picked.get("serial")):
        item = picked
        if item and not item.get("name") and (item.get("token") or "").strip():
            print("[提示] 正在从服务端补一下姓名…")
            refresh_current_meta(d, quiet=True)


def menu():
    d = load_store()
    if import_from_conf(d):
        print("[提示] 已把 config.ini 里现有的账户收进列表")
    while True:
        show_list(d)
        show_current(d)
        print("\n[1] 切换账户  [2] 添加账户  [3] 删除账户  [4] 改姓名  "
              "[5] 刷新姓名/班级(联网)  [0] 退出")
        choice = ask("选择：")
        if choice in ("0", "q", ""):
            return
        if choice == "1":
            switch_account(d)
        elif choice == "2":
            add_account(d)
        elif choice == "3":
            del_account(d)
        elif choice == "4":
            rename_account(d)
        elif choice == "5":
            sync_from_conf(d)
            refresh_current_meta(d)


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        d = load_store()
        import_from_conf(d)
        if cmd == "list":
            show_list(d)
            show_current(d)
        elif cmd == "whoami":
            show_current(d)
        elif cmd == "use" and len(sys.argv) > 2:
            # 不 sync：账户文件里的 token 才是最新的（grab_device 刚抓的那份），
            # 拿 config 里的旧值回写会把它覆盖掉。
            apply_account(d, sys.argv[2])
        elif cmd == "refresh":
            sync_from_conf(d)
            refresh_current_meta(d)
        else:
            print(__doc__)
        return
    menu()


if __name__ == "__main__":
    main()

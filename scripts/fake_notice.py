#!/usr/bin/env python3
"""把所有订阅输出替换为「通知假节点」。

背景：本人因学业原因暂停所有项目，订阅不再提供真实节点。
本脚本为每个来源生成一份只含公告节点的 clash.yaml：
客户端里会看到一条无法连接的「公告」节点，用于传达停更信息。
"""
import os

NOTICE = "【公告】因学业原因，所有项目暂停（详见 wzml.us.ci）"

TEMPLATE = """# 本订阅已停止提供节点：因学业原因，所有项目暂停。
# 该文件由 scripts/fake_notice.py 生成，仅用于在客户端展示公告。
mixed-port: 7890
allow-lan: false
mode: rule
log-level: warning

proxies:
  - name: "{notice}"
    type: socks5
    server: 127.0.0.1
    port: 1
    udp: false

proxy-groups:
  - name: "PROXY"
    type: select
    proxies: ["{notice}"]

rules:
  - MATCH,PROXY
"""

OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

def main():
    names = sorted(d for d in os.listdir(OUTPUT) if os.path.isdir(os.path.join(OUTPUT, d)))
    if not names:
        raise SystemExit(f"[FAIL] {OUTPUT} 下没有来源目录")
    text = TEMPLATE.format(notice=NOTICE)
    for name in names:
        path = os.path.join(OUTPUT, name, "clash.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[OK] {name}: 已替换为通知假节点")
    print(f"共处理 {len(names)} 个来源")

if __name__ == "__main__":
    main()
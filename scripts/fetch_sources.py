#!/usr/bin/env python3
"""下载各来源的原始订阅到 output/<source>/clash.raw.yaml,交给 sanitize.py 清洗。

设计要点:
  * 原始文件写入 .raw.yaml(不入库),已发布的 clash.yaml 只在清洗+内核校验
    通过后才被替换 —— 下载失败时旧文件保持原样,不会被重新盖上"更新时间";
  * 单个来源失败不影响其它来源,只有全部失败才返回非 0。

用法:
  python scripts/fetch_sources.py            # 下载全部来源(不含 yoyapai,由 scraper.py 抓取)
  python scripts/fetch_sources.py au1rxx     # 只下载指定来源
"""
import os
import sys

import requests

from sources import FETCH_URLS

HEADERS = {"User-Agent": "proxy-node-bot/1.0"}
RAW_NAME = "clash.raw.yaml"
TIMEOUT = 120


def fetch_one(name, url):
    out_dir = os.path.join("output", name)
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, RAW_NAME)
    if os.path.exists(dst):
        os.unlink(dst)  # 失败时不会残留上一轮原始文件
    print(f"  [GET] {name}: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    if not resp.content.strip():
        raise ValueError("返回内容为空")
    with open(dst, "wb") as f:
        f.write(resp.content)
    print(f"  [OK] {name} ({len(resp.content)} bytes)")
    return len(resp.content)


def main():
    names = sys.argv[1:] if len(sys.argv) > 1 else list(FETCH_URLS)
    unknown = [n for n in names if n not in FETCH_URLS]
    if unknown:
        raise SystemExit(f"[FAIL] 未知来源: {unknown} (可选: {', '.join(FETCH_URLS)})")
    ok, fail = 0, []
    for name in names:
        try:
            fetch_one(name, FETCH_URLS[name])
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            fail.append(name)
    print(f"下载完成: 成功 {ok}, 失败 {len(fail)} {fail}")
    if fail:
        print("  (失败来源本次不更新,已发布的 clash.yaml 保持不变)")
    if names and ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

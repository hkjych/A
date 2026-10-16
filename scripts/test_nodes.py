#!/usr/bin/env python3
"""用 Clash.Meta (mihomo) 内核测试节点可达性与下载速度,合并生成 AIO 精选订阅。

用法:
  python scripts/test_nodes.py <cleaned1.yaml> [<cleaned2.yaml> ...] -o output/aio/clash.yaml

流程:
  1. 合并各来源清洗后的节点(按完整配置去重,忽略节点名);
  2. 启动 mihomo 内核(仅含待测节点 + MATCH,DIRECT);
  3. 可达性:通过 RESTful API 请求
     GET /proxies/{name}/delay?url=https://www.gstatic.com/generate_204
     丢弃不可用节点,保留延迟;
  4. 测速:对可达节点启动一批"出口绑定"监听器(listeners + proxy: 节点名),
     并发下载 20MB 测试文件,实测每个节点的 MB/s;
  5. 汇总:节点名统一加 "[x.xMB/s]" 标注,按 高速 -> 延迟 排序,生成
     "⚡ 高速节点(>阈值)" 独立分组 + 节点选择 + 自动选择;
  6. 注入说明节点,写出 AIO 精选订阅。

mihomo 二进制:环境变量 MIHOMO_BIN,否则自动探测 /usr/local/bin/mihomo、/tmp/mihomo、PATH。
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from sanitize import SafeDumper, fake_proxy
from sources import SOURCES

TEST_URL = "https://www.gstatic.com/generate_204"

# 测速文件候选(按顺序探测直连可达性):20MB 固定大小文件 + mihomo 发行包。
def default_speed_urls():
    import platform

    arch = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "arm64": "arm64"} \
        .get(platform.machine(), "amd64")
    version = os.environ.get("MIHOMO_VERSION", "v1.19.9")
    return [
        "https://speed.cloudflare.com/__down?bytes=20000000",
        f"https://github.com/MetaCubeX/mihomo/releases/download/{version}/mihomo-linux-{arch}-{version}.gz",
    ]
SPEED_UA = "proxy-node-bot/1.0 (speedtest)"

GROUP_TYPES = {
    "Selector", "URLTest", "Fallback", "Relay", "LoadBalance", "Compatible",
    "Pass", "ShadowTLS", "Reject", "Direct",
}
SKIP_NAMES = {"GLOBAL", "DIRECT", "REJECT", "PASS"}
AUTHOR = "wzmwayne"
REPO = "https://github.com/wzmwayne/proxy-node"

# AIO 节点名标注:重新生成时可重复运行(先剥掉旧标注)
ANNOTATION_RE = None


def _annotation_re():
    import re

    global ANNOTATION_RE
    if ANNOTATION_RE is None:
        ANNOTATION_RE = re.compile(r"^\[(?:\d+(?:\.\d+)?\s*MB/s|测速失败|未测速)\]\s+")
    return ANNOTATION_RE


def strip_annotation(name: str) -> str:
    return _annotation_re().sub("", str(name), count=1)


def find_free_ports(n):
    """一次性申请 n 个空闲端口(先全部占用再统一释放,尽量避免重复)。"""
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def find_mihomo(explicit=None):
    cands = [explicit, os.environ.get("MIHOMO_BIN"), "/usr/local/bin/mihomo", "/tmp/mihomo"]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    which = shutil.which("mihomo")
    if which:
        return which
    raise SystemExit("[FAIL] 未找到 mihomo 内核(设置 MIHOMO_BIN 或用 --mihomo 指定)")


def api_get(port, secret, path, timeout=10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    req.add_header("Authorization", f"Bearer {secret}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Core:
    """一个 mihomo 测试内核进程。"""

    def __init__(self, mihomo, proxies, rules, listeners=None, keep_dir=False):
        self.mihomo = mihomo
        self.proxies = proxies
        self.rules = rules
        self.listeners = listeners or []
        self.secret = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        self.ctrl_port = find_free_ports(1)[0]
        self.td = tempfile.mkdtemp(prefix="pnode-")
        self.keep_dir = keep_dir
        self.proc = None

    def start(self, wait=60.0):
        cfg = {
            "mixed-port": find_free_ports(1)[0],
            "allow-lan": False,
            "mode": "rule",
            "log-level": "silent",
            "external-controller": f"127.0.0.1:{self.ctrl_port}",
            "secret": self.secret,
            "proxies": self.proxies,
            "rules": self.rules,
        }
        if self.listeners:
            cfg["listeners"] = self.listeners
        cfg_path = os.path.join(self.td, "config.yaml")
        import yaml

        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, Dumper=SafeDumper, allow_unicode=False, sort_keys=False)
        self.proc = subprocess.Popen(
            [self.mihomo, "-d", self.td, "-f", cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                api_get(self.ctrl_port, self.secret, "/version", timeout=3)
                return self
            except Exception:
                if self.proc.poll() is not None:
                    raise SystemExit("[FAIL] mihomo 进程提前退出(配置无法加载?)")
                time.sleep(0.2)
        self.stop()
        raise SystemExit("[FAIL] mihomo API 未就绪")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if not self.keep_dir:
            shutil.rmtree(self.td, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def test_delay(port, secret, name, timeout_ms=5000):
    q = urllib.parse.quote(name, safe="")
    url_q = urllib.parse.quote(TEST_URL, safe="")
    try:
        data = api_get(port, secret, f"/proxies/{q}/delay?timeout={timeout_ms}&url={url_q}")
        return name, data.get("delay")
    except Exception:
        return name, None


def probe_direct(url, timeout=15):
    """探测测试文件能否从 runner 直连下载(避免内核/节点背锅)。"""
    req = urllib.request.Request(url, headers={"User-Agent": SPEED_UA, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(65536)
        return True
    except Exception:
        return False


def pick_speed_url(candidates, timeout=15):
    for url in candidates:
        if probe_direct(url, timeout=timeout):
            return url
    return None


def measure_speed(port, url, max_bytes, timeout, early_bytes, early_rate):
    """经 127.0.0.1:port 下载 url,返回 (MB/s, 字节数, 秒数, 失败原因)。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({
        "http": f"http://127.0.0.1:{port}",
        "https": f"http://127.0.0.1:{port}",
    }))
    req = urllib.request.Request(url, headers={"User-Agent": SPEED_UA, "Accept-Encoding": "identity"})
    total, t0, t_first, err = 0, time.monotonic(), None, None
    try:
        with opener.open(req, timeout=timeout) as r:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                now = time.monotonic()
                if t_first is None:
                    t_first = now
                el = max(now - t_first, 0.3)  # 排除建连/TLS 握手,只算吞吐
                if total >= max_bytes:
                    break
                if total >= early_bytes and total / el / 1e6 >= early_rate:
                    break  # 明显超过阈值,提前结束省流量
                if now - t0 >= timeout:
                    break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:120]

    if total == 0:
        return 0.0, 0, time.monotonic() - t0, err or "no data"
    el = time.monotonic() - (t_first or t0)
    rate = total / max(el, 0.001) / 1e6
    if err and total < 1_000_000:
        return 0.0, total, el, err  # 只传了一点就断了,不算速度
    return rate, total, el, err


def load_inputs(inputs):
    """合并各来源节点(按完整配置去重),并记录每个节点来自哪个来源。"""
    import yaml

    merged, seen_cfg, per_source, dup_names, src_of_name = {}, set(), {}, 0, {}
    for inp in inputs:
        src = os.path.basename(os.path.dirname(os.path.abspath(inp)))
        with open(inp, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        n = 0
        for p in d.get("proxies", []):
            if not isinstance(p, dict) or not p.get("name") or not p.get("server"):
                continue
            if str(p["name"]).startswith("说明-"):
                continue
            key = hashlib.sha1(
                json.dumps({k: v for k, v in p.items() if k != "name"},
                           sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if key in seen_cfg:
                continue
            seen_cfg.add(key)
            name = str(p["name"])
            if name in merged:
                dup_names += 1
                i = 2
                while f"{name} #{i}" in merged:
                    i += 1
                name = f"{name} #{i}"
                p = dict(p, name=name)
            merged[name] = p
            src_of_name[name] = src
            n += 1
        per_source[inp] = n
    return list(merged.values()), per_source, dup_names, src_of_name


def build_aio(good, speeds, tested, threshold, n_inputs, speed_label, speed_enabled,
              src_of_name, quality_min_speed, quality_max_delay):
    """good: [(proxy, delay)];speeds: {name: MB/s or None};src_of_name: {name: 来源标识}

    生成分组:
      说明 / ⚡ 高速节点 / 🏅 优质节点 / 🚀 节点选择(全部精选) / ♻️ 自动选择 /
      📦 <来源> 各来源精选(仅保留测速后的存活节点)
    """
    fast, quality_only, rest = [], [], []
    for p, delay in good:
        rate = speeds.get(p["name"])
        is_fast = rate is not None and rate > threshold
        is_quality = rate is not None and rate >= quality_min_speed and delay <= quality_max_delay
        if is_fast:
            fast.append((p, delay, rate))
        elif is_quality:
            quality_only.append((p, delay, rate))
        else:
            rest.append((p, delay, rate))
    fast.sort(key=lambda x: -x[2])
    quality_only.sort(key=lambda x: (-x[2], x[1]))
    rest.sort(key=lambda x: x[1])
    quality = fast + quality_only          # 优质节点是高速节点的超集
    ordered = fast + quality_only + rest   # 全部精选:高速 -> 优质 -> 其余按延迟

    def annotate(p, rate):
        base = strip_annotation(p["name"])
        if not speed_enabled:
            tag = "[未测速]"
        elif rate is None:
            tag = "[测速失败]"
        else:
            tag = f"[{rate:.1f}MB/s]"
        return dict(p, name=f"{tag} {base}")

    annotated = [annotate(p, r) for p, _, r in ordered]
    names = [p["name"] for p in annotated]
    name_of = {id(p): a["name"] for (p, _, _), a in zip(ordered, annotated)}
    fast_names = [name_of[id(p)] for p, _, _ in fast]
    quality_names = [name_of[id(p)] for p, _, _ in quality]

    now = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600))
    fake_names = [
        f"说明-来源: AIO 精选(合并 {n_inputs} 个来源)",
        f"说明-延迟测试: {len(good)}/{tested} 节点通过 generate_204",
    ]
    if speed_enabled:
        fake_names.append(
            f"说明-测速: {len(fast)} 个节点 > {threshold:g} MB/s({speed_label}实测)"
        )
        fake_names.append(
            f"说明-优质节点: 速度 ≥ {quality_min_speed:g} MB/s 且延迟 ≤ {quality_max_delay} ms"
            f"(共 {len(quality)} 个)"
        )
    else:
        fake_names.append("说明-测速: 本次跳过(测试文件不可达)")
    fake_names += [
        f"说明-更新时间: {now} (CST)",
        f"说明-作者: {AUTHOR}",
        f"说明-仓库: {REPO}",
    ]

    groups = [{"name": "说明", "type": "select", "proxies": fake_names}]
    groups.append({
        "name": f"⚡ 高速节点(>{threshold:g}MB/s)",
        "type": "select",
        "proxies": fast_names or ["DIRECT"],
    })
    groups.append({"name": "🏅 优质节点", "type": "select", "proxies": quality_names or ["DIRECT"]})
    groups.append({"name": "🚀 节点选择(全部精选)", "type": "select", "proxies": names})
    groups.append({
        "name": "♻️ 自动选择",
        "type": "url-test",
        "url": TEST_URL,
        "interval": 300,
        "proxies": names,
    })

    # 每个来源一个标签页(仅含该来源通过延迟+测速的精选节点)
    per_src = {}
    for p, _, _ in ordered:
        src = src_of_name.get(p["name"], "")
        if src:
            per_src.setdefault(src, []).append(name_of[id(p)])
    for src, members in per_src.items():
        label = SOURCES.get(src, (src, ""))[0]
        groups.append({"name": f"📦 {label}", "type": "select", "proxies": members})
    src_stat = {SOURCES.get(s, (s, ""))[0]: len(m) for s, m in per_src.items()}

    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "external-controller": "127.0.0.1:9090",
        "proxies": [fake_proxy(n) for n in fake_names] + annotated,
        "proxy-groups": groups,
        "rules": ["MATCH,🚀 节点选择(全部精选)"],
    }, len(fast), len(quality), src_stat


def run_speed_batch(mihomo, batch, speed_url, args, ports):
    """对一批节点启动绑定出口的监听器,并发测速。返回 {name: MB/s or None}。"""
    listeners = [
        {"name": f"spd-{i}", "type": "mixed", "port": ports[i],
         "listen": "127.0.0.1", "proxy": p["name"]}
        for i, p in enumerate(batch)
    ]
    out = {}
    core = Core(mihomo, batch, ["MATCH,DIRECT"], listeners=listeners)
    try:
        core.start(wait=30)
    except SystemExit as e:
        core.stop()
        print(f"      [WARN] 测速内核启动失败,跳过本批 {len(batch)} 个节点: {e}")
        return {p["name"]: None for p in batch}
    try:
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = {
                ex.submit(measure_speed, ports[i], speed_url, args.speed_bytes,
                          args.speed_timeout, args.speed_early_bytes, args.speed_early_rate): p["name"]
                for i, p in enumerate(batch)
            }
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    rate, nbytes, secs, err = fut.result()
                except Exception as e:  # 单个节点异常不影响整批
                    rate, nbytes, secs, err = 0.0, 0, 0, str(e)[:80]
                out[name] = rate if nbytes else None
                if args.verbose:
                    print(f"        {name[:40]:40s} {rate:6.2f} MB/s "
                          f"{nbytes/1e6:6.1f}MB {secs:5.2f}s {err or ''}")
    finally:
        core.stop()
    return out


def main():
    ap = argparse.ArgumentParser(description="mihomo 内核节点可达性 + 下载测速 + AIO 合并")
    ap.add_argument("inputs", nargs="+", help="清洗后的各来源 clash.yaml")
    ap.add_argument("-o", "--output", required=True, help="输出 AIO clash.yaml")
    ap.add_argument("--mihomo", default=None, help="mihomo 内核路径(默认 MIHOMO_BIN 或自动探测)")
    ap.add_argument("--concurrency", type=int, default=96, help="可达性(延迟)测试并发")
    ap.add_argument("--timeout-ms", type=int, default=5000, help="单节点延迟测试超时")
    ap.add_argument("--limit", type=int, default=0, help="只测试前 N 个节点(调试用,0=全部)")
    ap.add_argument("--no-speed", action="store_true", help="跳过测速阶段")
    ap.add_argument("--speed-url", default=os.environ.get("SPEED_TEST_URL", ""),
                    help="测速文件 URL(逗号分隔可多个,默认 20MB Cloudflare 文件)")
    ap.add_argument("--speed-concurrency", type=int, default=48, help="测速并发(同时下载的节点数)")
    ap.add_argument("--speed-bytes", type=int, default=20_000_000, help="单个节点最大下载字节数")
    ap.add_argument("--speed-timeout", type=float, default=8.0, help="单个节点测速超时(秒)")
    ap.add_argument("--speed-early-bytes", type=int, default=2_000_000,
                    help="已下载该字节数且速率已达标则提前结束(省流量)")
    ap.add_argument("--speed-early-rate", type=float, default=3.0, help="提前结束速率阈值(MB/s)")
    ap.add_argument("--speed-max-nodes", type=int, default=0, help="最多测速多少个节点(0=全部可达节点)")
    ap.add_argument("--fast-threshold", type=float, default=2.0, help="高速节点阈值(MB/s)")
    ap.add_argument("--quality-min-speed", type=float, default=1.0, help="优质节点最低速度(MB/s)")
    ap.add_argument("--quality-max-delay", type=int, default=1500, help="优质节点最高延迟(ms)")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每个节点的测速明细")
    ap.add_argument("--keep-temp", action="store_true", help="保留内核临时目录(调试)")
    args = ap.parse_args()

    t_start = time.monotonic()
    mihomo = find_mihomo(args.mihomo)
    speed_urls = [u.strip() for u in (args.speed_url or ",".join(default_speed_urls())).split(",") if u.strip()]

    # 1) 合并去重
    proxies, per_source, dup_names, src_of_name = load_inputs(args.inputs)
    if args.limit:
        proxies = proxies[:args.limit]
    print(f"[1/5] 合并 {len(args.inputs)} 个来源,去重后待测节点: {len(proxies)}"
          f"(重名自动加后缀 {dup_names} 个)")
    for src, n in per_source.items():
        print(f"        {os.path.basename(os.path.dirname(src)):16s} +{n}")
    if not proxies:
        raise SystemExit("[FAIL] 无任何节点可测")

    # 2) 可达性(延迟)测试
    with Core(mihomo, proxies, ["MATCH,DIRECT"], keep_dir=args.keep_temp) as core:
        pmap = {}
        for _ in range(10):
            try:
                pmap = api_get(core.ctrl_port, core.secret, "/proxies")["proxies"]
            except Exception:
                pmap = {}
            if pmap:
                break
            time.sleep(0.5)
        names = [n for n, info in pmap.items()
                 if n not in SKIP_NAMES and info.get("type") not in GROUP_TYPES]
        if not names:
            raise SystemExit("[FAIL] 内核未返回任何可测节点")
        total = len(names)
        print(f"[2/5] 可达性测试: {total} 个节点 -> generate_204(并发 {args.concurrency})")
        ok, done, interval = {}, 0, max(1, total // 20)
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {ex.submit(test_delay, core.ctrl_port, core.secret, n, args.timeout_ms): n for n in names}
            for fut in as_completed(futs):
                name, delay = fut.result()
                done += 1
                if delay is not None:
                    ok[name] = delay
                if done % interval == 0 or done == total:
                    print(f"        进度 {done}/{total} 可用 {len(ok)} "
                          f"({time.monotonic()-t_start:.0f}s)", flush=True)
        print(f"        可达节点: {len(ok)}/{total}")
        if not ok:
            raise SystemExit("[FAIL] 全部节点不可达,不生成 AIO")

    # 3) 测速
    by_name = {p["name"]: p for p in proxies}
    candidates = sorted(ok, key=lambda n: ok[n])
    if args.speed_max_nodes:
        candidates = candidates[:args.speed_max_nodes]
    speeds = {n: None for n in ok}
    speed_url, speed_enabled = None, False
    speed_label = "测试文件"
    if args.no_speed:
        print("[3/5] 测速: 已跳过(--no-speed)")
    else:
        print(f"[3/5] 测速文件探测: {speed_urls}")
        speed_url = pick_speed_url(speed_urls)
        if not speed_url:
            print("        [WARN] 测试文件直连不可达,跳过测速(节点名标注为 [未测速])")
        else:
            speed_enabled = True
            speed_label = f"{args.speed_bytes // 1000000}MB 文件" if "cloudflare" in speed_url else "发行文件"
            batches = [candidates[i:i + args.speed_concurrency]
                       for i in range(0, len(candidates), args.speed_concurrency)]
            print(f"        使用 {speed_url}")
            print(f"        测速 {len(candidates)} 个节点,分 {len(batches)} 批,"
                  f"每批 {args.speed_concurrency} 并发,单节点上限 "
                  f"{args.speed_bytes/1e6:.0f}MB/{args.speed_timeout:g}s")
            for bi, batch in enumerate(batches, 1):
                ports = find_free_ports(len(batch))
                res = run_speed_batch(mihomo, [by_name[n] for n in batch], speed_url, args, ports)
                speeds.update(res)
                got = sum(1 for v in res.values() if v is not None)
                fast_n = sum(1 for v in res.values() if v is not None and v > args.fast_threshold)
                print(f"        批次 {bi}/{len(batches)}: 测速成功 {got}/{len(batch)},"
                      f"高速 {fast_n} ({time.monotonic()-t_start:.0f}s)", flush=True)

    # 4) 排序 / 分组 / 标注
    good = [(by_name[n], ok[n]) for n in ok]
    aio, n_fast, n_quality, src_stat = build_aio(
        good, speeds, total, args.fast_threshold, len(args.inputs),
        speed_label, speed_enabled, src_of_name,
        args.quality_min_speed, args.quality_max_delay,
    )
    print(f"[4/5] 生成 AIO: 全部精选 {len(good)} 个,"
          f"高速(>{args.fast_threshold:g}MB/s) {n_fast} 个,优质 {n_quality} 个")
    for label, n in src_stat.items():
        print(f"        📦 {label}: {n} 个精选节点")

    # 5) 写出
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    import yaml

    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(aio, f, Dumper=SafeDumper, allow_unicode=False,
                  default_flow_style=False, sort_keys=False)
    os.replace(tmp, args.output)
    n_groups = len(aio["proxy-groups"])
    print(f"[5/5] AIO 已写入 {args.output}: {len(good)} 个可用节点"
          f"(高速 {n_fast} 个 / 优质 {n_quality} 个 / {n_groups} 个分组),"
          f"耗时 {time.monotonic()-t_start:.0f}s")


if __name__ == "__main__":
    main()

# 宣传：vl.wzml.cc.cd 免费视频解析

# proxy-node

免费 Clash 节点订阅聚合 —— 每 4 小时自动抓取、清洗、**真内核实测(可达性 + 20MB 测速)**、更新。

## 说明

本仓库通过 GitHub Actions **每 4 小时**(UTC 00/04/08/12/16/20,即北京时间 08/12/16/20/00/04 点)自动抓取多个免费节点来源,对每个来源的订阅文件做**清洗**后发布,并额外用 Clash.Meta (mihomo) 内核**逐个节点实测**生成 AIO 精选。

**不同来源的订阅文件相互独立、按来源目录分类存放,不会混淆。**

## 订阅链接

> **AIO 精选(推荐)**:全部来源的节点先测 `https://www.gstatic.com/generate_204` 判可达,再对可达节点**真实下载 20MB 文件测速**;每个节点名都带 `[x.xMB/s]` 标注,并生成多个分组标签页:

| 标签页 | 内容 |
|--------|------|
| `说明` | 来源数 / 延迟通过数 / 测速统计 / 更新时间 / 作者 |
| `⚡ 高速节点(>2MB/s)` | 实测速度 > 2MB/s 的节点 |
| `🏅 优质节点` | 速度 ≥ 1MB/s 且延迟 ≤ 1500ms(高速节点是其子集) |
| `🚀 节点选择(全部精选)` | 全部通过延迟 + 测速的节点(默认出口) |
| `♻️ 自动选择` | 全部精选节点,url-test 自动选优 |
| `📦 <来源>` | **每个来源一个精选标签页**,只放该来源通过测试的节点 |

| 类型 | 直连 | ghproxy.net 镜像(国内网络) |
|------|------|------------------------------|
| **AIO 精选(合并全部来源)** | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/aio/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/aio/clash.yaml |

**单来源订阅(直连 + ghproxy 镜像)**:

| 来源 | 直连 | ghproxy.net 镜像 |
|------|------|-------------------|
| yoyapai.com | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/yoyapai/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/yoyapai/clash.yaml |
| Au1rxx/free-vpn-subscriptions | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/au1rxx/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/au1rxx/clash.yaml |
| Ruk1ng001/freeSub | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/freesub/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/freesub/clash.yaml |
| ripaojiedian/freenode | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/ripaojiedian/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/ripaojiedian/clash.yaml |
| zhangkaiitugithub/passcro | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/passcro/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/passcro/clash.yaml |
| anaer.github.io/Sub | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/anaer/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/anaer/clash.yaml |
| xiaoji235/airport-free | https://raw.githubusercontent.com/wzmwayne/proxy-node/main/output/xiaoji235/clash.yaml | https://ghproxy.net/github.com/wzmwayne/proxy-node/raw/main/output/xiaoji235/clash.yaml |

> 仅提供 Clash (Mihomo) 格式。直接复制链接到 FlClash / Clash Verge Rev / Mihomo 的订阅导入框即可。

## AIO 精选怎么来的

1. **合并去重**:按完整节点配置(协议/服务器/端口/凭据)去重,忽略节点名;
2. **可达性**:内核 REST API 逐节点请求 `generate_204`(默认 5s 超时),不可达即淘汰;
3. **测速**:对可达节点启动"出口绑定"监听器(`listeners` + `proxy: 节点名`),并发真实下载 20MB 测试文件(默认 `speed.cloudflare.com`,不可达时回退到 mihomo 发行包),按 `字节/耗时` 计算 MB/s;已达标即提前结束以节省流量;
4. **标注与分组**:每个节点名前缀 `[x.xMB/s]`(失败标 `[测速失败]`,未测标 `[未测速]`);生成 `⚡ 高速节点(>2MB/s)`、`🏅 优质节点`、`🚀 节点选择(全部精选)`、`♻️ 自动选择`,以及**每个来源各自的 `📦 <来源>` 精选标签页**(排序:高速 → 优质 → 其余按延迟);
5. **总耗时**约 5~8 分钟(取决于来源规模与节点存活率)。

## 清洗与发布门禁

每个来源的 `clash.yaml` 在发布前都会经过 `scripts/sanitize.py` 处理,并在**内核校验通过后**才替换线上文件:

- 按 go-yaml v3 的码点白名单检查**解码后**的每个字符串值,丢弃含控制字符的节点 —— 这是 FlClash 报 `yaml: control characters are not allowed` 的根因;
- 剔除上游错误页残留的垃圾顶层键(如 `error code: 520`);
- **名称唯一性**:重复节点名/组名、节点名与组名冲突自动改名或丢弃(否则 mihomo 直接拒绝加载整份配置:`proxy xxx is the duplicate name`);
- **悬空引用修复**:丢弃节点/分组后,同步清理 `group -> proxy`、`group -> group`、`rule -> 目标` 的失效引用(否则报 `proxy group[0]: xxx: 'yyy' not found`);
- 清理 `proxy-groups` 中指向已删除节点的失效引用;空分组自动补 `DIRECT`;
- 输出为纯 ASCII YAML(非 ASCII 以 `\uXXXX` 转义,兼容所有 YAML 解析器);
- 写入前二次解析校验 + `mihomo -t` 内核门禁,任一不过即**拒绝发布并保留上一版**(不会把坏配置推给用户);
- 抓取失败/中断的来源**不会被重新盖上"更新时间"**,旧文件原样保留,时间戳即真实新鲜度。

## 目录结构

```
output/
  yoyapai/  clash.yaml     # yoyapai.com 来源(清洗后)
  au1rxx/   clash.yaml     # Au1rxx/free-vpn-subscriptions 来源(清洗后)
  freesub/  clash.yaml     # Ruk1ng001/freeSub 来源(清洗后)
  ripaojiedian/ clash.yaml # ripaojiedian/freenode 来源(清洗后)
  passcro/  clash.yaml     # zhangkaiitugithub/passcro 来源(清洗后)
  anaer/    clash.yaml     # anaer.github.io/Sub 来源(清洗后)
  xiaoji235/ clash.yaml    # xiaoji235/airport-free 来源(清洗后)
  aio/      clash.yaml     # AIO 精选(合并全部来源,经内核可达性 + 测速)
scripts/
  sources.py               # 来源清单(名称/主页/下载 URL,集中维护)
  scraper.py               # 抓取 yoyapai.com 文章并下载最新订阅
  fetch_sources.py         # 下载其它来源到 output/<name>/clash.raw.yaml(暂存)
  sanitize.py              # 清洗(控制字符/垃圾键/重名/悬空引用)+ 内核门禁
  test_nodes.py            # 内核可达性 + 20MB 测速 + 生成 AIO
  check_sources.py         # 校验 output/ 与来源清单一致(防孤儿目录)
  install_mihomo.sh        # 安装 mihomo 内核(SHA256 校验)+ 预热地理库
  mihomo.sha256            # 内核发行包校验和
latest_urls.json           # yoyapai 最新文章信息
requirements.txt           # Python 依赖(固定版本)
.github/workflows/scrape.yml
```

## 本地运行

```bash
pip install -r requirements.txt
bash scripts/install_mihomo.sh                 # 下载并校验 mihomo(可用 MIHOMO_BIN 覆盖)

python scripts/scraper.py                      # 抓 yoyapai -> output/yoyapai/clash.raw.yaml
python scripts/fetch_sources.py                # 抓其它来源 -> output/<name>/clash.raw.yaml

# 清洗单个来源(带内核门禁;--gate 需要 mihomo 与网络)
python scripts/sanitize.py output/yoyapai/clash.raw.yaml output/yoyapai/clash.yaml \
  --source yoyapai --gate --mihomo "$MIHOMO_BIN" --mihomo-dir .cache/geo

# 可达性 + 测速 + 生成 AIO
python scripts/test_nodes.py output/*/clash.yaml -o output/aio/clash.yaml \
  --concurrency 96 --speed-concurrency 48 --fast-threshold 2.0 -v

python scripts/check_sources.py                # 来源清单一致性
```

常用调参:`--no-speed` 跳过测速;`--limit N` 只测前 N 个节点(调试);
`--speed-url` 自定义测速文件;`--speed-max-nodes N` 限制测速节点数;
`--speed-timeout` / `--speed-bytes` 控制单节点测速开销。

## 安全提示

- 所有节点均来自**第三方公开来源**,服务器不受本项目控制,请勿用于登录敏感账号或传输隐私数据;
- AIO 中相当比例的 `http` / `socks5` 节点为明文传输,仅建议用于公开内容访问;
- 本仓库只做格式清洗与可用性/速度实测,**不校验节点运营方的任何行为**。

## License

MIT,见 [LICENSE](LICENSE)。

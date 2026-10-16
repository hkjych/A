#!/usr/bin/env bash
# 安装 mihomo 内核(带 SHA256 校验)并预热地理库缓存。
#
# 用法:bash scripts/install_mihomo.sh
# 输出(/追加到 $GITHUB_ENV):
#   MIHOMO_BIN   内核可执行文件路径
#   MIHOMO_DIR   地理库工作目录(可被 actions/cache 缓存)
#   MIHOMO_GATE  1=可做 mihomo -t 门禁,0=地理库不可用,跳过门禁
set -uo pipefail

VERSION="${MIHOMO_VERSION:-v1.19.9}"
CACHE="${MIHOMO_CACHE:-$HOME/.cache/mihomo}"
GEO_DIR="${MIHOMO_DIR:-$PWD/.cache/geo}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$(uname -m)" in
  x86_64 | amd64) ARCH=amd64 ;;
  aarch64 | arm64) ARCH=arm64 ;;
  *)
    echo "::error::不支持的架构: $(uname -m)(请手动安装 mihomo 并设置 MIHOMO_BIN)"
    exit 1
    ;;
esac

ASSET="mihomo-linux-${ARCH}-${VERSION}.gz"
URL="https://github.com/MetaCubeX/mihomo/releases/download/${VERSION}/${ASSET}"
# 国内可用 GH_PROXY(如 https://ghproxy.net)加速下载;CI 上不设置,直连
if [ -n "${GH_PROXY:-}" ]; then
  URL="${GH_PROXY%/}/$URL"
  echo "[INFO] 使用 GH_PROXY 镜像: $URL"
fi
BIN="$CACHE/mihomo-${VERSION}-${ARCH}"

mkdir -p "$CACHE" "$GEO_DIR"

if [ ! -x "$BIN" ]; then
  echo "下载 $URL"
  if ! curl -fsSL --retry 3 --retry-delay 2 -o "$CACHE/$ASSET" "$URL"; then
    echo "::error::mihomo 下载失败"; exit 1
  fi
  want="$(awk -v v="$VERSION" -v a="$ASSET" '$1 == v && $2 == a { print $3 }' "$ROOT/scripts/mihomo.sha256" 2>/dev/null)"
  if [ -n "${want:-}" ]; then
    got="$(sha256sum "$CACHE/$ASSET" | awk '{print $1}')"
    if [ "$got" != "$want" ]; then
      echo "::error::$ASSET SHA256 校验失败(期望 $want,实际 $got)"; exit 1
    fi
    echo "[OK] SHA256 校验通过"
  else
    echo "::warning::$ASSET 无内置校验和,跳过校验"
  fi
  gunzip -c "$CACHE/$ASSET" > "$BIN" || { echo "::error::解压失败"; exit 1; }
  chmod +x "$BIN"
  rm -f "$CACHE/$ASSET"
else
  echo "[OK] 使用缓存内核 $BIN"
fi
"$BIN" -v || true

# 预热地理库(MMDB/geosite):否则每次 mihomo -t 都要联网下载,拖慢工作流
GATE=1
if [ -f "$GEO_DIR/.ready" ]; then
  echo "[OK] 地理库缓存已就绪"
else
  cat > "$GEO_DIR/warm.yaml" <<'YAML'
mixed-port: 7890
mode: rule
log-level: warning
rules:
  - GEOSITE,cn,DIRECT
  - GEOIP,CN,DIRECT
  - MATCH,DIRECT
YAML
  if timeout 240 "$BIN" -t -d "$GEO_DIR" -f "$GEO_DIR/warm.yaml" > "$GEO_DIR/warm.log" 2>&1 \
     && grep -q "test is successful" "$GEO_DIR/warm.log"; then
    : > "$GEO_DIR/.ready"
    echo "[OK] 地理库预热完成"
  else
    echo "::warning::地理库预热失败,mihomo 内核门禁将跳过(脚本自身校验仍然生效)"
    tail -3 "$GEO_DIR/warm.log" 2>/dev/null || true
    GATE=0
  fi
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "MIHOMO_BIN=$BIN"
    echo "MIHOMO_DIR=$GEO_DIR"
    echo "MIHOMO_GATE=$GATE"
  } >> "$GITHUB_ENV"
else
  echo "MIHOMO_BIN=$BIN"
  echo "MIHOMO_DIR=$GEO_DIR"
  echo "MIHOMO_GATE=$GATE"
fi

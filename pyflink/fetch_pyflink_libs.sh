#!/usr/bin/env bash
# Baixa o tarball gigante do apache-flink-libraries (220MB sdist) para uso no
# Dockerfile.flink. Pular o PyPI no daemon Docker — daqui ele timeouta;
# no host com curl + resume funciona rapidíssimo (~7s @ 30MB/s).
#
# Uso: bash pyflink/fetch_pyflink_libs.sh

set -euo pipefail

VERSION="${PYFLINK_LIBS_VERSION:-1.18.1}"
URL="https://files.pythonhosted.org/packages/source/a/apache-flink-libraries/apache-flink-libraries-${VERSION}.tar.gz"
DEST_DIR="$(cd "$(dirname "$0")" && pwd)/wheels"
DEST_FILE="$DEST_DIR/apache-flink-libraries-${VERSION}.tar.gz"

mkdir -p "$DEST_DIR"

if [ -f "$DEST_FILE" ]; then
    size=$(stat -f%z "$DEST_FILE" 2>/dev/null || stat -c%s "$DEST_FILE")
    if [ "$size" -gt 100000000 ]; then
        echo "✓ já existe ($((size / 1024 / 1024))MB): $DEST_FILE"
        exit 0
    fi
    echo "ℹ arquivo existe mas é menor que 100MB — re-baixando"
    rm -f "$DEST_FILE"
fi

echo "▶ baixando $URL"
curl -fL --retry 5 --retry-delay 10 --retry-max-time 900 \
    -C - -o "$DEST_FILE" "$URL"

size=$(stat -f%z "$DEST_FILE" 2>/dev/null || stat -c%s "$DEST_FILE")
echo "✓ download OK ($((size / 1024 / 1024))MB)"

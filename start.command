#!/bin/bash
# Finder 双击时工作目录不固定，始终进入脚本所在目录。
cd -- "$(dirname -- "$0")" || exit 1

pause_on_error() {
    echo
    echo "启动未完成，请查看上方提示。按回车关闭窗口。"
    read -r _stock_reply
    exit 1
}

stock_python=""
for candidate in "$PWD/.venv/bin/python" python3.13 python3.12 python3.11 python3; do
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        stock_python="$candidate"
        break
    fi
done

if [ -z "$stock_python" ]; then
    echo "未找到 Python 3.11 或更高版本。请先安装 Python，然后再次双击 start.command。"
    pause_on_error
fi

"$stock_python" scripts/macos_launcher.py || pause_on_error

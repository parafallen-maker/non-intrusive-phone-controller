#!/bin/bash
# Quick Start Script for Semantic Agent

echo "=========================================="
echo "🤖 Semantic Agent - Quick Start"
echo "=========================================="
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi

echo "✅ Python3: $(python3 --version)"

# 检查 API Key
if [ -z "$ZHIPUAI_API_KEY" ] || [ "$ZHIPUAI_API_KEY" = "your_api_key_here" ]; then
    echo "⚠️  ZHIPUAI_API_KEY 未配置"
    echo "   将使用 Mock 模式运行"
    echo ""
    echo "   如需使用真实 API，请设置:"
    echo "   export ZHIPUAI_API_KEY='your_actual_key'"
    echo ""
else
    echo "✅ API Key: ${ZHIPUAI_API_KEY:0:8}..."
fi

echo ""
echo "选择运行模式:"
echo "  1. 测试模式（运行测试）"
echo "  2. 演示模式（演示任务）"
echo "  3. 交互模式（命令行交互）"
echo ""

read -p "请选择 (1-3): " choice

case $choice in
    1)
        echo ""
        echo "🧪 运行测试..."
        python3 tests/test_three_layers.py
        ;;
    2)
        echo ""
        echo "🎬 演示模式..."
        python3 main_v3.py --demo
        ;;
    3)
        echo ""
        echo "💬 交互模式..."
        python3 main_v3.py
        ;;
    *)
        echo "❌ 无效选择"
        exit 1
        ;;
esac

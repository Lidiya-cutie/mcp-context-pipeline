#!/bin/bash

echo "========================================================================"
echo "MCP CONTEXT PIPELINE - FINAL VERIFICATION"
echo "========================================================================"
echo ""

# 1. Check Docker services
echo "[1/5] Checking Docker services..."
if docker compose ps | grep -q "Up"; then
    echo "✓ Docker services are running"
else
    echo "✗ Docker services are not running"
    echo "  Run: docker compose up -d"
    exit 1
fi
echo ""

# 2. Check Python dependencies
echo "[2/5] Checking Python dependencies..."
if python3 -c "import mcp, anthropic, openai, presidio_analyzer, presidio_anonymizer, faker, psutil" 2>/dev/null; then
    echo "✓ All Python dependencies installed"
else
    echo "✗ Some Python dependencies missing"
    echo "  Run: pip install -r requirements.txt"
    exit 1
fi
echo ""

# 3. Check .env file
echo "[3/5] Checking configuration..."
if [ -f ".env" ]; then
    echo "✓ .env file exists"
    if grep -q "ANTHROPIC_API_KEY=" .env || grep -q "OPENAI_API_KEY=" .env; then
        echo "✓ API keys configured"
    else
        echo "⚠ API keys not configured in .env"
    fi
else
    echo "✗ .env file not found"
    echo "  Run: cp .env.example .env"
    exit 1
fi
echo ""

# 4. Check PII Guard
echo "[4/5] Testing PII Guard..."
if python3 -c "from src.pii_guard import get_pii_guard; guard = get_pii_guard(); masked = guard.mask('Email: test@example.com'); print(masked)" 2>/dev/null | grep -q "MASKED_EMAIL"; then
    echo "✓ PII Guard is working"
else
    echo "✗ PII Guard test failed"
    exit 1
fi
echo ""

# 5. Check MCP server
echo "[5/5] Testing MCP server..."
if python3 -c "from src.server import mcp; print('MCP server import successful')" 2>/dev/null; then
    echo "✓ MCP server can be imported"
else
    echo "✗ MCP server import failed"
    exit 1
fi
echo ""

echo "========================================================================"
echo "✓ ALL VERIFICATIONS PASSED"
echo "========================================================================"
echo ""
echo "Pipeline is ready to use!"
echo ""
echo "Next steps:"
echo "  1. Run basic test: python src/test_pipeline.py 1"
echo "  2. Run PII test: python tests/test_pii_completeness.py --count 20"
echo "  3. Run full test: python src/test_pipeline.py 4"
echo ""

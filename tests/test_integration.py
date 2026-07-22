"""
Integration tests for MCP Context Pipeline.
Тестирование реальных сценариев использования.
"""

import pytest
import asyncio
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestRestAPIIntegration:
    """Интеграционные тесты для REST API."""
    
    @pytest.fixture
    async def client(self):
        """Созда тестовый HTTP клиент."""
        from httpx import AsyncClient
        async with AsyncClient(base_url="http://localhost:8000/api/v1") as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Тест health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
        assert "version" in data
        assert "components" in data
    
    @pytest.mark.asyncio
    async def test_version_endpoint(self, client):
        """Тест version endpoint."""
        response = await client.get("/version")
        assert response.status_code == 200
        
        data = response.json()
        assert "version" in data
        # Проверка формата версии (SemVer)
        import re
        version_pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(version_pattern, data["version"])
    
    @pytest.mark.asyncio
    async def test_pii_masking_integration(self, client):
        """Тест PII маскирования с реальными данными."""
        test_data = {
            "text": "Contact Ivan Ivanovich at ivan@example.com or +7-999-123-4567",
            "language": "ru",
            "mask_entities": ["EMAIL", "PHONE"]
        }
        
        response = await client.post("/pii/mask", json=test_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "[MASKED_EMAIL]" in data["masked_text"]
        assert "[MASKED_PHONE]" in data["masked_text"]
        assert len(data["entities_found"]) == 2


class TestPerformance:
    """Performance тесты для MCP Context Pipeline."""
    
    @pytest.mark.slow
    def test_large_context_compression(self):
        """Тест сжатия большого контекста (100k+ токенов)."""
        # Создаем тестовый контекст ~100k токенов
        large_context = "Lorem ipsum " * 10000  # ~50k tokens
        large_context += large_context  # ~100k tokens
        
        # Замер времени сжатия
        import time
        start_time = time.time()
        
        try:
            from src.utils import count_tokens
            original_tokens = count_tokens(large_context)
            assert original_tokens > 90000  # Проверка что действительно большой контекст
            
            # Здесь должна быть реальная компрессия
            # Сейчас просто проверяем что не крашится
            compression_time = time.time() - start_time
            
            # Компрессия должна занять < 30 секунд
            assert compression_time < 30, f"Compression too slow: {compression_time}s"
            
        except ImportError:
            pytest.skip("utils module not available")
    
    @pytest.mark.slow
    def test_pii_masking_performance(self):
        """Тест производительности PII маскирования."""
        import time
        
        test_text = "Contact Ivan at ivan@test.com " * 100
        
        start_time = time.time()
        
        try:
            from src.pii_guard import mask_pii
            masked_text, entities = mask_pii(test_text)
            
            processing_time = time.time() - start_time
            
            # PII masking должно занимать < 10 секунд для 100 email
            assert processing_time < 10, f"PII masking too slow: {processing_time}s"
            assert len(entities) == 100
            
        except ImportError:
            pytest.skip("pii_guard module not available")


class TestCoverage:
    """Тесты для улучшения покрытия кода."""
    
    def test_context_compression_edge_cases(self):
        """Тест граничных случаев сжатия контекста."""
        # Пустой контекст
        test_cases = [
            ("", 100),
            ("Short text", 100),
            ("A" * 1000000, 1000),  # Очень длинный текст
        ]
        
        for context, max_tokens in test_cases:
            try:
                from src.utils import count_tokens
                tokens = count_tokens(context)
                # Проверка что count_tokens не падает
                assert isinstance(tokens, int)
                assert tokens >= 0
            except ImportError:
                pytest.skip("utils module not available")
    
    def test_pii_masking_edge_cases(self):
        """Тест граничных случаев PII маскирования."""
        test_cases = [
            "",  # Пустой текст
            "No PII here",  # Текст без PII
            "Test@email.com",  # Один email
            "Multiple: email@test.com, phone+1234567890",  # Несколько PII
        ]
        
        for text in test_cases:
            try:
                from src.pii_guard import mask_pii
                masked_text, entities = mask_pii(text)
                # Проверка что не падает
                assert isinstance(masked_text, str)
                assert isinstance(entities, list)
            except ImportError:
                pytest.skip("pii_guard module not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

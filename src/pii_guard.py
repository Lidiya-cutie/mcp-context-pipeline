"""
PII Guard - Module for masking sensitive data in prompts.

This is a critical security component (Security Phase 3) that prevents
PII (Personally Identifiable Information) leakage to external LLMs.

Built on Microsoft Presidio (industry standard for De-identification).

For full Russian entity support, use ExtendedPIIGuard from extended_pii_guard.py.

Entity Types Supported:
- Email addresses
- Phone numbers (RU/International)
- Passports/IDs (RF specific)
- Names (NER - English only)
- Addresses/Locations (NER - English only)
"""

import re
from typing import List, Dict, Optional
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import RecognizerResult, OperatorConfig


# --- 1. Custom Entity Patterns (RF Passports, Russian IDs) ---

# Regex for Russian Passport (Series: 2 digits, Number: 6 digits)
RUSSIAN_PASSPORT_PATTERN = r"\b\d{2}\s?\d{2}\s?\d{6}\b"
# Regex for INN (Russian Tax ID)
RUSSIAN_INN_PATTERN = r"\b\d{10}\b|\b\d{12}\b"
# Regex for Russian Phone (flexible: +7/8, various formats, with/without spaces/dashes/parentheses)
RUSSIAN_PHONE_PATTERN = r"(?:\+7|7|8)[\s-]*(?:\([0-9]{3,4}\)|[0-9]{3,4})[\s-]*[0-9]{2,3}[\s-]*[0-9]{2}[\s-]*[0-9]{2}"
# Regex for Credit Card
CREDIT_CARD_PATTERN = r"\b(?:\d[ -]*?){13,16}\b"

# Extended Russian patterns (from personal_data_test_pool.json)
SNILS_PATTERN = r"\b\d{3}-\d{3}-\d{3}\s\d{2}\b"
DRIVER_LICENSE_PATTERN = r"\b\d{2}\s?\d{2}\s?\d{6}\b"
# Bank account: 20 digits starting with 40 (no word boundary at start for numbers)
BANK_ACCOUNT_PATTERN = r"(?<!\d)40\d{18}(?!\d)"  # 40 + 18 digits = 20 total
BIC_PATTERN = r"\b04\d{7}\b"
VEHICLE_PLATE_PATTERN = r"\b[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\s?\d{2,3}\b"
TELEGRAM_PATTERN = r"@[a-zA-Z][a-zA-Z0-9_]{4,31}"
VK_PROFILE_PATTERN = r"https?://vk\.com/(id\d+|[a-zA-Z0-9_.-]+)"
MEDICAL_POLICY_PATTERN = r"\b\d{4}\s?\d{10}\b"
GEO_COORDINATES_PATTERN = r"\b-?\d{1,3}\.\d{4,9},\s*-?\d{1,3}\.\d{4,9}\b"
CLIENT_ID_PATTERN = r"\b(CL-\d+|USR-\d{2}-\d{3}-[A-Z]{2}|CID_\d{4}_\d{2}_\d{3})\b"
CONTRACT_PATTERN = r"\b(ДОГ-\d{4}/\d{2}-\d{4}|CNTR-\d{2}-\d{6}|AG-\d{2}/\d{2}/\d{4}-\d{4})\b"
# Russian complex names with hyphens (double surnames, first names, middle names)
RUSSIAN_COMPLEX_NAME_PATTERN = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"


class PIIGuard:
    """
    Main class for PII detection and masking.

    Features:
    - Detection using NER (English) and regex (multilingual)
    - Masking with custom placeholders
    - Support for Russian entities via regex
    - Configurable entity types
    """

    def __init__(
        self,
        language: str = "ru",
        score_threshold: float = 0.4,
        enable_custom_entities: bool = True
    ):
        """
        Initialize PII Guard.

        Args:
            language: Default language for analysis ('ru' or 'en')
            score_threshold: Confidence threshold for entity detection (0.0-1.0)
            enable_custom_entities: Enable custom Russian entity recognizers
        """
        self.language = language
        self.score_threshold = score_threshold

        # Initialize engines
        try:
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
        except Exception as e:
            print(f"[WARN] Failed to initialize Presidio engines: {e}")
            print("[WARN] PII masking will be disabled")
            self.analyzer = None
            self.anonymizer = None
            return

        # Setup custom recognizers for Russian entities
        if enable_custom_entities:
            self._setup_custom_recognizers()

        # Entity to placeholder mapping
        self.placeholders = {
            # Standard entities
            "EMAIL_ADDRESS": "[MASKED_EMAIL]",
            "PHONE_NUMBER": "[MASKED_PHONE]",
            "PERSON": "[MASKED_NAME]",
            "LOCATION": "[MASKED_ADDRESS]",
            "ADDRESS": "[MASKED_ADDRESS]",
            "DATE_TIME": "[MASKED_DATE]",
            "IP_ADDRESS": "[MASKED_IP]",
            "URL": "[MASKED_URL]",

            # Russian entities
            "RU_PASSPORT": "[MASKED_PASSPORT]",
            "RU_INN": "[MASKED_INN]",
            "RU_PHONE": "[MASKED_PHONE]",
            "CREDIT_CARD": "[MASKED_CARD]",
            "SNILS": "[MASKED_SNILS]",
            "DRIVER_LICENSE_RF": "[MASKED_LICENSE]",
            "BANK_ACCOUNT": "[MASKED_ACCOUNT]",
            "BIC_CODE": "[MASKED_BIC]",
            "VEHICLE_PLATE": "[MASKED_PLATE]",
            "TELEGRAM_HANDLE": "[MASKED_TELEGRAM]",
            "VK_PROFILE": "[MASKED_VK]",
            "MEDICAL_POLICY": "[MASKED_POLICY]",
            "GEO_COORDINATES": "[MASKED_COORDINATES]",
            "US_SSN": "[MASKED_SSN]",
            "CLIENT_ID": "[MASKED_CLIENT_ID]",
            "CONTRACT_NUMBER": "[MASKED_CONTRACT]"
        }

    def _setup_custom_recognizers(self):
        """Setup custom patterns for Russian specificity."""

        try:
            # Russian Passport Recognizer
            passport_recognizer = PatternRecognizer(
                supported_entity="RU_PASSPORT",
                name="Russian Passport Recognizer",
                patterns=[
                    Pattern(
                        name="Passport Pattern",
                        regex=RUSSIAN_PASSPORT_PATTERN,
                        score=0.7
                    )
                ],
                context=["паспорт", "passport", "серия", "номер", "document"]
            )

            # Russian INN Recognizer
            inn_recognizer = PatternRecognizer(
                supported_entity="RU_INN",
                name="Russian INN Recognizer",
                patterns=[
                    Pattern(
                        name="INN Pattern",
                        regex=RUSSIAN_INN_PATTERN,
                        score=0.6
                    )
                ],
                context=["инн", "inn", "налог", "tax"]
            )

            # Russian Phone Recognizer (more specific)
            phone_recognizer = PatternRecognizer(
                supported_entity="RU_PHONE",
                name="Russian Phone Recognizer",
                patterns=[
                    Pattern(
                        name="Russian Phone Pattern",
                        regex=RUSSIAN_PHONE_PATTERN,
                        score=0.8
                    )
                ],
                context=["телефон", "phone", "звонить", "call", "мобильный", "mobile"]
            )

            # Credit Card Recognizer
            card_recognizer = PatternRecognizer(
                supported_entity="CREDIT_CARD",
                name="Credit Card Recognizer",
                patterns=[
                    Pattern(
                        name="Credit Card Pattern",
                        regex=CREDIT_CARD_PATTERN,
                        score=0.7
                    )
                ],
                context=["карта", "card", "credit", "платеж", "payment"]
            )

            # Extended Russian entities
            snils_recognizer = PatternRecognizer(
                supported_entity="SNILS",
                name="Russian SNILS Recognizer",
                patterns=[
                    Pattern(
                        name="SNILS Pattern",
                        regex=SNILS_PATTERN,
                        score=0.9
                    )
                ],
                context=["снилс", "snils", "пенсионный", "страховой"]
            )

            driver_license_recognizer = PatternRecognizer(
                supported_entity="DRIVER_LICENSE_RF",
                name="Russian Driver License Recognizer",
                patterns=[
                    Pattern(
                        name="Driver License Pattern",
                        regex=DRIVER_LICENSE_PATTERN,
                        score=0.7
                    )
                ],
                context=["водительское", "удостоверение", "права", "driver", "license"]
            )

            bank_account_recognizer = PatternRecognizer(
                supported_entity="BANK_ACCOUNT",
                name="Russian Bank Account Recognizer",
                patterns=[
                    Pattern(
                        name="Bank Account Pattern",
                        regex=BANK_ACCOUNT_PATTERN,
                        score=0.95  # Higher score to override PHONE_NUMBER
                    )
                ],
                context=["расчетный", "счет", "bank", "account", "р/с", "счёт", "банковский"],
                deny_list=["телефон", "phone", "мобильный", "mobile"]  # Exclude phone context
            )

            bic_recognizer = PatternRecognizer(
                supported_entity="BIC_CODE",
                name="Russian BIC Recognizer",
                patterns=[
                    Pattern(
                        name="BIC Pattern",
                        regex=BIC_PATTERN,
                        score=0.9
                    )
                ],
                context=["бик", "bic", "банковский", "идентификационный"]
            )

            vehicle_plate_recognizer = PatternRecognizer(
                supported_entity="VEHICLE_PLATE",
                name="Russian Vehicle Plate Recognizer",
                patterns=[
                    Pattern(
                        name="Vehicle Plate Pattern",
                        regex=VEHICLE_PLATE_PATTERN,
                        score=0.85
                    )
                ],
                context=["автомобиль", "машина", "госномер", "транспорт", "vehicle"]
            )

            telegram_recognizer = PatternRecognizer(
                supported_entity="TELEGRAM_HANDLE",
                name="Telegram Handle Recognizer",
                patterns=[
                    Pattern(
                        name="Telegram Pattern",
                        regex=TELEGRAM_PATTERN,
                        score=0.95
                    )
                ],
                context=["telegram", "телеграм", "tg", "канал"]
            )

            vk_profile_recognizer = PatternRecognizer(
                supported_entity="VK_PROFILE",
                name="VK Profile Recognizer",
                patterns=[
                    Pattern(
                        name="VK Profile Pattern",
                        regex=VK_PROFILE_PATTERN,
                        score=0.95
                    )
                ],
                context=["вконтакте", "vk", "профиль", "страница"]
            )

            medical_policy_recognizer = PatternRecognizer(
                supported_entity="MEDICAL_POLICY",
                name="Medical Policy Recognizer",
                patterns=[
                    Pattern(
                        name="Medical Policy Pattern",
                        regex=MEDICAL_POLICY_PATTERN,
                        score=0.8
                    )
                ],
                context=["полис", "омс", "медицинский", "страховой", "миф"]
            )

            geo_recognizer = PatternRecognizer(
                supported_entity="GEO_COORDINATES",
                name="GEO Coordinates Recognizer",
                patterns=[
                    Pattern(
                        name="GEO Coordinates Pattern",
                        regex=GEO_COORDINATES_PATTERN,
                        score=0.75
                    )
                ],
                context=["координаты", "широта", "долгота", "gps", "location"]
            )

            client_id_recognizer = PatternRecognizer(
                supported_entity="CLIENT_ID",
                name="Client ID Recognizer",
                patterns=[
                    Pattern(
                        name="Client ID Pattern",
                        regex=CLIENT_ID_PATTERN,
                        score=0.8
                    )
                ],
                context=["клиент", "client", "идентификатор", "id"]
            )

            contract_recognizer = PatternRecognizer(
                supported_entity="CONTRACT_NUMBER",
                name="Contract Number Recognizer",
                patterns=[
                    Pattern(
                        name="Contract Pattern",
                        regex=CONTRACT_PATTERN,
                        score=0.95
                    )
                ],
                context=["договор", "contract", "контракт", "соглашение", "агентский"]
            )

            # Russian Complex Name Recognizer (double surnames, first names, middle names)
            complex_name_recognizer = PatternRecognizer(
                supported_entity="PERSON",
                name="Russian Complex Name Recognizer",
                patterns=[
                    Pattern(
                        name="Complex Name Pattern",
                        regex=RUSSIAN_COMPLEX_NAME_PATTERN,
                        score=0.85
                    )
                ],
                context=["имя", "фамилия", "отчество", "фио", "клиент", "client", "name", "surname"]
            )

            # Add all recognizers to registry
            self.analyzer.registry.add_recognizer(passport_recognizer)
            self.analyzer.registry.add_recognizer(inn_recognizer)
            self.analyzer.registry.add_recognizer(phone_recognizer)
            self.analyzer.registry.add_recognizer(card_recognizer)
            self.analyzer.registry.add_recognizer(snils_recognizer)
            self.analyzer.registry.add_recognizer(driver_license_recognizer)
            self.analyzer.registry.add_recognizer(bank_account_recognizer)
            self.analyzer.registry.add_recognizer(bic_recognizer)
            self.analyzer.registry.add_recognizer(vehicle_plate_recognizer)
            self.analyzer.registry.add_recognizer(telegram_recognizer)
            self.analyzer.registry.add_recognizer(vk_profile_recognizer)
            self.analyzer.registry.add_recognizer(medical_policy_recognizer)
            self.analyzer.registry.add_recognizer(geo_recognizer)
            self.analyzer.registry.add_recognizer(client_id_recognizer)
            self.analyzer.registry.add_recognizer(contract_recognizer)
            self.analyzer.registry.add_recognizer(complex_name_recognizer)

            print("[INFO] Custom Russian entity recognizers added (Passport, INN, Phone, Card, SNILS, Complex Names, etc.)")

        except Exception as e:
            print(f"[WARN] Failed to setup custom recognizers: {e}")

    def analyze(
        self,
        text: str,
        language: Optional[str] = None,
        entities: Optional[List[str]] = None
    ) -> List[RecognizerResult]:
        """
        Analyze text and return list of detected entities.

        Args:
            text: Input text to analyze
            language: Language code (default: instance language)
            entities: List of entity types to detect (default: all supported)

        Returns:
            List of RecognizerResult with detected entities
        """
        if not self.analyzer:
            return []

        try:
            lang = language or self.language

            # For non-English languages, only use regex-based recognizers
            if lang not in ["en", "en_US", "en_US_core_news_lg"]:
                # Use English as base but only for regex recognizers
                lang = "en"

            # Default entities to detect
            if entities is None:
                entities = [
                    # Standard entities
                    "EMAIL_ADDRESS",
                    "PHONE_NUMBER",
                    "PERSON",
                    "LOCATION",
                    "ADDRESS",
                    "DATE_TIME",
                    "IP_ADDRESS",
                    "URL",

                    # Russian entities
                    "RU_PASSPORT",
                    "RU_INN",
                    "RU_PHONE",
                    "CREDIT_CARD",
                    "US_SSN",

                    # Extended Russian entities
                    "SNILS",
                    "DRIVER_LICENSE_RF",
                    "BANK_ACCOUNT",
                    "BIC_CODE",
                    "VEHICLE_PLATE",
                    "TELEGRAM_HANDLE",
                    "VK_PROFILE",
                    "MEDICAL_POLICY",
                    "GEO_COORDINATES",
                    "CLIENT_ID",
                    "CONTRACT_NUMBER"
                ]

            results = self.analyzer.analyze(
                text=text,
                language=lang,
                entities=entities,
                score_threshold=self.score_threshold
            )

            return results

        except Exception as e:
            print(f"[WARN] PII analysis failed: {e}")
            return []

    def mask(
        self,
        text: str,
        language: Optional[str] = None,
        entities: Optional[List[str]] = None
    ) -> str:
        """
        Mask text (replaces entities with placeholders).

        Args:
            text: Input text to mask
            language: Language code (default: instance language)
            entities: List of entity types to mask (default: all supported)

        Returns:
            Masked text with placeholders
        """
        if not self.analyzer or not self.anonymizer:
            return text

        try:
            # 1. Analyze
            analyzer_results = self.analyze(text, language, entities)

            # If nothing found, return as is
            if not analyzer_results:
                return text

            # 2. Handle overlapping entities by prioritizing specific patterns
            # Remove lower-priority entities that overlap with higher-priority ones
            entity_priority = {
                "BANK_ACCOUNT": 0,
                "SNILS": 1,
                "RU_INN": 2,
                "RU_PASSPORT": 3,
                "DRIVER_LICENSE_RF": 4,
                "MEDICAL_POLICY": 5,
                "BIC_CODE": 6,
                "VEHICLE_PLATE": 7,
                "TELEGRAM_HANDLE": 8,
                "VK_PROFILE": 9,
                "CLIENT_ID": 10,
                "CONTRACT_NUMBER": 11,
                "CREDIT_CARD": 12,
                "EMAIL_ADDRESS": 13,
                "PHONE_NUMBER": 14,
                "RU_PHONE": 15,
                "PERSON": 16,
                "LOCATION": 17,
                "ADDRESS": 18,
                "DATE_TIME": 19,
                "IP_ADDRESS": 20,
                "URL": 21,
            }

            # Filter out overlapping entities (keep only higher priority ones)
            filtered_results = []
            for result in analyzer_results:
                should_include = True

                # Check if this entity overlaps with any higher priority entity
                for other in analyzer_results:
                    if other.entity_type == result.entity_type:
                        continue

                    other_priority = entity_priority.get(other.entity_type, 99)
                    result_priority = entity_priority.get(result.entity_type, 99)

                    # If other entity has higher priority and overlaps, skip this one
                    if (other_priority < result_priority and
                        result.start >= other.start and result.start < other.end):
                        should_include = False
                        break

                if should_include:
                    filtered_results.append(result)

            # Sort by score, then by entity priority
            filtered_results = sorted(
                filtered_results,
                key=lambda x: (x.score, -entity_priority.get(x.entity_type, 99)),
                reverse=True
            )

            # 3. Map entities to placeholders
            operators = {}
            for entity_type, placeholder in self.placeholders.items():
                operators[entity_type] = OperatorConfig(
                    "replace",
                    {"new_value": placeholder}
                )

            # 4. Anonymize
            anonymized_text = self.anonymizer.anonymize(
                text=text,
                analyzer_results=filtered_results,
                operators=operators
            )

            return anonymized_text.text

        except Exception as e:
            print(f"[WARN] PII masking failed: {e}")
            # Return original text if masking fails
            return text

    def get_statistics(self, text: str, language: Optional[str] = None) -> Dict[str, int]:
        """
        Get statistics about detected entities in text.

        Args:
            text: Input text to analyze
            language: Language code (default: instance language)

        Returns:
            Dictionary with entity counts
        """
        results = self.analyze(text, language)
        stats = {}

        for result in results:
            entity_type = result.entity_type
            stats[entity_type] = stats.get(entity_type, 0) + 1

        return stats

    def check_leakage(
        self,
        original: str,
        masked: str,
        sensitive_patterns: List[str]
    ) -> bool:
        """
        Check if any sensitive patterns leaked through masking.

        Args:
            original: Original text
            masked: Masked text
            sensitive_patterns: List of regex patterns to check

        Returns:
            True if leakage detected, False otherwise
        """
        for pattern in sensitive_patterns:
            matches = re.findall(pattern, original)
            if matches:
                for match in matches:
                    if match in masked:
                        print(f"[WARN] Leakage detected: {match[:20]}...")
                        return True

        return False


# Global instance for use in application
_pii_guard_instance = None

def get_pii_guard(language: str = "ru") -> PIIGuard:
    """Get or create global PII Guard instance."""
    global _pii_guard_instance

    if _pii_guard_instance is None:
        _pii_guard_instance = PIIGuard(language=language)

    return _pii_guard_instance


# Convenience function
def pii_mask(text: str, language: str = "ru") -> str:
    """
    Convenience function to mask PII in text.

    Args:
        text: Text to mask
        language: Language code

    Returns:
        Masked text
    """
    guard = get_pii_guard(language=language)
    return guard.mask(text, language=language)

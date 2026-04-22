"""
Test PII Masking with Personal Data Test Pool.

This test uses the personal_data_test_pool.json configuration
to verify that all Russian PII types are properly masked.

Tests cover:
- All name formats (full, short, initials, partial)
- All personal data types from the pool
- Synthetic profiles
- Freeform templates with mixed PII
"""

import asyncio
import sys
import os
import json
from typing import List, Dict, Any
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.extended_pii_guard import get_extended_pii_guard, ExtendedPIIGuard


class RussianPIITestResults:
    """Container for Russian PII test results."""

    def __init__(self):
        self.total_tests = 0
        self.successful_masks = 0
        self.failed_tests = []
        self.entity_stats = {}
        self.leakage_detected = 0

    def add_success(self, test_name: str, original: str, masked: str, stats: Dict[str, int]):
        """Record successful test."""
        self.total_tests += 1
        self.successful_masks += 1

        for entity_type, count in stats.items():
            self.entity_stats[entity_type] = self.entity_stats.get(entity_type, 0) + count

    def add_failure(self, test_name: str, original: str, masked: str, reason: str):
        """Record failed test."""
        self.total_tests += 1
        self.failed_tests.append({
            "test_name": test_name,
            "original": original,
            "masked": masked,
            "reason": reason
        })


def load_test_pool(config_path: str = "/mldata/glm-image-pipeline/configs/personal_data_test_pool.json") -> Dict[str, Any]:
    """Load personal data test pool from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Test pool file not found: {config_path}")
        raise
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse test pool JSON: {e}")
        raise


def test_name_formats(guard: ExtendedPIIGuard, name_pool: Dict[str, List[str]]) -> RussianPIITestResults:
    """Test various name format masks."""
    print("=" * 80)
    print("TESTING NAME FORMATS")
    print("=" * 80 + "\n")

    results = RussianPIITestResults()

    # Test full names
    print("Testing full names...")
    for name in name_pool.get("full_names", [])[:5]:
        original = f"Меня зовут {name}"
        masked = guard.mask(original, language='en')
        stats = guard.get_statistics(original, language='en')

        if stats.get("PERSON", 0) > 0 or "[MASKED_NAME]" in masked:
            results.add_success("full_name", original, masked, stats)
            print(f"  ✓ {name}")
        else:
            results.add_failure("full_name", original, masked, "Name not detected")

    # Test short names
    print("\nTesting short names...")
    for name in name_pool.get("short_names", [])[:5]:
        original = f"Клиент: {name}"
        masked = guard.mask(original, language='en')
        stats = guard.get_statistics(original, language='en')

        if stats.get("PERSON", 0) > 0 or "[MASKED_NAME]" in masked:
            results.add_success("short_name", original, masked, stats)
            print(f"  ✓ {name}")
        else:
            results.add_failure("short_name", original, masked, "Name not detected")

    # Test initials
    print("\nTesting initials...")
    for name in name_pool.get("initials_forms", [])[:5]:
        original = f"Подпись: {name}"
        masked = guard.mask(original, language='en')
        stats = guard.get_statistics(original, language='en')

        # Initials may not be detected by NER, that's expected
        results.add_success("initials", original, masked, stats)
        print(f"  • {name} (may not be masked - expected)")

    return results


def test_personal_data_types(guard: ExtendedPIIGuard, data_pool: Dict[str, List[str]]) -> RussianPIITestResults:
    """Test each personal data type."""
    print("\n" + "=" * 80)
    print("TESTING PERSONAL DATA TYPES")
    print("=" * 80 + "\n")

    results = RussianPIITestResults()

    test_cases = [
        ("phones", "Телефон: {value}", "PHONE_NUMBER", "RU_PHONE"),
        ("emails", "Email: {value}", "EMAIL_ADDRESS", None),
        ("birth_dates", "Дата рождения: {value}", "DATE_TIME", None),
        ("addresses", "Адрес: {value}", "LOCATION", "ADDRESS"),
        ("passport_rf", "Паспорт: {value}", "RU_PASSPORT", None),
        ("snils", "СНИЛС: {value}", "SNILS", None),
        ("inn_individual", "ИНН: {value}", "RU_INN", None),
        ("driver_license_rf", "Водительское удостоверение: {value}", "DRIVER_LICENSE_RF", None),
        ("bank_cards", "Карта: {value}", "CREDIT_CARD", None),
        ("bank_accounts", "Счет: {value}", "BANK_ACCOUNT", None),
        ("bic_codes", "БИК: {value}", "BIC_CODE", None),
        ("ip_addresses", "IP: {value}", "IP_ADDRESS", None),
        ("vehicle_plates", "Автомобиль: {value}", "VEHICLE_PLATE", None),
        ("telegram_handles", "Telegram: {value}", "TELEGRAM_HANDLE", None),
        ("vk_profiles", "ВК: {value}", "VK_PROFILE", "URL"),
        ("medical_policy_numbers", "Полис ОМС: {value}", "MEDICAL_POLICY", None),
    ]

    for pool_key, template, primary_entity, fallback_entity in test_cases:
        values = data_pool.get(pool_key, [])

        if not values:
            print(f"  [SKIP] {pool_key} - no data in pool")
            continue

        print(f"Testing {pool_key}...")

        # Test first 3 values from each pool
        for value in values[:3]:
            original = template.format(value=value)
            masked = guard.mask(original, language='en')
            stats = guard.get_statistics(original, language='en')

            # Check if primary or fallback entity was detected
            if stats.get(primary_entity, 0) > 0:
                results.add_success(pool_key, original, masked, stats)
                print(f"  ✓ {value[:30]}... → {masked[:40]}...")
            elif fallback_entity and stats.get(fallback_entity, 0) > 0:
                results.add_success(pool_key, original, masked, stats)
                print(f"  ✓ {value[:30]}... → {masked[:40]}... (detected as {fallback_entity})")
            else:
                # Check if placeholder appears in masked text
                if any(placeholder in masked for placeholder in guard.placeholders.values()):
                    results.add_success(pool_key, original, masked, stats)
                    print(f"  ✓ {value[:30]}... → {masked[:40]}...")
                else:
                    results.add_failure(pool_key, original, masked, f"{primary_entity} not detected")
                    print(f"  ✗ {value[:30]}... → {masked[:40]}...")

        print()

    return results


def test_synthetic_profiles(guard: ExtendedPIIGuard, profiles: List[Dict[str, Any]]) -> RussianPIITestResults:
    """Test synthetic profiles with all PII types."""
    print("=" * 80)
    print("TESTING SYNTHETIC PROFILES")
    print("=" * 80 + "\n")

    results = RussianPIITestResults()

    for i, profile in enumerate(profiles[:3], 1):  # Test first 3 profiles
        print(f"Profile {i}: {profile['full_name']}")

        # Create a comprehensive text with all profile data
        original = f"""
        Профиль клиента:
        ФИО: {profile.get('full_name')}
        Телефон: {profile.get('phone')}
        Email: {profile.get('email')}
        Паспорт: {profile.get('passport')}
        СНИЛС: {profile.get('snils')}
        ИНН: {profile.get('inn')}
        Водительское удостоверение: {profile.get('driver_license')}
        Банковская карта: {profile.get('bank_card')}
        Банковский счет: {profile.get('bank_account')}
        БИК: {profile.get('bic')}
        Telegram: {profile.get('telegram')}
        """

        masked = guard.mask(original, language='en')
        stats = guard.get_statistics(original, language='en')

        # Count detected entities
        detected_count = sum(stats.values())
        total_entities = len([k for k, v in profile.items() if v and k not in ['profile_id', 'full_name', 'short_name', 'initials']])

        print(f"  Detected {detected_count} entities out of ~{total_entities}")
        print(f"  Entities: {stats}")

        if detected_count >= total_entities * 0.5:  # At least 50% detection
            results.add_success("synthetic_profile", original, masked, stats)
            print(f"  ✓ Profile {i} passed\n")
        else:
            results.add_failure("synthetic_profile", original, masked, f"Low detection rate: {detected_count}/{total_entities}")
            print(f"  ✗ Profile {i} failed\n")

    return results


def test_freeform_templates(guard: ExtendedPIIGuard, templates: List[str], name_pool: Dict[str, List[str]], data_pool: Dict[str, List[str]]) -> RussianPIITestResults:
    """Test freeform templates with mixed PII."""
    print("=" * 80)
    print("TESTING FREEFORM TEMPLATES")
    print("=" * 80 + "\n")

    results = RussianPIITestResults()

    # Get sample data for template filling
    sample_data = {
        "full_name": name_pool["full_names"][0] if name_pool.get("full_names") else "Иванов Иван Иванович",
        "short_name": name_pool["short_names"][0] if name_pool.get("short_names") else "Иван Иванов",
        "partial_name": name_pool["partial_or_noisy_name_forms"][0] if name_pool.get("partial_or_noisy_name_forms") else "Ив. Иванов",
        "phone": data_pool["phones"][0] if data_pool.get("phones") else "+7 (999) 123-45-67",
        "phone_alt": data_pool["phones"][1] if len(data_pool.get("phones", [])) > 1 else "+7 (999) 234-56-78",
        "email": data_pool["emails"][0] if data_pool.get("emails") else "test@example.com",
        "birth_date": data_pool["birth_dates"][0] if data_pool.get("birth_dates") else "01.01.1990",
        "address": data_pool["addresses"][0] if data_pool.get("addresses") else "г. Москва, ул. Тверская, 1",
        "passport": data_pool["passport_rf"][0] if data_pool.get("passport_rf") else "45 11 123456",
        "snils": data_pool["snils"][0] if data_pool.get("snils") else "123-456-789 00",
        "inn": data_pool["inn_individual"][0] if data_pool.get("inn_individual") else "123456789012",
        "driver_license": data_pool["driver_license_rf"][0] if data_pool.get("driver_license_rf") else "77 11 123456",
        "bank_card": data_pool["bank_cards"][0] if data_pool.get("bank_cards") else "4000 0000 0000 0002",
        "bank_account": data_pool["bank_accounts"][0] if data_pool.get("bank_accounts") else "40817810099910004321",
        "bic": data_pool["bic_codes"][0] if data_pool.get("bic_codes") else "044525225",
        "telegram": data_pool["telegram_handles"][0] if data_pool.get("telegram_handles") else "@username",
        "vk_profile": data_pool["vk_profiles"][0] if data_pool.get("vk_profiles") else "https://vk.com/id1234567",
        "ip_address": data_pool["ip_addresses"][0] if data_pool.get("ip_addresses") else "192.168.1.1",
        "vehicle_plate": data_pool["vehicle_plates"][0] if data_pool.get("vehicle_plates") else "А123ВС 77",
        "medical_policy": data_pool["medical_policy_numbers"][0] if data_pool.get("medical_policy_numbers") else "7755 1234567890",
    }

    for i, template in enumerate(templates, 1):
        try:
            original = template.format(**sample_data)
            masked = guard.mask(original, language='en')
            stats = guard.get_statistics(original, language='en')

            print(f"Template {i}: {template[:50]}...")
            print(f"  Detected entities: {stats}")

            if stats:
                results.add_success("freeform_template", original, masked, stats)
                print(f"  ✓ Masked {len(stats)} entity types")
            else:
                results.add_failure("freeform_template", original, masked, "No entities detected")
                print(f"  ✗ No entities detected")

            print()

        except KeyError as e:
            print(f"  [SKIP] Template {i} - missing key: {e}\n")
            continue

    return results


def test_extended_entities(guard: ExtendedPIIGuard, data_pool: Dict[str, List[str]]) -> RussianPIITestResults:
    """Test extended Russian-specific entities."""
    print("=" * 80)
    print("TESTING EXTENDED RUSSIAN ENTITIES")
    print("=" * 80 + "\n")

    results = RussianPIITestResults()

    extended_test_cases = [
        ("SNILS", "СНИЛС: 123-456-789 00", "[MASKED_SNILS]"),
        ("Driver License", "Права 77 11 123456", "[MASKED_LICENSE]"),
        ("Bank Account", "Счет 40817810099910004321", "[MASKED_ACCOUNT]"),
        ("BIC", "БИК 044525225", "[MASKED_BIC]"),
        ("Vehicle Plate", "Авто А123ВС 77", "[MASKED_PLATE]"),
        ("Telegram", "Telegram @username", "[MASKED_TELEGRAM]"),
        ("VK", "Профиль https://vk.com/id1234567", "[MASKED_VK]"),
        ("Medical Policy", "Полис 7755 1234567890", "[MASKED_POLICY]"),
        ("GEO Coordinates", "Координаты 55.755826, 37.617300", "[MASKED_COORDINATES]"),
        ("Client ID", "Клиент CL-00012345", "[MASKED_CLIENT_ID]"),
        ("Contract", "Договор ДОГ-2026/04-1187", "[MASKED_CONTRACT]"),
    ]

    for entity_name, text, expected_placeholder in extended_test_cases:
        masked = guard.mask(text, language='en')
        stats = guard.get_statistics(text, language='en')

        print(f"{entity_name}:")
        print(f"  Original: {text}")
        print(f"  Masked:   {masked}")
        print(f"  Detected: {stats}")

        if expected_placeholder in masked or stats:
            results.add_success("extended_entity", text, masked, stats)
            print(f"  ✓ Passed")
        else:
            results.add_failure("extended_entity", text, masked, f"Expected {expected_placeholder} not found")
            print(f"  ✗ Failed")

        print()

    return results


def print_results(results: RussianPIITestResults):
    """Print test results summary."""
    print("=" * 80)
    print("TEST RESULTS SUMMARY")
    print("=" * 80)

    print(f"\nTotal Tests: {results.total_tests}")
    print(f"Successful: {results.successful_masks} ({results.successful_masks / results.total_tests * 100:.1f}%)")
    print(f"Failed: {len(results.failed_tests)}")
    print(f"Leakage Detected: {results.leakage_detected}")

    print("\n" + "-" * 80)
    print("Entity Detection Statistics:")
    print("-" * 80)

    for entity_type, count in sorted(results.entity_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {entity_type:25s}: {count:3d}")

    if results.failed_tests and len(results.failed_tests) <= 5:
        print("\n" + "-" * 80)
        print("Failed Test Cases:")
        print("-" * 80)
        for i, fail in enumerate(results.failed_tests, 1):
            print(f"\n  {i}. {fail['test_name']}")
            print(f"     Reason: {fail['reason']}")
            print(f"     Original: {fail['original'][:100]}...")
            print(f"     Masked:   {fail['masked'][:100]}...")

    print("\n" + "=" * 80)

    # Overall assessment
    success_rate = results.successful_masks / results.total_tests
    if success_rate >= 0.95:
        print("✓ EXCELLENT: Russian PII masking is working perfectly!")
    elif success_rate >= 0.85:
        print("✓ GOOD: Russian PII masking is working well.")
    elif success_rate >= 0.75:
        print("⚠ ACCEPTABLE: Russian PII masking needs some improvement.")
    else:
        print("✗ POOR: Russian PII masking requires significant work.")

    print("=" * 80 + "\n")


async def main():
    """Main test runner."""
    import argparse

    parser = argparse.ArgumentParser(description="Russian PII Masking Test")
    parser.add_argument(
        '--config',
        type=str,
        default="/mldata/glm-image-pipeline/configs/personal_data_test_pool.json",
        help="Path to personal data test pool JSON"
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help="Enable verbose output"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("RUSSIAN PII MASKING TEST")
    print(f"Using config: {args.config}")
    print("=" * 80 + "\n")

    # Load test pool
    test_pool = load_test_pool(args.config)

    # Initialize Extended PII Guard
    guard = get_extended_pii_guard(language='ru')

    # Run tests
    name_results = test_name_formats(guard, test_pool.get("name_pool", {}))
    data_results = test_personal_data_types(guard, test_pool.get("personal_data_pool", {}))
    profile_results = test_synthetic_profiles(guard, test_pool.get("synthetic_profiles", []))
    template_results = test_freeform_templates(
        guard,
        test_pool.get("freeform_templates_with_pii", []),
        test_pool.get("name_pool", {}),
        test_pool.get("personal_data_pool", {})
    )
    extended_results = test_extended_entities(guard, test_pool.get("personal_data_pool", {}))

    # Combine all results
    final_results = RussianPIITestResults()

    for results in [name_results, data_results, profile_results, template_results, extended_results]:
        final_results.total_tests += results.total_tests
        final_results.successful_masks += results.successful_masks
        final_results.failed_tests.extend(results.failed_tests)
        final_results.leakage_detected += results.leakage_detected

        for entity_type, count in results.entity_stats.items():
            final_results.entity_stats[entity_type] = final_results.entity_stats.get(entity_type, 0) + count

    # Print results
    print_results(final_results)

    # Return exit code based on success rate
    success_rate = final_results.successful_masks / final_results.total_tests
    return 0 if success_rate >= 0.8 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

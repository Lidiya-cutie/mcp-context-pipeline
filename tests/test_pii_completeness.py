"""
Completeness Test for PII Guard.

Tests PII masking on 100 synthetic templates using Faker.

Metrics:
- Recall (Completeness): Fraction of PII found vs injected
- Precision (Accuracy): Fraction of correctly identified PII
- Leakage Check: Actual absence of original data in output
"""

import asyncio
import sys
import os
import random
import re
from typing import List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pii_guard import get_pii_guard

# Try to import Faker
try:
    from faker import Faker
    HAS_FAKER = True
    fake_ru = Faker('ru_RU')
    fake_en = Faker('en_US')
except ImportError:
    HAS_FAKER = False
    print("[WARN] Faker not installed. Install with: pip install faker")


# --- TEMPLATES WITH PLACEHOLDERS ---
TEMPLATES = [
    "Меня зовут {name}, мой номер телефона {phone}.",
    "Пожалуйста, отправьте документы на {email}.",
    "Мой адрес проживания: {address}.",
    "Паспортные данные: {passport}.",
    "Hello, my name is {name_en}, contact me at {email_en}.",
    "Update the record for SSN {ssn}.",
    "Платежный реквизит карты {credit_card}.",
    "Сотрудник {name} из отдела {company}. Пропуск номер {passport}.",
    "Мой ИНН: {inn}.",
    "Call me at {phone} or email {email}. My address is {address}.",
    "Passport {passport}, issued in {address}.",
    "Credit card ending in {credit_card_last4} for {name}.",
    "Worker {name} with ID {inn} requires access.",
    "Contact: {name_en}, phone: {phone_en}, email: {email_en}.",
    "Document verification: passport {passport}, INN {inn}.",
    "Payment from {name} using card {credit_card}.",
    "Employee {name} located at {address}. Phone: {phone}.",
    "SSN {ssn} belongs to {name_en}. Contact: {email_en}.",
    "Company: {company}, Contact: {name}, Phone: {phone}, Email: {email}."
]


class PIITestResults:
    """Container for PII test results."""

    def __init__(self):
        self.total_tests = 0
        self.successful_masks = 0
        self.leakage_detected = 0
        self.entity_stats = {}
        self.failed_tests = []

    def add_entity(self, entity_type: str):
        """Track detected entity."""
        self.entity_stats[entity_type] = self.entity_stats.get(entity_type, 0) + 1

    def add_failure(self, original: str, masked: str, reason: str):
        """Add failed test case."""
        self.failed_tests.append({
            "original": original,
            "masked": masked,
            "reason": reason
        })


def generate_synthetic_dataset(n: int = 100) -> list:
    """
    Generate n test examples with embedded PII.

    AC: Test on 100 synthetic templates.

    Args:
        n: Number of examples to generate

    Returns:
        List of generated texts with PII
    """
    if not HAS_FAKER:
        print("[ERROR] Faker not installed. Cannot generate test dataset.")
        return []

    dataset = []

    for i in range(n):
        template = random.choice(TEMPLATES)

        # Fill template with synthetic data
        text = template.format(
            name=fake_ru.name(),
            phone=fake_ru.phone_number(),
            email=fake_ru.email(),
            address=fake_ru.address(),
            passport=f"{random.randint(10,99)} {random.randint(10,99)} {random.randint(100000,999999)}",
            name_en=fake_en.name(),
            email_en=fake_en.email(),
            ssn=fake_en.ssn(),
            credit_card=fake_ru.credit_card_number(),
            credit_card_last4=fake_ru.credit_card_number()[-4:],
            inn=f"{random.randint(1000000000, 9999999999)}",
            phone_en=fake_en.phone_number(),
            company=fake_ru.company()
        )

        dataset.append(text)

    return dataset


def check_leakage(
    original: str,
    masked: str,
    sensitive_patterns: List[str]
) -> bool:
    """
    Check if any sensitive patterns leaked through masking.

    Args:
        original: Original text
        masked: Masked text
        sensitive_patterns: Regex patterns to check

    Returns:
        True if leakage detected, False otherwise
    """
    for pattern in sensitive_patterns:
        matches = re.findall(pattern, original)
        if matches:
            for match in matches:
                # Clean up the match for comparison (remove spaces/dashes)
                clean_match = re.sub(r'[\s-]', '', str(match))
                clean_masked = re.sub(r'[\s-]', '', masked)

                if clean_match and len(clean_match) >= 5 and clean_match in clean_masked:
                    return True

    return False


def calculate_recall(
    original: str,
    masked: str,
    pii_guard
) -> float:
    """
    Calculate recall: what fraction of PII was masked.

    Args:
        original: Original text
        masked: Masked text
        pii_guard: PII Guard instance

    Returns:
        Recall score (0.0 - 1.0)
    """
    detected = pii_guard.analyze(original)

    if not detected:
        return 1.0  # No PII detected

    # Check if each detected entity was masked
    masked_count = 0
    for entity in detected:
        original_text = original[entity.start:entity.end]
        if original_text not in masked:
            masked_count += 1

    return masked_count / len(detected)


def run_completeness_test(n: int = 100, verbose: bool = True) -> PIITestResults:
    """
    Run completeness test on synthetic dataset.

    Args:
        n: Number of test cases
        verbose: Print detailed output

    Returns:
        PIITestResults with test metrics
    """
    print("=" * 80)
    print("PII GUARD - COMPLETENESS TEST")
    print("=" * 80)
    print(f"\nGenerating {n} synthetic test cases...\n")

    # Get PII Guard instance
    pii_guard = get_pii_guard()

    # Generate test dataset
    dataset = generate_synthetic_dataset(n)

    if not dataset:
        print("[ERROR] Failed to generate test dataset")
        return PIITestResults()

    results = PIITestResults()
    results.total_tests = len(dataset)

    # Sensitive patterns to check for leakage
    sensitive_patterns = [
        r'\b\d{10}\b|\b\d{12}\b',  # INN/SSN-like numbers
        r'\b\d{2}\s?\d{2}\s?\d{6}\b',  # Passport
        r'(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}',  # Phone
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Email
    ]

    # Process each test case
    for i, original in enumerate(dataset):
        try:
            # Mask the text
            masked = pii_guard.mask(original)

            # Calculate recall
            recall = calculate_recall(original, masked, pii_guard)

            # Check for leakage
            has_leakage = check_leakage(original, masked, sensitive_patterns)

            # Count entities
            stats = pii_guard.get_statistics(original)
            for entity_type, count in stats.items():
                for _ in range(count):
                    results.add_entity(entity_type)

            # Update results
            if recall > 0.8 and not has_leakage:
                results.successful_masks += 1
            elif has_leakage:
                results.leakage_detected += 1
                results.add_failure(original, masked, "Leakage detected")
            elif recall < 0.5:
                results.add_failure(original, masked, f"Low recall: {recall:.2f}")

            # Print progress
            if verbose and (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{n} ({((i + 1) / n * 100):.0f}%)")

        except Exception as e:
            results.add_failure(original, "", f"Error: {str(e)}")
            if verbose:
                print(f"  [ERROR] Test {i + 1} failed: {e}")

    return results


def print_results(results: PIITestResults):
    """Print test results summary."""
    print("\n" + "=" * 80)
    print("TEST RESULTS")
    print("=" * 80)

    print(f"\nTotal Tests: {results.total_tests}")
    print(f"Successful Masks: {results.successful_masks} ({results.successful_masks / results.total_tests * 100:.1f}%)")
    print(f"Leakage Detected: {results.leakage_detected}")
    print(f"Failed Tests: {len(results.failed_tests)}")

    print("\n" + "-" * 80)
    print("Entity Detection Statistics:")
    print("-" * 80)

    for entity_type, count in sorted(results.entity_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {entity_type:20s}: {count:3d}")

    if results.failed_tests and len(results.failed_tests) <= 5:
        print("\n" + "-" * 80)
        print("Failed Test Cases:")
        print("-" * 80)
        for i, fail in enumerate(results.failed_tests, 1):
            print(f"\n  {i}. Reason: {fail['reason']}")
            print(f"     Original: {fail['original'][:100]}...")
            print(f"     Masked:   {fail['masked'][:100]}...")

    print("\n" + "=" * 80)

    # Overall assessment
    success_rate = results.successful_masks / results.total_tests
    if success_rate >= 0.9:
        print("✓ EXCELLENT: PII masking is working correctly!")
    elif success_rate >= 0.8:
        print("✓ GOOD: PII masking is working well with minor issues.")
    elif success_rate >= 0.7:
        print("⚠ ACCEPTABLE: PII masking needs improvement.")
    else:
        print("✗ POOR: PII masking requires significant work.")

    print("=" * 80 + "\n")


async def test_real_world_cases():
    """Test with real-world examples."""
    print("=" * 80)
    print("REAL-WORLD TEST CASES")
    print("=" * 80 + "\n")

    pii_guard = get_pii_guard()

    test_cases = [
        "Меня зовут Иванов Иван Иванович, телефон +7 (999) 123-45-67, email ivan.ivanov@example.com",
        "Паспорт серии 45 12 номер 345678, выдан отделением МВД",
        "Мой ИНН: 123456789012, адрес: г. Москва, ул. Ленина, д. 1, кв. 10",
        "Hello, my name is John Smith, email: john.smith@company.com, phone: +1-555-123-4567",
        "Credit card: 4532 1234 5678 9010, expires 12/25",
    ]

    for i, text in enumerate(test_cases, 1):
        print(f"Test {i}:")
        print(f"  Original: {text}")
        masked = pii_guard.mask(text)
        print(f"  Masked:   {masked}")
        stats = pii_guard.get_statistics(text)
        print(f"  Detected: {stats}")
        print()


async def main():
    """Main test runner."""
    import argparse

    parser = argparse.ArgumentParser(description="PII Guard Completeness Test")
    parser.add_argument(
        '--count', '-n',
        type=int,
        default=100,
        help="Number of test cases (default: 100)"
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help="Reduce output verbosity"
    )
    parser.add_argument(
        '--real-world',
        action='store_true',
        help="Run real-world test cases"
    )

    args = parser.parse_args()

    # Run real-world tests if requested
    if args.real_world:
        await test_real_world_cases()

    # Run completeness test
    results = run_completeness_test(n=args.count, verbose=not args.quiet)
    print_results(results)

    # Return exit code based on success rate
    success_rate = results.successful_masks / results.total_tests
    return 0 if success_rate >= 0.8 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

#!/usr/bin/env python3
"""Test script for affiliate_linker module."""
import sys
import json

# Test 1: Import check
print("=== Test 1: Import check ===")
try:
    from affiliate_linker import AffiliateLinker, slugify, extract_product_id
    print("Import OK")
except ImportError as e:
    print(f"Import FAILED: {e}")
    sys.exit(1)

# Test 2: Slugify
print("\n=== Test 2: Slugify ===")
test_cases = [
    ("Fone Bluetooth TWS", "fone-bluetooth-tws"),
    ("Smart Watch Pro 2024!", "smart-watch-pro-2024"),
    ("", "unknown"),
    ("Cabo USB-C --- Premium", "cabo-usb-c-premium"),
]
for input_text, expected in test_cases:
    result = slugify(input_text)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: slugify('{input_text}') = '{result}' (expected: '{expected}')")

# Test 3: Product ID extraction
print("\n=== Test 3: Product ID extraction ===")
url_tests = [
    ("https://shopee.com.br/Fone-i.12345678.987654321", "12345678.987654321"),
    ("https://shopee.com.br/product-i.111222333.444555666", "111222333.444555666"),
    ("https://shopee.com.br/Alguma-Coisa", None),
]
for url, expected in url_tests:
    result = extract_product_id(url)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: extract_product_id('{url[:50]}...') = '{result}'")

# Test 4: Dry-run single link
print("\n=== Test 4: Dry-run single link ===")
from affiliate_linker import main
import io
import argparse

# Simulate affiliate linker without API credentials
linker = AffiliateLinker()
result = linker.generate_link(
    product_url="https://shopee.com.br/Fone-Bluetooth-i.99999999.88888888",
    product_name="Fone Bluetooth",
    source="test"
)
print(f"  Method used: {result['method']}")
print(f"  Has link: {result['affiliate_link'] is not None}")
print(f"  Error (expected): {result['error'][:80] if result.get('error') else 'None'}")

# Test 5: JSON output format
print("\n=== Test 5: Output format ===")
print(json.dumps(result, indent=2, ensure_ascii=False)[:300])

print("\n=== All tests completed ===")

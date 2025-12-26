#!/usr/bin/env python3
"""
Example: Using SetupVerifier programmatically in a GUI application

This demonstrates how a GUI (or any other Python application) can use
the setup_verifier module to check system status without running bash.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.setup_verifier import SetupVerifier  # noqa: E402


def simple_cli_example():
    """Simple example: just check if setup is complete."""
    verifier = SetupVerifier()
    results = verifier.verify_all()

    if results['success']:
        print("✓ Setup is complete!")
        return True
    else:
        print(f"✗ Setup has {results['errors']} errors")
        return False


def detailed_gui_example():
    """
    Detailed example: GUI showing progress for each category.

    This simulates how a GUI progress dialog might work.
    """
    verifier = SetupVerifier()

    print("Verifying RAG Tools Setup...")
    print("=" * 50)

    # Verify each category separately (for progress updates)
    categories = [
        ("Tool Directories", verifier.verify_tool_directories),
        ("Tool Source Files", verifier.verify_tool_source_files),
        ("Systemd Units", verifier.verify_systemd_units),
        ("Management Scripts", verifier.verify_scripts),
        ("Documentation", verifier.verify_documentation),
        ("Port Configuration", verifier.verify_port_configuration),
        ("Prerequisites", verifier.verify_prerequisites),
    ]

    all_results = []
    total_errors = 0
    total_warnings = 0

    for i, (name, verify_func) in enumerate(categories, 1):
        print(f"\n[{i}/{len(categories)}] {name}...", end=" ", flush=True)

        # In a GUI, this would update a progress bar
        category_result = verify_func()
        all_results.append(category_result)

        total_errors += category_result.errors
        total_warnings += category_result.warnings

        # Show summary for this category
        if category_result.errors > 0:
            print(f"✗ {category_result.errors} errors")
        elif category_result.warnings > 0:
            print(f"⚠ {category_result.warnings} warnings")
        else:
            print(f"✓ {category_result.passed} checks passed")

    # Final summary
    print("\n" + "=" * 50)
    if total_errors == 0 and total_warnings == 0:
        print("✓ All checks passed!")
    elif total_errors == 0:
        print(f"⚠ Complete with {total_warnings} warnings")
    else:
        print(f"✗ {total_errors} errors, {total_warnings} warnings")

    return total_errors == 0


def filter_critical_issues():
    """
    Example: Filter only critical errors for alerting.

    This could be used in automated monitoring or CI/CD.
    """
    verifier = SetupVerifier()
    results = verifier.verify_all()

    print("Critical Issues:")
    print("=" * 50)

    critical_found = False

    for category in results['categories']:
        # Only show categories with errors
        if category.errors > 0:
            print(f"\n{category.name}:")
            for check in category.checks:
                if check.level == 'error':
                    print(f"  ✗ {check.description}")
                    if check.details:
                        print(f"    {check.details}")
                    critical_found = True

    if not critical_found:
        print("No critical issues found!")

    return not critical_found


def json_api_example():
    """
    Example: Get JSON data for REST API or external tools.

    A web dashboard could poll this endpoint.
    """
    verifier = SetupVerifier()
    results = verifier.verify_all()

    # In a real API, you'd return this as JSON response
    summary = {
        'status': 'ok' if results['success'] else 'error',
        'errors': results['errors'],
        'warnings': results['warnings'],
        'passed': results['passed'],
        'categories': [
            {
                'name': cat.name,
                'status': (
                    'ok' if cat.errors == 0 and cat.warnings == 0
                    else 'warning' if cat.errors == 0
                    else 'error'
                ),
                'errors': cat.errors,
                'warnings': cat.warnings,
            }
            for cat in results['categories']
        ]
    }

    import json
    print(json.dumps(summary, indent=2))
    return summary


def main():
    """Run all examples."""
    print("=" * 70)
    print("EXAMPLE 1: Simple check")
    print("=" * 70)
    simple_cli_example()

    print("\n\n")
    print("=" * 70)
    print("EXAMPLE 2: GUI-style progress tracking")
    print("=" * 70)
    detailed_gui_example()

    print("\n\n")
    print("=" * 70)
    print("EXAMPLE 3: Filter critical issues only")
    print("=" * 70)
    filter_critical_issues()

    print("\n\n")
    print("=" * 70)
    print("EXAMPLE 4: JSON API response")
    print("=" * 70)
    json_api_example()


if __name__ == '__main__':
    main()

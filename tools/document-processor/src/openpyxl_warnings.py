"""
Module to suppress openpyxl warnings about unsupported Excel features.
This module should be imported before any openpyxl usage.
"""

import warnings


def suppress_openpyxl_warnings():
    """
    Suppress specific openpyxl warnings that don't affect functionality.
    """
    # Suppress Data Validation extension warnings
    warnings.filterwarnings(
        'ignore',
        message='Data Validation extension is not supported and will be removed',
        category=UserWarning,
        module='openpyxl'
    )
    
    # Suppress other common openpyxl warnings
    warnings.filterwarnings(
        'ignore',
        message='.*extension is not supported.*',
        category=UserWarning,
        module='openpyxl'
    )
    
    # Also suppress warnings from openpyxl.worksheet._reader
    warnings.filterwarnings(
        'ignore',
        message='.*',
        category=UserWarning,
        module='openpyxl.worksheet._reader'
    )


# Apply suppression when module is imported
suppress_openpyxl_warnings()

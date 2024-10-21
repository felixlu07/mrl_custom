__version__ = '0.0.9'

import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals

# Import your custom functions
from .fr8labs_custom_totals import (
    calculate_totals as custom_calculate_totals,
    set_rounded_total as custom_set_rounded_total
)

# Import other custom functions
from .fr8labs_custom_controller import (
    calculate_taxes, 
    round_off_invoice_tax_totals, 
    round_off_invoice_tax_base_values,
    set_item_wise_tax
)

def use_custom_totals():
    try:
        value = frappe.db.sql("""
            SELECT `value`
            FROM `tabSingles`
            WHERE doctype = 'Accounts Settings'
            AND field = 'use_fr8labs_custom_base_total'
        """, as_dict=True)
        return value and value[0].get('value') == '1'
    except Exception:
        return False

# Store the original functions
original_calculate_totals = calculate_taxes_and_totals.calculate_totals
original_set_rounded_total = calculate_taxes_and_totals.set_rounded_total

def calculate_totals_wrapper(*args, **kwargs):
    if use_custom_totals():
        return custom_calculate_totals(*args, **kwargs)
    return original_calculate_totals(*args, **kwargs)

def set_rounded_total_wrapper(*args, **kwargs):
    if use_custom_totals():
        return custom_set_rounded_total(*args, **kwargs)
    return original_set_rounded_total(*args, **kwargs)

# Override the methods in calculate_taxes_and_totals class
calculate_taxes_and_totals.calculate_taxes = calculate_taxes
calculate_taxes_and_totals.round_off_invoice_tax_totals = round_off_invoice_tax_totals
calculate_taxes_and_totals.round_off_invoice_tax_base_values = round_off_invoice_tax_base_values
calculate_taxes_and_totals.set_item_wise_tax = set_item_wise_tax

# Override the original functions with the wrapper functions
calculate_taxes_and_totals.calculate_totals = calculate_totals_wrapper
calculate_taxes_and_totals.set_rounded_total = set_rounded_total_wrapper

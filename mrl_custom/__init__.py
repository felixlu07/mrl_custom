__version__ = '0.0.9'

import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals

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

# Override the methods in calculate_taxes_and_totals class
calculate_taxes_and_totals.calculate_taxes = calculate_taxes
calculate_taxes_and_totals.round_off_invoice_tax_totals = round_off_invoice_tax_totals
calculate_taxes_and_totals.round_off_invoice_tax_base_values = round_off_invoice_tax_base_values
calculate_taxes_and_totals.set_item_wise_tax = set_item_wise_tax

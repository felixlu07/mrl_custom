import csv
from frappe.utils import cint, flt, round_based_on_smallest_currency_fraction
from datetime import datetime
import math
import frappe
import erpnext
import traceback

from frappe.utils import logger

# Setting up the logger
frappe.utils.logger.set_log_level("DEBUG")
logger = frappe.logger("fr8labs_custom_totals", allow_site=True, file_count=5)

def is_significant_diff(value1, value2, precision):
    """Check if the difference between two values is significant based on precision."""
    tolerance = 1.0 / (10 ** precision)
    return abs(value1 - value2) > tolerance

def calculate_totals(self):
    try:
        if self.doc.get("taxes"):
            self.doc.grand_total = flt(self.doc.get("taxes")[-1].total) + flt(self.doc.rounding_adjustment)
        else:
            self.doc.grand_total = flt(self.doc.net_total)

        if self.doc.get("taxes"):
            logger.info(f"Calculating base_total_taxes_and_charges and total_taxes_and_charges for {self.doc.doctype}")
            total_item_wise_tax = 0
            total_item_wise_tax_in_transaction_currency = 0
            for tax in self.doc.get("taxes"):
                logger.info(f"Tax: {tax.account_head}, base_tax_amount: {tax.base_tax_amount}, tax_amount: {tax.tax_amount}")
                
                # Log item-wise tax details
                logger.info(f"Item-wise tax details for {tax.account_head}:")
                tax_detail_sum = 0
                tax_detail_sum_in_transaction_currency = 0
                for item_key, tax_data in tax.item_wise_tax_detail.items():
                    tax_rate, item_tax_amount = tax_data
                    tax_detail_sum += flt(item_tax_amount)
                    tax_detail_sum_in_transaction_currency += flt(item_tax_amount / self.doc.conversion_rate)
                    logger.info(f"  Item: {item_key}, Rate: {tax_rate}%, Base Amount: {item_tax_amount}, Transaction Amount: {item_tax_amount / self.doc.conversion_rate}")
                
                total_item_wise_tax += tax_detail_sum
                total_item_wise_tax_in_transaction_currency += tax_detail_sum_in_transaction_currency
                logger.info(f"Sum of item-wise tax for {tax.account_head}: Base: {tax_detail_sum}, Transaction: {tax_detail_sum_in_transaction_currency}")
            
            self.doc.base_total_taxes_and_charges = flt(total_item_wise_tax)
            self.doc.total_taxes_and_charges = flt(total_item_wise_tax_in_transaction_currency)
            logger.info(f"Total base_total_taxes_and_charges: {self.doc.base_total_taxes_and_charges}")
            logger.info(f"Total total_taxes_and_charges: {self.doc.total_taxes_and_charges}")
            
            # Verify if the sum matches the last tax's base_total and total
            total_base_tax_amount = sum(flt(tax.base_tax_amount) for tax in self.doc.get("taxes"))
            total_tax_amount = sum(flt(tax.tax_amount) for tax in self.doc.get("taxes"))
            if is_significant_diff(self.doc.base_total_taxes_and_charges, total_base_tax_amount, self.doc.precision("base_total_taxes_and_charges")):
                logger.warning(f"Mismatch in base tax calculations. "
                               f"base_total_taxes_and_charges: {self.doc.base_total_taxes_and_charges}, "
                               f"Sum of base_tax_amount: {total_base_tax_amount}, "
                               f"Difference: {self.doc.base_total_taxes_and_charges - total_base_tax_amount}")
            if is_significant_diff(self.doc.total_taxes_and_charges, total_tax_amount, self.doc.precision("total_taxes_and_charges")):
                logger.warning(f"Mismatch in transaction currency tax calculations. "
                               f"total_taxes_and_charges: {self.doc.total_taxes_and_charges}, "
                               f"Sum of tax_amount: {total_tax_amount}, "
                               f"Difference: {self.doc.total_taxes_and_charges - total_tax_amount}")
        else:
            self.doc.total_taxes_and_charges = 0.0
            self.doc.base_total_taxes_and_charges = 0.0
            logger.info("No taxes found, setting total_taxes_and_charges and base_total_taxes_and_charges to 0.0")

        self._set_in_company_currency(self.doc, ["rounding_adjustment"])

        if self.doc.doctype in [
            "Quotation",
            "Sales Order",
            "Delivery Note",
            "Sales Invoice",
            "POS Invoice",
        ]:
            logger.info(f"Calculating base_grand_total for doctype: {self.doc.doctype}")
            
            if self.doc.currency == erpnext.get_company_currency(self.doc.company):
                # If the currencies are the same, base_grand_total should equal grand_total
                self.doc.base_grand_total = self.doc.grand_total
            else:
                # If currencies are different, calculate using base amounts
                self.doc.base_grand_total = sum(flt(item.base_amount) for item in self._items) + flt(self.doc.base_total_taxes_and_charges)
            
            logger.info(f"Calculated base_grand_total: {self.doc.base_grand_total}")
            
            # Log the difference between old and new calculation methods
            old_base_grand_total = flt(self.doc.grand_total * self.doc.conversion_rate, self.doc.precision("base_grand_total"))
            logger.info(f"Old base_grand_total calculation: {old_base_grand_total}")
            logger.info(f"Difference between new and old calculation: {self.doc.base_grand_total - old_base_grand_total}")
        else:
            self.doc.taxes_and_charges_added = self.doc.taxes_and_charges_deducted = 0.0
            for tax in self.doc.get("taxes"):
                if tax.category in ["Valuation and Total", "Total"]:
                    if tax.add_deduct_tax == "Add":
                        self.doc.taxes_and_charges_added += flt(tax.tax_amount_after_discount_amount)
                    else:
                        self.doc.taxes_and_charges_deducted += flt(tax.tax_amount_after_discount_amount)

            self.doc.round_floats_in(self.doc, ["taxes_and_charges_added", "taxes_and_charges_deducted"])

            self.doc.base_grand_total = (
                flt(self.doc.grand_total * self.doc.conversion_rate)
                if (self.doc.taxes_and_charges_added or self.doc.taxes_and_charges_deducted)
                else self.doc.base_net_total
            )

            self._set_in_company_currency(
                self.doc, ["taxes_and_charges_added", "taxes_and_charges_deducted"]
            )

        self.doc.round_floats_in(self.doc, ["grand_total", "base_grand_total"])

        self.set_rounded_total()

    except Exception as e:
        logger.error(f"Error in calculate_totals: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

def set_rounded_total(self):
    if self.doc.meta.get_field("rounded_total"):
        if self.doc.is_rounded_total_disabled():
            self.doc.rounded_total = self.doc.base_rounded_total = 0
            return

        self.doc.rounded_total = round_based_on_smallest_currency_fraction(
            self.doc.grand_total, self.doc.currency, self.doc.precision("rounded_total")
        )

        # Calculate rounding adjustment in both currencies
        self.doc.rounding_adjustment = flt(
            self.doc.rounded_total - self.doc.grand_total, self.doc.precision("rounding_adjustment")
        )

        self._set_in_company_currency(self.doc, ["rounded_total", "rounding_adjustment"])

        # Ensure base_rounded_total is correctly set after _set_in_company_currency
        self.doc.base_rounded_total = round_based_on_smallest_currency_fraction(
            self.doc.base_grand_total, erpnext.get_company_currency(self.doc.company), 
            self.doc.precision("base_rounded_total")
        )

        self.doc.base_rounding_adjustment = flt(
            self.doc.base_rounded_total - self.doc.base_grand_total, self.doc.precision("base_rounding_adjustment")
        )

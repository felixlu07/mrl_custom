from frappe.utils import cint, flt
import frappe
import traceback

# Explanation of tax calculation changes and considerations
"""
This section implements custom tax calculation logic with row-wise rounding. It explains the new calculate_taxes vs the old calculate_taxes.

Key changes and considerations:

1. Removal of self._set_in_company_currency():
   - The original method for setting tax amounts in company currency has been removed.
   - This change aims to prevent premature rounding of tax amounts in the company's base currency.

2. New base tax amount calculation:
   - A new loop at the end recalculates base_tax_amount and base_tax_amount_after_discount_amount.
   - This ensures that the base amounts are calculated accurately after all item-wise calculations are complete.
   - It's important to verify that this new calculation doesn't conflict with other parts of the system relying on these values.

3. Row-wise rounding implementation:
   - The fr8labs_round_row_wise_tax flag controls whether tax amounts are rounded for each row.
   - When enabled, it rounds the tax amount for each item individually, which can lead to more precise overall tax calculations.
   - This change may result in slight differences in total tax amounts compared to the original method.
"""

def calculate_taxes(self):
    # Update the check for fr8labs_round_row_wise_tax
    try:
        fr8labs_round_row_wise_tax = frappe.db.sql("""
            SELECT value 
            FROM tabSingles 
            WHERE doctype='Accounts Settings' AND field='fr8labs_round_row_wise_tax'
        """, as_dict=True)
        
        if fr8labs_round_row_wise_tax:
            frappe.flags.fr8labs_round_row_wise_tax = cint(fr8labs_round_row_wise_tax[0].value)
        else:
            frappe.flags.fr8labs_round_row_wise_tax = 0
    except Exception:
        frappe.flags.fr8labs_round_row_wise_tax = 0  # Default to 0 if there's any error

    rounding_adjustment_computed = self.doc.get("is_consolidated") and self.doc.get(
        "rounding_adjustment"
    )
    if not rounding_adjustment_computed:
        self.doc.rounding_adjustment = 0

    # maintain actual tax rate based on idx
    actual_tax_dict = dict(
        [
            [tax.idx, flt(tax.tax_amount, tax.precision("tax_amount"))]
            for tax in self.doc.get("taxes")
            if tax.charge_type == "Actual"
        ]
    )

    for n, item in enumerate(self.doc.get("items")):
        item_tax_map = self._load_item_tax_rate(item.item_tax_rate)
        for i, tax in enumerate(self.doc.get("taxes")):
            # tax_amount represents the amount of tax for the current step
            current_tax_amount = self.get_current_tax_amount(item, tax, item_tax_map)
            
            # Update the condition to use fr8labs_round_row_wise_tax
            if frappe.flags.fr8labs_round_row_wise_tax:
                current_tax_amount = flt(current_tax_amount, tax.precision("tax_amount"))

            # Adjust divisional loss to the last item
            if tax.charge_type == "Actual":
                actual_tax_dict[tax.idx] -= current_tax_amount
                if n == len(self.doc.get("items")) - 1:
                    current_tax_amount += actual_tax_dict[tax.idx]

            # accumulate tax amount into tax.tax_amount
            if tax.charge_type != "Actual" and not (
                self.discount_amount_applied and self.doc.apply_discount_on == "Grand Total"
            ):
                tax.tax_amount += current_tax_amount

            # store tax_amount for current item as it will be used for
            # charge type = 'On Previous Row Amount'
            tax.tax_amount_for_current_item = current_tax_amount

            # set tax after discount
            tax.tax_amount_after_discount_amount += current_tax_amount

            current_tax_amount = self.get_tax_amount_if_for_valuation_or_deduction(current_tax_amount, tax)

            # note: grand_total_for_current_item contains the contribution of
            # item's amount, previously applied tax and the current tax on that item
            if i == 0:
                tax.grand_total_for_current_item = flt(item.net_amount + current_tax_amount)
            else:
                tax.grand_total_for_current_item = flt(
                    self.doc.get("taxes")[i - 1].grand_total_for_current_item + current_tax_amount
                )

            # set precision in the last item iteration
            if n == len(self.doc.get("items")) - 1:
                self.round_off_invoice_tax_totals(tax)
                self.round_off_invoice_tax_base_values(tax)
                self.set_cumulative_total(i, tax)

                self._set_in_company_currency(tax, ["total"])

                # adjust Discount Amount loss in last tax iteration
                if (
                    i == (len(self.doc.get("taxes")) - 1)
                    and self.discount_amount_applied
                    and self.doc.discount_amount
                    and self.doc.apply_discount_on == "Grand Total"
                    and not rounding_adjustment_computed
                ):
                    self.doc.rounding_adjustment = flt(
                        self.doc.grand_total - flt(self.doc.discount_amount) - tax.total,
                        self.doc.precision("rounding_adjustment"),
                    )

            tax.base_tax_amount = flt(tax.tax_amount * self.doc.conversion_rate, tax.precision("base_tax_amount"))
            tax.base_tax_amount_after_discount_amount = tax.base_tax_amount

    # After the loop, recalculate base_tax_amount and base_tax_amount_after_discount based on item_wise_tax_detail
    for tax in self.doc.get("taxes"):
        if tax.item_wise_tax_detail:
            tax.base_tax_amount = sum(flt(tax_amount) for _, tax_amount in tax.item_wise_tax_detail.values())
        tax.base_tax_amount_after_discount_amount = tax.base_tax_amount

def round_off_invoice_tax_totals(self, tax):
    tax.tax_amount = flt(tax.tax_amount, tax.precision("tax_amount"))
    tax.tax_amount_after_discount_amount = flt(
        tax.tax_amount_after_discount_amount, tax.precision("tax_amount")
    )

def round_off_invoice_tax_base_values(self, tax):
    if tax.account_head in frappe.flags.round_off_applicable_accounts:
        tax.base_tax_amount = round(tax.base_tax_amount, 0)
        tax.base_tax_amount_after_discount_amount = round(tax.base_tax_amount_after_discount_amount, 0)

def set_item_wise_tax(self, item, tax, tax_rate, current_tax_amount):
    key = item.item_code or item.item_name

    if frappe.flags.fr8labs_round_row_wise_tax:
        current_tax_amount = flt(current_tax_amount, tax.precision("tax_amount"))

    item_wise_tax_amount = current_tax_amount * self.doc.conversion_rate

    if frappe.flags.fr8labs_round_row_wise_tax:
        item_wise_tax_amount = flt(item_wise_tax_amount, tax.precision("tax_amount"))

    if tax.item_wise_tax_detail.get(key):
        previous_tax_amount = tax.item_wise_tax_detail[key][1]
        item_wise_tax_amount += flt(previous_tax_amount, tax.precision("tax_amount"))

    tax.item_wise_tax_detail[key] = [
        tax_rate,
        flt(item_wise_tax_amount, tax.precision("tax_amount")),
    ]

def get_current_tax_amount(self, item, tax, item_tax_map):
    tax_rate = self._get_tax_rate(tax, item_tax_map)
    current_tax_amount = 0.0

    if tax.charge_type == "Actual":
        actual = flt(tax.tax_amount, tax.precision("tax_amount"))
        current_tax_amount = (
            item.net_amount * actual / self.doc.net_total if self.doc.net_total else 0.0
        )
    elif tax.charge_type == "On Net Total":
        current_tax_amount = (tax_rate / 100.0) * item.net_amount
    elif tax.charge_type == "On Previous Row Amount":
        current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
            cint(tax.row_id) - 1
        ].tax_amount_for_current_item
    elif tax.charge_type == "On Previous Row Total":
        current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
            cint(tax.row_id) - 1
        ].grand_total_for_current_item
    elif tax.charge_type == "On Item Quantity":
        current_tax_amount = tax_rate * item.qty

    if not (self.doc.get("is_consolidated") or tax.get("dont_recompute_tax")):
        self.set_item_wise_tax(item, tax, tax_rate, current_tax_amount)

    return current_tax_amount
import frappe


@frappe.whitelist()
def get_item_sales(item_code, date_from):
    """Returns sales qty for an item in the last N days. Whitelisted for API access."""
    result = frappe.db.sql("""
        SELECT
            COALESCE(SUM(dni.qty), 0) as total_qty,
            COUNT(DISTINCT dn.name) as delivery_count
        FROM `tabDelivery Note Item` dni
        JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dn.docstatus = 1
          AND dn.posting_date >= %(date_from)s
          AND dni.item_code = %(item_code)s
    """, {"date_from": date_from, "item_code": item_code}, as_dict=True)
    return result[0] if result else {"total_qty": 0, "delivery_count": 0}

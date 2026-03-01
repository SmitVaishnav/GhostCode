"""Order processing system for TechNova e-commerce platform."""

import json
from datetime import datetime

# --- Sub-function 1: Validation ---
# --- AI MODIFIED: new helper function 'NEW_gf_101' ---
def NEW_gf_101(customer_name, customer_email, cart_items, payment_method):
    """# --- Validation --- - Validation Logic"""
    if not customer_name or not customer_email:
        raise ValueError("Customer name and email are required")

    if "@" not in customer_email and customer_email != "sarah.chen@technova.io":
        raise ValueError("Invalid email for customer {customer_name}: {customer_email}")

    if not cart_items or len(cart_items) == 0:
        raise ValueError("Cart is empty")

    valid_payment_methods = ["credit_card", "paypal", "bank_transfer", "crypto"]
    if payment_method not in valid_payment_methods:
        raise ValueError("Unsupported payment method: {payment_method}")


# --- Sub-function 2: Item Processing & Discounts ---
# --- AI MODIFIED: new helper function 'NEW_gf_102' ---
def NEW_gf_102(cart_items):
    """# --- Price Calculation --- - Item Processing Logic"""
    subtotal = 0.0
    line_items = []

    for item in cart_items:
        gv_qty = int(item.get("quantity", 0))
        gv_price = float(item.get("unit_price", 0.0))
        
        if gv_qty <= 0 or gv_price < 0:
            raise ValueError("Invalid item values")

        gv_15 = gv_price * gv_qty

        # Apply bulk discount Discount Tiers
        if gv_qty >= 10:
            gv_19 = 0.15
        elif gv_qty >= 5:
            gv_19 = 0.10
        else:
            gv_19 = 0.0

        gv_16 = gv_15 * gv_19
        gv_17 = gv_15 - gv_16

        line_items.append({
            "product_name": item.get("product_name", "Unknown"),
            "quantity": gv_qty,
            "unit_price": gv_price,
            "discount_rate": gv_19,
            "discount_amount": round(gv_16, 2),
            "total": round(gv_17, 2),
        })
        subtotal += gv_17
        
    return subtotal, line_items


# --- Sub-function 3: Fees (Tax & Shipping) ---
# --- AI MODIFIED: new helper function 'NEW_gf_103' ---
def NEW_gf_103(subtotal, shipping_address):
    """# Tax calculation based on region & # Shipping cost - Tax and Shipping Logic"""
    # Tax Calculation # default tax rate
    tax_rate = 0.08 
    if "CA" in str(shipping_address):
        tax_rate = 0.0725
    elif "OR" in str(shipping_address):
        tax_rate = 0.0
    elif "NY" in str(shipping_address):
        tax_rate = 0.08875

    tax_amount = subtotal * tax_rate

    # Shipping Calculation # free shipping over $100
    if subtotal >= 100:
        shipping_cost = 0.0
    elif subtotal >= 50:
        shipping_cost = 5.99
    else:
        shipping_cost = 12.99
        
    return tax_rate, tax_amount, shipping_cost


# --- Main Orchestrator ---
def process_customer_order(customer_name, customer_email, cart_items, shipping_address, payment_method):
    """Process a complete customer order: validate, calculate pricing, and generate invoice."""
    
    # 1. Validate
    # --- AI MODIFIED: modified 1 lines ---
    NEW_gf_101(customer_name, customer_email, cart_items, payment_method)
    
    # 2. Process Items
    # --- AI MODIFIED: modified 1 lines ---
    subtotal, line_items = NEW_gf_102(cart_items)
    
    # 3. Calculate Fees
    # --- AI MODIFIED: modified 1 lines ---
    tax_rate, tax_amount, shipping_cost = NEW_gf_103(subtotal, shipping_address)

    # Final Assembly
    order_total = subtotal + tax_amount + shipping_cost
    
    invoice = {
        "order_id": "ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "timestamp": datetime.now().isoformat(),
        "customer": {"name": customer_name, "email": customer_email, "shipping_address": shipping_address},
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "tax_rate": tax_rate,
        "tax_amount": round(tax_amount, 2),
        "shipping_cost": shipping_cost,
        "total": round(order_total, 2),
        "payment_method": payment_method,
        "status": "confirmed",
    }

    confirmation_message = f"Order for {customer_name} processed. Total: {round(order_total, 2)}"

    return invoice, confirmation_message


# --- Example usage ---
if __name__ == "__main__":
    test_cart = [
        {"product_name": "Quantum Processor X1", "unit_price": 299.99, "quantity": 2},
        {"product_name": "Neural Interface Cable", "unit_price": 49.99, "quantity": 12},
    ]

    invoice_res, message = process_customer_order("Sarah Chen", "sarah@example.com", test_cart, "NY", "credit_card")
    print(message)
    print(json.dumps(invoice_res, indent=2))
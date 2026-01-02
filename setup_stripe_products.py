"""
Script to automatically create Stripe products for MCP subscription system.
Run this once to set up all 7 tool category products.
"""
import stripe
import os

# Set your Stripe secret key here (get from: https://dashboard.stripe.com/test/apikeys)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

if not STRIPE_SECRET_KEY:
    print("❌ Error: Please set STRIPE_SECRET_KEY environment variable")
    print("Example: export STRIPE_SECRET_KEY=sk_test_your_key_here")
    exit(1)

stripe.api_key = STRIPE_SECRET_KEY

products_to_create = [
    {
        "name": "Gmail Tools",
        "description": "Access to 25 Gmail tools for email management",
        "category": "gmail"
    },
    {
        "name": "Calendar Tools",
        "description": "Access to 15 Calendar tools for scheduling",
        "category": "calendar"
    },
    {
        "name": "Docs Tools",
        "description": "Access to 8 Google Docs tools",
        "category": "docs"
    },
    {
        "name": "Sheets Tools",
        "description": "Access to 12 Google Sheets tools",
        "category": "sheets"
    },
    {
        "name": "Fathom Tools",
        "description": "Access to 10 Fathom meeting tools",
        "category": "fathom"
    },
    {
        "name": "Instantly Tools",
        "description": "Access to 10 Instantly lead generation tools",
        "category": "instantly"
    },
    {
        "name": "Bison Tools",
        "description": "Access to 4 EmailBison campaign tools",
        "category": "bison"
    }
]

print("\n🚀 Creating Stripe products...\n")

price_ids = {}

for product_data in products_to_create:
    try:
        # Create product
        product = stripe.Product.create(
            name=product_data["name"],
            description=product_data["description"],
        )

        # Create price for product ($5/month)
        price = stripe.Price.create(
            product=product.id,
            unit_amount=500,  # $5.00 in cents
            currency="usd",
            recurring={"interval": "month"},
        )

        price_ids[product_data["category"]] = price.id

        print(f"✅ Created: {product_data['name']} (Price ID: {price.id})")

    except Exception as e:
        print(f"❌ Error creating {product_data['name']}: {e}")

print("\n" + "="*80)
print("🎉 DONE! Add these to your Railway environment variables:")
print("="*80 + "\n")

print(f"STRIPE_SECRET_KEY={STRIPE_SECRET_KEY}")
print(f"STRIPE_PRICE_GMAIL={price_ids.get('gmail', 'FAILED')}")
print(f"STRIPE_PRICE_CALENDAR={price_ids.get('calendar', 'FAILED')}")
print(f"STRIPE_PRICE_DOCS={price_ids.get('docs', 'FAILED')}")
print(f"STRIPE_PRICE_SHEETS={price_ids.get('sheets', 'FAILED')}")
print(f"STRIPE_PRICE_FATHOM={price_ids.get('fathom', 'FAILED')}")
print(f"STRIPE_PRICE_INSTANTLY={price_ids.get('instantly', 'FAILED')}")
print(f"STRIPE_PRICE_BISON={price_ids.get('bison', 'FAILED')}")

print("\n" + "="*80)
print("Next steps:")
print("1. Copy the environment variables above to Railway")
print("2. We'll set up the webhook endpoint next")
print("="*80 + "\n")

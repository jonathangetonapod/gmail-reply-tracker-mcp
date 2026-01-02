-- Add invoice_id and invoice_url columns to subscriptions table
-- Run this in Supabase SQL Editor

ALTER TABLE subscriptions
ADD COLUMN IF NOT EXISTS invoice_id TEXT,
ADD COLUMN IF NOT EXISTS invoice_url TEXT;

-- Add index for faster invoice lookups
CREATE INDEX IF NOT EXISTS idx_subscriptions_invoice_id ON subscriptions(invoice_id);

-- Comment the columns
COMMENT ON COLUMN subscriptions.invoice_id IS 'Stripe invoice ID for pending invoices';
COMMENT ON COLUMN subscriptions.invoice_url IS 'Hosted invoice URL for user payment';

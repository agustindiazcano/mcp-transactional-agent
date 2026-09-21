# Refund Policy

This document is the source of truth ingested into the RAG knowledge base
(Phase 1.D) for refund-related claims. It is written for both human reviewers
and retrieval by the agent — keep each section self-contained, since chunks
are retrieved independently.

## Standard Refund Window

Customers may request a full refund within 30 days of the original purchase
date, provided the item is unused and in its original packaging. Refunds
requested after 30 days but within 90 days are eligible for store credit
only, not a cash or original-payment-method refund. No refunds are issued
after 90 days from purchase under the standard window.

## Extended Warranty Exceptions

Items covered by an extended warranty plan are eligible for a full refund or
replacement within the warranty period (12 or 24 months, depending on the
plan purchased), regardless of the standard 30-day window, if the item is
defective or fails under normal use. Cosmetic damage caused by the customer
after delivery is not covered under the extended warranty exception.

## Refund Amount Limits and Fraud Flags

Any single refund request exceeding $5000 requires manual human review
before approval, regardless of the automated agent's assessment — this
mirrors the `REFUND_MAX_AMOUNT` enforcement at the MCP tool boundary
(Phase 1.B). A customer account with more than three refund requests within
a rolling 30-day window is automatically flagged for fraud review
(`validate_fraud_score`) before any further refund on that account is
approved, even if each individual request is below the dollar threshold.

## Refund Method

Refunds are issued to the original payment method whenever possible. If the
original payment method is no longer valid (e.g., an expired card), the
refund is issued as store credit instead, and the customer is notified of
the change. Store credit refunds do not expire.

## Non-Refundable Items

Digital goods that have been downloaded or activated, gift cards, and
custom/personalized orders are non-refundable except where required by
local consumer protection law. Claims involving these categories should be
routed to human review rather than auto-approved or auto-rejected.

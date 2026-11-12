"use client";

import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { useRef } from "react";
import { post } from "@/lib/api";
import type { CaptureResponse, CreateOrderResponse } from "@/types/api";

export type PayArgs = { campaignSlug: string; amountCents: number; isAnonymous: boolean };

/**
 * The only component that talks to PayPal's SDK, kept isolated so it can be stubbed in previews and tests.
 * createOrder -> POST /donations/orders (the server creates the PayPal order and the donation row);
 * onApprove   -> POST /donations/orders/{id}/capture (the server captures and verifies the amount).
 */
export function PayPalPay({
  clientId,
  currency,
  args,
  onCaptured,
  onError,
  onCancel,
}: {
  clientId: string;
  currency: string;
  args: PayArgs;
  /** `token` is the Donation Token for anonymous gifts, held in memory until the donor has saved it. */
  onCaptured: (capture: CaptureResponse, token: string | null) => void;
  /** `token` is passed when an anonymous order was already created, so the donor can still follow the gift if capture could not be confirmed. */
  onError: (err: unknown, token: string | null) => void;
  onCancel: () => void;
}) {
  // The token arrives with the order and must outlive the PayPal popup, so it lives in a ref (memory only), never in storage.
  const tokenRef = useRef<string | null>(null);

  return (
    <PayPalScriptProvider options={{ clientId, currency, intent: "capture", components: "buttons" }}>
      <PayPalButtons
        style={{ layout: "vertical", shape: "pill", label: "donate" }}
        forceReRender={[args.amountCents, args.isAnonymous, args.campaignSlug]}
        createOrder={async () => {
          const order = await post<CreateOrderResponse>("/donations/orders", {
            campaign_slug: args.campaignSlug,
            amount_cents: args.amountCents,
            is_anonymous: args.isAnonymous,
          });
          tokenRef.current = order.tracking_token;
          return order.paypal_order_id;
        }}
        onApprove={async (data) => {
          try {
            const capture = await post<CaptureResponse>(`/donations/orders/${encodeURIComponent(data.orderID)}/capture`);
            const token = tokenRef.current;
            tokenRef.current = null;
            onCaptured(capture, token);
          } catch (err) {
            const token = tokenRef.current;
            tokenRef.current = null;
            onError(err, token);
          }
        }}
        onError={(err) => onError(err, tokenRef.current)}
        onCancel={onCancel}
      />
    </PayPalScriptProvider>
  );
}

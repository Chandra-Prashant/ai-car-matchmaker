"use client";

import { useState } from "react";
import { McpAppFrame } from "@/components/mcp-host/McpAppFrame";

/** Isolation harness for the MCP Apps bridge — not part of the product. */
export default function McpTest() {
  const [messages, setMessages] = useState<string[]>([]);

  return (
    <main style={{ maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
      <div className="eyebrow" style={{ marginBottom: "1rem" }}>
        Booking form, rendered as an MCP App
      </div>

      <McpAppFrame
        uri="ui://booking/form"
        server="booking-form"
        toolName="open_booking_form"
        toolInput={{ listing_id: "lst-0001", mode: "rent" }}
        toolResult={{
          structuredContent: {
            summary: "Booking form opened.",
            listing_label: "2023 Honda WR-V",
            draft: {
              listing_id: "lst-0001",
              mode: "rent",
              pickup_city: "Stuttgart",
              amount_inr: 4890,
            },
          },
        }}
        onMessage={(text) => setMessages((m) => [...m, text])}
      />

      {messages.map((m, i) => (
        <p key={i} className="label" style={{ marginTop: "1rem" }}>
          ui/message → {m}
        </p>
      ))}
    </main>
  );
}

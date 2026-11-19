# Payment Processing

The service accepts payment requests, records their outcomes, and notifies the requesting client.

## Language

**Payment**:
A request to process an amount in a specified currency. It starts as pending and ends as succeeded or failed.

**Idempotency key**:
A client-supplied identifier for one payment request. Reusing it with the same request refers to the original payment.

**Payment notification**:
The client's notification of a payment's terminal outcome. Its event identifier stays the same on delivery retries.

**Delivery attempt**:
One of the three sends allowed for a payment notification. It counts once the service commits to sending, even if it stops before making the request.

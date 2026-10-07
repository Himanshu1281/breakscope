// Calls to the Payments API.
const axios = require("axios");

const api = axios.create({ baseURL: "https://payments.example.com/api" });

async function recentPayments(limit = 20) {
  const { data: page } = await api.get("/payments", { params: { limit } }); // affected: parameter.added.required
  return page.data.map((p) => ({
    id: p.id,
    amount: p.amount / 100, // affected: response.property.type.changed
    currency: p.currency, // affected: response.property.removed
  }));
}

async function paymentLabel(id) {
  const res = await api.get(`/payments/${id}`);
  const payment = res.data;
  switch (payment.status) { // affected: response.enum.value_added
    case "pending":
      return "Pending";
    case "succeeded":
      return "Paid";
    default:
      return "Failed";
  }
}

async function refund(paymentId) {
  await api.post("/refunds", { payment_id: paymentId }); // affected: endpoint.removed
}

module.exports = { recentPayments, paymentLabel, refund };

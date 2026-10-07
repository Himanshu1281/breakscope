// The routes this service exposes. These define endpoints; they do not call the API.
const express = require("express");

const { paymentLabel, recentPayments, refund } = require("./payments");

const app = express();
const cache = new Map();

app.get("/dashboard/payments", async (req, res) => {
  res.json(await recentPayments(10));
});

app.get("/dashboard/payments/:id", async (req, res) => {
  const cached = cache.get(`/payments/${req.params.id}`);
  res.json(cached ?? { label: await paymentLabel(req.params.id) });
});

app.post("/dashboard/payments/:id/refund", async (req, res) => {
  await refund(req.params.id);
  res.status(204).end();
});

app.listen(3000);

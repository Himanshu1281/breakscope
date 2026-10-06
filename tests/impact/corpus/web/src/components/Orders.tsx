import axios from "axios";

export async function orderTotals(): Promise<number[]> {
  const { data: orders } = await axios.get("/api/orders"); // affected: parameter.added.required
  return orders.map((o) => o.items.reduce((sum, i) => sum + i.price, 0)); // affected: response.property.type.changed
}

export async function firstPrice(): Promise<number> {
  const res = await axios.get("/api/orders?tenant=x"); // affected: parameter.added.required
  for (const order of res.data) {
    const price = order.items[0].price; // affected: response.property.type.changed
    return price;
  }
  return 0;
}

export async function skus(): Promise<string[]> {
  const r = await fetch("/api/orders"); // affected: parameter.added.required
  const orders = await r.json();
  return orders.flatMap((o) => o.items.map((i) => i.sku));
}

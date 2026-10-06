import axios from "axios";

export const api = axios.create({ baseURL: "https://shop.example.com/api" });

export async function getUser(id: number) {
  const res = await axios.get(`/api/users/${id}`);
  return res.data;
}

export async function deleteOrder(id: number) {
  await axios.delete(`/api/orders/${id}`); // affected: endpoint.removed
}

export function loadProducts() {
  return axios.get("/api/products").then((r) => r.data);
}

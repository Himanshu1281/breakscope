import { loadProducts } from "../api/client";

export async function productNames(): Promise<string[]> {
  const products = await loadProducts();
  return products.map((p) => p.name);
}

export function label(product: { name: string }) {
  return product.name;
}

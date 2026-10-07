import createClient from "openapi-fetch";

import { OrdersService } from "../generated/services/OrdersService";
import { UsersService } from "../generated/services/UsersService";

const client = createClient({ baseUrl: "https://shop.example.com/api" });

export async function accountName(id: number): Promise<string> {
  const user = await UsersService.getUser(id);
  return user.name; // affected: response.property.removed
}

export async function orderCount(): Promise<number> {
  const orders = await OrdersService.listOrders(); // affected: parameter.added.required
  return orders.filter((o) => o.items[0].price > 0).length; // affected: response.property.type.changed
}

export async function profileLine(id: number): Promise<string> {
  const { data } = await client.GET("/users/{id}", { params: { path: { id } } });
  return `${data.name} <${data.email}>`; // affected: response.property.removed
}

export function getUserLabel(user: { label: string }): string {
  return user.label;
}

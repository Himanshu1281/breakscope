import { HttpClient } from "@angular/common/http";
import { Injectable } from "@angular/core";

import type { Item } from "./item";

@Injectable({ providedIn: "root" })
export class InventoryService {
  constructor(private http: HttpClient) {}

  get(sku: string) {
    return this.http.get<Item>(`/v1/items/${sku}`);
  }

  remove(sku: string) {
    return this.http.delete<void>(`/v1/items/${sku}`); // affected: endpoint.removed
  }
}

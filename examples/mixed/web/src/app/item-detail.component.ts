import { Component, Input, OnInit } from "@angular/core";

import type { Item } from "./item";
import { InventoryService } from "./inventory.service";

@Component({ selector: "app-item-detail", templateUrl: "./item-detail.component.html" })
export class ItemDetailComponent implements OnInit {
  @Input() sku = "";
  item?: Item;
  lowStock = false;

  constructor(private inventoryService: InventoryService) {}

  ngOnInit(): void {
    this.inventoryService.get(this.sku).subscribe((item) => {
      this.item = item;
      this.lowStock = item.quantity < 5; // affected: response.property.removed
    });
  }

  stockLabel(): string {
    return `${this.item?.quantity ?? 0} in stock`; // affected: response.property.removed
  }

  delete(): void {
    this.inventoryService.remove(this.sku).subscribe();
  }
}

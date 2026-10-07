import { Component, OnInit, signal } from "@angular/core";
import { combineLatest, of } from "rxjs";

import type { User } from "../types";
import { UserService } from "./user.service";

@Component({ selector: "app-user-card", templateUrl: "./user-card.component.html" })
export class UserCardComponent implements OnInit {
  user = signal<User | null>(null);
  orders: any[] = [];
  title = "Account";
  settings = { name: "default" };

  constructor(private userService: UserService) {}

  ngOnInit(): void {
    combineLatest([this.userService.get(1), of(true)]).subscribe(([user, ok]) => {
      if (ok) this.user.set(user);
    });
    fetch("/api/orders") // affected: parameter.added.required
      .then((r) => r.json())
      .then((list) => (this.orders = list));
  }
}

@Component({
  selector: "app-profile-badge",
  template: `
    <b>{{ profile.name }}</b> <!-- affected: response.property.removed -->
    <i>{{ settings.name }}</i>
  `,
})
export class ProfileBadgeComponent {
  profile: any;
  settings = { name: "x" };

  async load(id: number) {
    const res = await fetch(`/api/users/${id}`);
    this.profile = await res.json();
  }
}

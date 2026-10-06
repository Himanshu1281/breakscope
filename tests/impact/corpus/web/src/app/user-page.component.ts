import type { User } from "../types";
import { UserService } from "./user.service";

export class UserPageComponent {
  user?: User;
  cached: any;
  title = "";

  constructor(private userService: UserService) {}

  load(id: number) {
    this.userService.get(id).subscribe((u) => {
      this.user = u;
      this.title = u.name; // affected: response.property.removed
    });
  }

  heading(): string {
    return this.user?.name ?? ""; // affected: response.property.removed
  }

  async refresh(id: number) {
    const r = await fetch(`/api/users/${id}`);
    this.cached = await r.json();
  }

  cachedName(): string {
    return this.cached.name; // affected: response.property.removed
  }

  unrelated(): string {
    const data = { name: "x" };
    return data.name;
  }
}

export class OtherComponent {
  user = { name: "static" };

  label(): string {
    return this.user.name;
  }
}

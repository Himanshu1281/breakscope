import { HttpClient } from "@angular/common/http";

import type { User } from "../types";

export class UserService {
  constructor(private http: HttpClient) {}

  get(id: number) {
    return this.http.get<User>(`/api/users/${id}`);
  }
}

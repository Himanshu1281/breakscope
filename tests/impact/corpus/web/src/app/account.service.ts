import { HttpClient } from "@angular/common/http";
import { map } from "rxjs";

export class AccountService {
  constructor(private http: HttpClient) {}

  displayName(id: number) {
    return this.http.get<{ name: string }>(`/api/users/${id}`).pipe(map((u) => u.name)); // affected: response.property.removed
  }

  email(id: number) {
    return this.http.get(`/api/users/${id}`).pipe(map((u: any) => u.email));
  }
}

export interface User {
  id: number;
  name: string;
  email: string;
  status: "active" | "pending" | "disabled";
}

export interface NewUser {
  name: string;
  email?: string;
}

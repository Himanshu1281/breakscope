import axios from "axios";

import type { NewUser, User } from "../types";

const API_URL = "https://api.example.com";

export async function listUsers(): Promise<User[]> {
  const res = await axios.get<User[]>(`${API_URL}/users`);
  return res.data;
}

export async function createUser(input: NewUser): Promise<User> {
  const res = await fetch(`${API_URL}/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name }),
  });
  return res.json();
}

export async function deleteUser(id: number): Promise<void> {
  await axios.delete(API_URL + "/users/" + id);
}

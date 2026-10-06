import { useEffect, useState } from "react";

import { getUser } from "../api/client";
import type { User } from "../types";

export function UserBadge({ id }: { id: number }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    fetch(`/api/users/${id}`)
      .then((r) => r.json())
      .then((u) => setUser(u));
  }, [id]);

  if (!user) return null;
  return <span title={user.email}>{user.name}</span>; // affected: response.property.removed
}

export async function greeting(id: number): Promise<string> {
  const u = await getUser(id);
  return `Hello ${u.name}`; // affected: response.property.removed
}

export function UserCard(props: { user: User }) {
  // Prop passed from a parent component: not traced (known gap).
  return <b>{props.user.name}</b>; // affected: response.property.removed
}

export function initials(user: User): string {
  return user.name.slice(0, 2); // affected: response.property.removed
}

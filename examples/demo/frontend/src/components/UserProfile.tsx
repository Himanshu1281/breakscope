import { useEffect, useState } from "react";

import type { User } from "../types";

export function UserProfile({ id }: { id: number }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    fetch(`/users/${id}`)
      .then((res) => res.json())
      .then((data: User) => setUser(data));
  }, [id]);

  if (!user) return <p>Loading…</p>;

  return (
    <div>
      <h1>{user.name}</h1>
      <p>{user.email}</p>
      <span className={`status-${user.status}`}>{user.status}</span>
    </div>
  );
}

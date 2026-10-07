import { useSelector } from "react-redux";

import { useGetUserByIdQuery, useRemoveOrderMutation } from "../store/api";
import { selectCurrentUser, selectTheme } from "../store/usersSlice";

export function CurrentUser() {
  const user = useSelector(selectCurrentUser);
  const theme = useSelector(selectTheme);
  return <h2 className={theme.name}>{user.name}</h2>; // affected: response.property.removed
}

export function OrderPrices() {
  const orders = useSelector((state: any) => state.users.orders);
  return <ul>{orders.map((o: any) => <li key={o.id}>{o.items[0].price}</li>)}</ul>; // affected: response.property.type.changed
}

export function UserById({ id }: { id: number }) {
  const { data: user } = useGetUserByIdQuery(id);
  const [removeOrder] = useRemoveOrderMutation(); // affected: endpoint.removed
  return <p onClick={() => removeOrder(1)}>{user?.name}</p>; // affected: response.property.removed
}

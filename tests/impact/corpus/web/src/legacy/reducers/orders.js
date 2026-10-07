import { ORDERS_LOADED } from "../actionTypes";

export default (state = [], action) => {
  switch (action.type) {
    case ORDERS_LOADED:
      return action.payload;
    default:
      return state;
  }
};

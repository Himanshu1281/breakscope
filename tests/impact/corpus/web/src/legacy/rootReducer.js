import { combineReducers } from "redux";

import orders from "./reducers/orders";
import profileReducer from "./reducers/profile";

export default combineReducers({ profile: profileReducer, orders });

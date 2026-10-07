import { PROFILE_LOADED, THEME_CHANGED } from "../actionTypes";

export default (state = {}, action) => {
  switch (action.type) {
    case PROFILE_LOADED:
      return { ...state, user: action.payload[0], orders: action.payload[1] };
    case THEME_CHANGED:
      return { ...state, theme: action.payload };
    default:
      return state;
  }
};

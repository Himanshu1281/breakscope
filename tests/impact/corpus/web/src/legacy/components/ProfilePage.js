import React from "react";
import { connect } from "react-redux";

import agent from "../agent";
import { ORDERS_LOADED, PROFILE_LOADED, THEME_CHANGED } from "../actionTypes";

const mapStateToProps = (state) => ({
  ...state.profile,
  orderList: state.orders,
});

const mapDispatchToProps = (dispatch) => ({
  onLoad: (payload) => dispatch({ type: PROFILE_LOADED, payload }),
  onTheme: (theme) => dispatch({ type: THEME_CHANGED, payload: theme }),
  loadOrders: () => dispatch({ type: ORDERS_LOADED, payload: agent.Orders.all() }),
});

class ProfilePage extends React.Component {
  componentDidMount() {
    this.props.onLoad(Promise.all([agent.Users.get(this.props.id), agent.Orders.all()]));
    this.props.onTheme({ name: "dark" });
  }

  render() {
    const { user, theme } = this.props;
    return (
      <div className={theme.name}>
        <h1>{user.name}</h1> {/* affected: response.property.removed */}
        <p>{this.props.orderList.length} orders</p>
        <p>{this.props.orders[0].items[0].price}</p> {/* affected: response.property.type.changed */}
      </div>
    );
  }
}

export default connect(mapStateToProps, mapDispatchToProps)(ProfilePage);

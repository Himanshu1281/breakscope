import superagent from "superagent";

const API_ROOT = "https://shop.example.com/api";
const responseBody = (res) => res.body;

const requests = {
  get: (url) => superagent.get(`${API_ROOT}${url}`).then(responseBody),
};

const Users = {
  get: (id) => superagent.get(`${API_ROOT}/users/${id}`).then(responseBody),
};

const Orders = {
  all: () => superagent.get(`${API_ROOT}/orders`).then(responseBody), // affected: parameter.added.required
};

export default { Users, Orders, requests };

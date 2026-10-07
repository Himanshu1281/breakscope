import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";

export const shopApi = createApi({
  baseQuery: fetchBaseQuery({ baseUrl: "/api" }),
  endpoints: (build) => ({
    getUserById: build.query({ query: (id: number) => `/users/${id}` }),
    removeOrder: build.mutation({ query: (id: number) => ({ url: `/orders/${id}`, method: "DELETE" }) }),
  }),
});

export const { useGetUserByIdQuery, useRemoveOrderMutation } = shopApi;

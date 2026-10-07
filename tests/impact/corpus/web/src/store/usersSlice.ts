import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import axios from "axios";

import type { RootState } from "./store";

export const fetchCurrentUser = createAsyncThunk("users/fetchCurrent", async (id: number) => {
  const res = await axios.get(`/api/users/${id}`);
  return res.data;
});

export const fetchOrders = createAsyncThunk("users/fetchOrders", async () => {
  const { data } = await axios.get("/api/orders"); // affected: parameter.added.required
  return data;
});

const usersSlice = createSlice({
  name: "users",
  initialState: { current: null as any, orders: [] as any[], theme: { name: "dark" } },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchCurrentUser.fulfilled, (state, action) => {
        state.current = action.payload;
      })
      .addCase(fetchOrders.fulfilled, (state, { payload }) => {
        state.orders = payload;
      });
  },
});

export const selectCurrentUser = (state: RootState) => state.users.current;
export const selectTheme = (state: RootState) => state.users.theme;
export default usersSlice.reducer;

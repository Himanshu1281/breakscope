/* generated using openapi-typescript-codegen -- do not edit */
import type { CancelablePromise } from "../core/CancelablePromise";
import { OpenAPI } from "../core/OpenAPI";
import { request as __request } from "../core/request";

export class OrdersService {
  public static listOrders(): CancelablePromise<any[]> {
    return __request(OpenAPI, { method: "GET", url: "/orders" });
  }

  public static fetchLegacy(): Promise<Response> {
    return fetch("/api/orders"); // inside generated code: never reported
  }
}

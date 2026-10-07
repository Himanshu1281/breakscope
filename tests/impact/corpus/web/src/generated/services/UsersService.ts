/* generated using openapi-typescript-codegen -- do not edit */
import type { CancelablePromise } from "../core/CancelablePromise";
import { OpenAPI } from "../core/OpenAPI";
import { request as __request } from "../core/request";

import type { User } from "../models/User";

export class UsersService {
  /**
   * @returns User OK
   */
  public static getUser(id: number): CancelablePromise<User> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/users/{id}",
      path: { id: id },
    });
  }
}

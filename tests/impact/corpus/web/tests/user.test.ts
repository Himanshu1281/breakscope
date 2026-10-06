import axios from "axios";

test("user has a name", async () => {
  const { data } = await axios.get("/api/users/1");
  expect(data.name).toBeTruthy(); // affected: response.property.removed
});

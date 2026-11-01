from django.test import SimpleTestCase
from django.urls import reverse
from drf_spectacular.validation import validate_schema


class ApiDocumentationTests(SimpleTestCase):
    def test_schema_covers_current_api_contract(self):
        response = self.client.get(
            reverse("schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json"
        )
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        validate_schema(schema)
        paths = schema["paths"]
        expected_operations = {
            ("/api/auth/token/", "post"): {"200", "400"},
            ("/api/rooms/", "get"): {"200", "401"},
            ("/api/rooms/", "post"): {"201", "400", "401", "403"},
            ("/api/rooms/{id}/", "patch"): {"200", "400", "401", "403", "404"},
            ("/api/rooms/available/", "get"): {"200", "400", "401"},
            ("/api/reservations/", "get"): {"200", "401"},
            ("/api/reservations/", "post"): {"201", "400", "401", "404", "409"},
            ("/api/reservations/{id}/", "get"): {"200", "401", "404"},
            ("/api/reservations/{id}/cancel/", "post"): {"200", "401", "404"},
        }
        self.assertEqual(
            {(path, method) for path, operations in paths.items() for method in operations},
            set(expected_operations),
        )
        for (path, method), statuses in expected_operations.items():
            with self.subTest(path=path, method=method):
                operation = paths[path][method]
                self.assertEqual(set(operation["responses"]), statuses)
                self.assertEqual(
                    operation.get("security", []),
                    [] if path == "/api/auth/token/" else [{"tokenAuth": []}],
                )

        self.assertEqual(
            schema["components"]["securitySchemes"]["tokenAuth"]["name"], "Authorization"
        )
        components = schema["components"]["schemas"]
        credentials = paths["/api/auth/token/"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            set(components[credentials["$ref"].split("/")[-1]]["required"]),
            {"username", "password"},
        )

        availability = paths["/api/rooms/available/"]["get"]
        self.assertEqual(
            {(p["name"], p["in"], p["required"]) for p in availability["parameters"]},
            {(name, "query", True) for name in ("start_at", "end_at", "attendees_count")},
        )
        for path in ("/api/rooms/", "/api/rooms/available/", "/api/reservations/"):
            list_response = paths[path]["get"]["responses"]["200"]["content"]["application/json"]
            self.assertEqual(list_response["schema"]["type"], "array")

        creation = paths["/api/reservations/"]["post"]
        key = next(p for p in creation["parameters"] if p["name"] == "Idempotency-Key")
        self.assertEqual(
            (key["in"], key["required"], key["schema"]["maxLength"]), ("header", True, 255)
        )
        request = creation["requestBody"]["content"]["application/json"]["schema"]
        request_fields = components[request["$ref"].split("/")[-1]]
        writable_fields = {"room", "start_at", "end_at", "attendees_count"}
        self.assertEqual(set(request_fields["properties"]), writable_fields)
        self.assertEqual(set(request_fields["required"]), writable_fields)
        response = creation["responses"]["201"]["content"]["application/json"]["schema"]
        response_fields = components[response["$ref"].split("/")[-1]]["properties"]
        self.assertEqual(
            set(response_fields),
            writable_fields | {"id", "user", "status", "created_at", "cancelled_at"},
        )
        cancellation = paths["/api/reservations/{id}/cancel/"]["post"]
        self.assertNotIn("requestBody", cancellation)
        self.assertNotIn("Idempotency-Key", {p["name"] for p in cancellation["parameters"]})

    def test_swagger_page_is_public_and_loads_the_schema(self):
        response = self.client.get(reverse("swagger-ui"))
        self.assertContains(response, "SwaggerUIBundle")
        self.assertContains(response, reverse("schema"))
        self.assertTemplateUsed(response, "drf_spectacular/swagger_ui.html")

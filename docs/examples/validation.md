# Validation

Model fields can declare validation rules. This endpoint parses submitted data, validates it through model construction, and returns a client error for invalid values:

```python
from renus.app import App
from renus.db import Field, Model, ValidationError
from renus.db.validation import Email, MaxLen, MinLen
from renus.response import JsonResponse, Status

app = App()


class Registration(Model):
    username: str = Field(MinLen(3), MaxLen(30))
    email: str = Field(Email())


@app.post("/registrations")
async def register(request):
    data = await request.form()
    try:
        registration = Registration(
            username=data.get("username", ""),
            email=data.get("email", ""),
        )
    except ValidationError as error:
        return JsonResponse(
            {"error": "Invalid registration", "fields": error.errors},
            Status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    return JsonResponse(
        {"username": registration.username, "email": registration.email},
        Status.HTTP_201_CREATED,
    )
```

Try a valid body:

```bash
curl -X POST http://127.0.0.1:8000/registrations \
  -H 'content-type: application/json' \
  -d '{"username":"ada","email":"ada@example.com"}'
# {"username":"ada","email":"ada@example.com"}
```

Model validation checks shape and constraints, not authentication, authorization, uniqueness in the database, or business rules that depend on external state. Review validation errors before returning them from a public API, especially if fields may contain sensitive input.

See [Validation](../security/validation.md) for built-in rules and partial updates.

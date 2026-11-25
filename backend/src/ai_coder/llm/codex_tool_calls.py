"""Describe and validate the structured arguments for Codex role tools."""

from jsonschema import Draft202012Validator


def _closed_object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _argument_schema(schema, *, provider_output):
    result = {key: value for key, value in schema.items() if key != "default"}
    if schema.get("type") == "object" or "properties" in schema:
        required = schema.get("required", [])
        properties = {}
        for name, field in schema.get("properties", {}).items():
            adapted = _argument_schema(field, provider_output=provider_output)
            if provider_output and name not in required and not Draft202012Validator(field).is_valid(None):
                adapted = {"anyOf": [adapted, {"type": "null"}]}
            properties[name] = adapted
        result.update(_closed_object(properties, None if provider_output else required))
        result["type"] = schema.get("type", "object")
    if "items" in schema:
        result["items"] = _argument_schema(schema["items"], provider_output=provider_output)
    if "anyOf" in schema:
        result["anyOf"] = [_argument_schema(option, provider_output=provider_output) for option in schema["anyOf"]]
    return result


def _tool_parameters(tool):
    return tool.get("parameters") or {"type": "object"}


def tool_reply_schema(tools):
    variants = [
        _closed_object({
            "name": {"type": "string", "enum": [tool["name"]]},
            "arguments": _argument_schema(_tool_parameters(tool), provider_output=True),
        })
        for tool in tools
    ]
    if variants:
        calls = {"type": "array", "items": variants[0] if len(variants) == 1 else {"anyOf": variants}}
    else:
        calls = {"type": "array", "items": _closed_object({}), "maxItems": 0}
    return _closed_object({"content": {"type": "string"}, "tool_calls": calls})


def _without_null_placeholders(value, schema):
    if isinstance(value, dict) and "properties" in schema:
        properties = schema["properties"]
        required = schema.get("required", [])
        return {
            name: _without_null_placeholders(item, properties.get(name, {}))
            for name, item in value.items()
            if (item is not None or name not in properties or name in required
                or Draft202012Validator(properties[name]).is_valid(None))
        }
    if isinstance(value, list) and "items" in schema:
        return [_without_null_placeholders(item, schema["items"]) for item in value]
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            normalized = _without_null_placeholders(value, option)
            if Draft202012Validator(option).is_valid(normalized):
                return normalized
    return value


def validated_tool_arguments(tool, raw_args):
    if not isinstance(raw_args, dict):
        raise ValueError("arguments must be an object")
    schema = _argument_schema(_tool_parameters(tool), provider_output=False)
    arguments = _without_null_placeholders(raw_args, schema)
    error = next(Draft202012Validator(schema).iter_errors(arguments), None)
    if error is None:
        return arguments
    field = "arguments" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
    )
    if error.validator == "required":
        missing = next(name for name in error.validator_value if name not in error.instance)
        raise ValueError(f"{field}.{missing} is required")
    if error.validator == "type":
        kind = error.validator_value
        raise ValueError(f"{field} must be {' or '.join(kind) if isinstance(kind, list) else kind}")
    if error.validator == "additionalProperties":
        raise ValueError(f"{field} contains an unexpected field")
    if error.validator == "enum":
        raise ValueError(f"{field} must use an allowed value")
    raise ValueError(f"{field} failed the {error.validator} constraint")
